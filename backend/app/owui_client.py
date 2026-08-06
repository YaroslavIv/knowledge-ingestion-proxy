import json
import re
from urllib.parse import unquote

import httpx

from app.config import settings

_FILENAME_STAR_RE = re.compile(r"filename\*=UTF-8''([^;]+)", re.IGNORECASE)


def _filename_from_content_disposition(disposition: str) -> str | None:
    match = _FILENAME_STAR_RE.search(disposition)
    return unquote(match.group(1)) if match else None


class OwuiError(RuntimeError):
    def __init__(self, status_code: int, detail: str):
        super().__init__(f"Open WebUI returned {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


class OwuiClient:
    """Thin wrapper around the Open WebUI HTTP API.

    Everything goes through this one client so the service-account API key
    never has to be touched anywhere else in the codebase (and never reaches
    the proxy's own frontend).
    """

    def __init__(self, base_url: str | None = None, api_key: str | None = None):
        self._base_url = (base_url or settings.owui_base_url).rstrip("/")
        self._api_key = api_key or settings.owui_api_key

    @property
    def base_url(self) -> str:
        return self._base_url

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    async def list_knowledge_bases(self) -> list[dict]:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=30) as client:
            resp = await client.get("/api/v1/knowledge/", headers=self._headers())
            self._raise_for_status(resp)
            data = resp.json()
            return data if isinstance(data, list) else data.get("items", data)

    async def create_knowledge_base(self, name: str, description: str = "") -> dict:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=30) as client:
            resp = await client.post(
                "/api/v1/knowledge/create",
                headers=self._headers(),
                json={"name": name, "description": description},
            )
            self._raise_for_status(resp)
            return resp.json()

    async def delete_knowledge_base(self, knowledge_id: str) -> None:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=30) as client:
            resp = await client.delete(
                f"/api/v1/knowledge/{knowledge_id}/delete",
                headers=self._headers(),
            )
            self._raise_for_status(resp)

    async def get_retrieval_config(self) -> dict:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=30) as client:
            resp = await client.get("/api/v1/retrieval/config", headers=self._headers())
            self._raise_for_status(resp)
            return resp.json()

    async def get_embedding_config(self) -> dict:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=30) as client:
            resp = await client.get("/api/v1/retrieval/embedding", headers=self._headers())
            self._raise_for_status(resp)
            return resp.json()

    async def query_collection(self, collection_ids: list[str], query: str, k: int = 3) -> dict:
        """Pure vector search against one or more knowledge-base collections
        — no LLM call, just matching chunks + a `distances` field. Despite
        the name, confirmed empirically that this is a similarity score,
        not a distance: for a fixed query, results come back sorted with
        the HIGHEST value first (the best match), decreasing from there —
        so higher is better, not lower. Used to score/compare collections
        for routing; not used for the actual answer (that goes through
        chat_completion's `files` hook, which does its own retrieval
        internally).

        `hybrid` is forced to False: confirmed live against a real
        corporate instance that the hybrid-search path (the default when
        omitted, since this instance has ENABLE_RAG_HYBRID_SEARCH on) 200s
        but silently returns empty results — a server-side bug on that
        version, not something detectable via status code. Plain vector
        search (hybrid=False) returns real, correctly-ranked results there.
        """
        async with httpx.AsyncClient(base_url=self._base_url, timeout=30) as client:
            resp = await client.post(
                "/api/v1/retrieval/query/collection",
                headers=self._headers(),
                json={"collection_names": collection_ids, "query": query, "k": k, "hybrid": False},
            )
            self._raise_for_status(resp)
            return resp.json()

    async def list_models(self) -> list[dict]:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=30) as client:
            resp = await client.get("/api/v1/models", headers=self._headers())
            if resp.status_code == 200 and "application/json" in resp.headers.get("content-type", ""):
                data = resp.json()
                return data.get("data", data) if isinstance(data, dict) else data

            # Confirmed live against a real corporate instance: this endpoint
            # 200s with the SPA's own index.html (no backend route matches
            # it) instead of JSON. `/api/models` (no v1 prefix) is Open
            # WebUI's own "models visible in this instance's chat UI" list —
            # the same one its own model picker shows — and works reliably
            # here, so it's a strictly better fallback than failing outright.
            fallback_resp = await client.get("/api/models", headers=self._headers())
            self._raise_for_status(fallback_resp)
            data = fallback_resp.json()
            return data.get("data", data) if isinstance(data, dict) else data

    async def chat_completion(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.2,
        response_format: dict | None = None,
        files: list[dict] | None = None,
        return_raw: bool = False,
    ) -> str | dict:
        """One OpenAI-compatible chat completion — this is how course
        generation talks to an LLM: through whatever provider Open WebUI
        itself has configured, never a second API key held by this proxy.
        Returns the assistant message's raw content string by default.

        `files` is Open WebUI's own native RAG hook — e.g.
        `[{"type": "collection", "id": knowledge_id}]` to retrieve and inject
        the most relevant chunks from that knowledge base before answering,
        or `[{"type": "file", "id": file_id}]` to scope to one specific
        document. Passing several `{"type": "collection", ...}` entries
        queries each collection independently (its own top-k) and merges
        the results into one prompt — confirmed live, this is how "answer
        using the best matches across several collections" works with zero
        extra retrieval code on our side.

        `return_raw=True` returns the full response body instead of just
        the message content — when `files` is used, Open WebUI adds a
        `sources` field alongside the usual `choices`/`usage`/etc., listing
        exactly which chunks (with `file_id`/`name`/`score`) fed the answer.
        Callers that just want the text (course generation) leave this off.
        """
        body: dict = {"model": model, "messages": messages, "temperature": temperature}
        if response_format is not None:
            body["response_format"] = response_format
        if files is not None:
            body["files"] = files

        # A full-module revise/generate call can embed 100KB+ of HTML and ask
        # for a similarly large document back — a slow model can legitimately
        # take longer than an ordinary chat call, so this timeout is generous
        # on purpose. httpx.TimeoutException/ConnectError are still real
        # failure modes (a stuck model, a dead Open WebUI instance), so they
        # get wrapped as OwuiError like every HTTP-status failure, instead of
        # bubbling up as an unhandled 500.
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=300) as client:
                resp = await self._post_chat_completion(client, body)
                if resp.status_code == 400 and self._mentions_temperature(resp):
                    # Some newer reasoning-style models (GPT-5-class and
                    # similar) reject any non-default temperature at all via
                    # the OpenAI-compatible API — confirmed by the error
                    # text itself naming the parameter. Retrying once with it
                    # omitted entirely beats failing the whole
                    # generation/revision call outright over a parameter
                    # this proxy doesn't actually need to control.
                    retry_body = {k: v for k, v in body.items() if k != "temperature"}
                    resp = await self._post_chat_completion(client, retry_body)
                self._raise_for_status(resp)
                data = resp.json()
                if return_raw:
                    return data
                return data["choices"][0]["message"]["content"]
        except httpx.HTTPError as e:
            raise OwuiError(status_code=502, detail=f"Request to Open WebUI failed: {e}") from e

    async def _post_chat_completion(self, client: httpx.AsyncClient, body: dict) -> httpx.Response:
        resp = await client.post(
            "/api/v1/chat/completions",
            headers=self._headers(),
            json=body,
        )
        if resp.status_code == 405 or (
            resp.status_code == 200 and "application/json" not in resp.headers.get("content-type", "")
        ):
            # Confirmed live: this corporate instance's /api/v1/*
            # OpenAI-compatibility routes can go stale/break independently
            # of the rest of the API — the exact same symptom already seen
            # on /api/v1/models and /api/v1/knowledge/{id}/files (see
            # list_models and list_knowledge_files above). /api/chat/completions
            # (no v1) is Open WebUI's own native chat endpoint and works
            # reliably there.
            resp = await client.post(
                "/api/chat/completions",
                headers=self._headers(),
                json=body,
            )
        return resp

    @staticmethod
    def _mentions_temperature(resp: httpx.Response) -> bool:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:  # noqa: BLE001
            detail = resp.text
        return "temperature" in str(detail).lower()

    async def upload_file_to_knowledge(
        self, filename: str, content: str, knowledge_id: str
    ) -> dict:
        """Push final (already-redacted) text as a new file, linked to a knowledge base.

        Uses process=true&process_in_background=false so the extraction/embedding
        happens synchronously and we get a real file_id back in this same call.
        `metadata.knowledge_id` alone is NOT reliably enough to make the file a real
        member of the knowledge base — confirmed live against a real corporate Open
        WebUI instance where uploads landed in their own isolated per-file vector
        collection (`meta.collection_name == "file-{id}"`) and never appeared in the
        knowledge base's own `/file/add`, or in Open WebUI's own UI, until this
        explicit follow-up call. Newer Open WebUI versions auto-link during upload
        (issue #24807) and tolerate this call being redundant; this makes the
        behavior correct on both.
        """
        files = {"file": (filename, content.encode("utf-8"), "text/markdown")}
        data = {"metadata": json.dumps({"knowledge_id": knowledge_id})}
        params = {"process": "true", "process_in_background": "false"}

        async with httpx.AsyncClient(base_url=self._base_url, timeout=120) as client:
            resp = await client.post(
                "/api/v1/files/",
                headers=self._headers(),
                params=params,
                files=files,
                data=data,
            )
            self._raise_for_status(resp)
            result = resp.json()

            add_resp = await client.post(
                f"/api/v1/knowledge/{knowledge_id}/file/add",
                headers=self._headers(),
                json={"file_id": result["id"]},
            )
            self._raise_for_status(add_resp)

            return result

    async def upload_raw_file(self, filename: str, data: bytes, content_type: str, knowledge_id: str) -> dict:
        """Store the actual published artifact (a SCORM zip, a raw HTML page,
        whatever the caller published) as a real Open WebUI file.

        Uses process=false: this is a finished deliverable, not something Open
        WebUI needs to extract/embed text from — that's the separate
        `upload_file_to_knowledge` manifest-text flow, which stays the thing
        actually linked into the knowledge base for search. Confirmed live
        against a real corporate instance: a binary zip can never be linked
        into a knowledge base's own file list this way (`/file/add` 400s with
        "Extracted content is not available for this file"), but it uploads
        and downloads back byte-identical when process=false, which is enough
        to make it genuinely present inside Open WebUI's own storage.
        """
        files = {"file": (filename, data, content_type)}
        params = {"process": "false"}

        async with httpx.AsyncClient(base_url=self._base_url, timeout=120) as client:
            resp = await client.post(
                "/api/v1/files/",
                headers=self._headers(),
                params=params,
                files=files,
            )
            self._raise_for_status(resp)
            return resp.json()

    async def list_knowledge_files(self, knowledge_id: str, include_content: bool = False) -> dict:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=30) as client:
            resp = await client.get(
                f"/api/v1/knowledge/{knowledge_id}/files",
                headers=self._headers(),
                params={"include_content": "true" if include_content else "false"},
            )
            if resp.status_code == 200 and "application/json" in resp.headers.get("content-type", ""):
                return resp.json()

            # Older Open WebUI versions don't expose this dedicated sub-route at
            # all — confirmed live: the request 200s with the SPA's own
            # index.html (SvelteKit's catch-all) instead of a JSON error, since
            # no backend route matches it. Those versions expose the same
            # information as a `files` field embedded directly on the knowledge
            # base's own GET-by-id response instead.
            detail_resp = await client.get(f"/api/v1/knowledge/{knowledge_id}", headers=self._headers())
            self._raise_for_status(detail_resp)
            return detail_resp.json().get("files") or []

    async def get_file_content(self, file_id: str) -> str:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=30) as client:
            resp = await client.get(
                f"/api/v1/files/{file_id}/data/content",
                headers=self._headers(),
            )
            self._raise_for_status(resp)
            return resp.json().get("content", "")

    async def get_file_raw(self, file_id: str) -> tuple[bytes, str, str]:
        """The original bytes Open WebUI has stored for this file, exactly as
        uploaded to *it* — distinct from `get_file_content`'s extracted text.

        For files this proxy itself pushed, that's the same cleaned markdown
        text (we never hand Open WebUI a true original — see finalize_document);
        for files that entered a knowledge base some other way (uploaded
        directly in Open WebUI, or predating this proxy), it's the real
        original file. Returns (content, content_type, filename).
        """
        async with httpx.AsyncClient(base_url=self._base_url, timeout=30) as client:
            resp = await client.get(
                f"/api/v1/files/{file_id}/content",
                headers=self._headers(),
            )
            self._raise_for_status(resp)
            content_type = resp.headers.get("content-type", "application/octet-stream")
            disposition = resp.headers.get("content-disposition", "")
            filename = _filename_from_content_disposition(disposition) or file_id
            return resp.content, content_type, filename

    async def remove_file_from_knowledge(self, knowledge_id: str, file_id: str) -> None:
        """Unlink a file from a knowledge base and delete it outright
        (`delete_file` defaults to true on Open WebUI's own endpoint) —
        removes it from the vector collection and the file registry, not
        just from this one knowledge base's listing.
        """
        async with httpx.AsyncClient(base_url=self._base_url, timeout=30) as client:
            resp = await client.post(
                f"/api/v1/knowledge/{knowledge_id}/file/remove",
                headers=self._headers(),
                params={"delete_file": "true"},
                json={"file_id": file_id},
            )
            self._raise_for_status(resp)

    async def delete_file(self, file_id: str) -> None:
        """Delete a standalone Open WebUI file outright — for files that
        were never linked into any knowledge base (e.g. a course module's
        raw published artifact, uploaded via upload_raw_file with
        process=false), so remove_file_from_knowledge (which needs a
        knowledge_id to unlink from) doesn't apply. Open WebUI's own
        DELETE /api/v1/files/{id} cleans up any KB associations/embeddings
        it does have regardless, so this is also safe to call on a linked
        file if the caller doesn't have a specific knowledge_id at hand.
        """
        async with httpx.AsyncClient(base_url=self._base_url, timeout=30) as client:
            resp = await client.delete(f"/api/v1/files/{file_id}", headers=self._headers())
            self._raise_for_status(resp)

    async def update_file_content(self, file_id: str, content: str) -> None:
        """Overwrite an already-committed file's extracted text.

        Open WebUI re-embeds this content (replacing the file's own vector
        collection and every knowledge base collection referencing it), so
        this is a real re-sync, not just a display-text edit.
        """
        async with httpx.AsyncClient(base_url=self._base_url, timeout=60) as client:
            resp = await client.post(
                f"/api/v1/files/{file_id}/data/content/update",
                headers=self._headers(),
                json={"content": content},
            )
            self._raise_for_status(resp)

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:  # noqa: BLE001
                detail = resp.text
            raise OwuiError(resp.status_code, str(detail))
