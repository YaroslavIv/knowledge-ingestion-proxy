import json

import respx
from httpx import Response

GENERATED_HTML_V1 = "<html><body><h1>Module 01</h1><p>Original lecture content.</p></body></html>"
REVISED_HTML_V2 = (
    "<html><body><h1>Module 01</h1><p>Original lecture content.</p>"
    "<section><h2>Practice</h2><p>New practice exercise added.</p></section></body></html>"
)


async def _create_project_with_module(client, name="Generate Test Project"):
    project = (
        await client.post(
            "/api/courses",
            json={
                "name": name,
                "product_knowledge_ids": ["kb-product"],
                "instructions_knowledge_ids": ["kb-instructions"],
            },
        )
    ).json()
    module = (
        await client.post(
            f"/api/courses/{project['id']}/modules",
            json={"title": "Module 01 — Intro", "learning_objectives": ["Explain the basics"]},
        )
    ).json()
    return project, module


@respx.mock
async def test_generation_context_reports_files_and_current_version_state(client):
    project, module = await _create_project_with_module(client)

    respx.get("http://fake-owui.test/api/v1/knowledge/").mock(
        return_value=Response(200, json=[{"id": "kb-product", "name": "Product Docs", "description": ""}])
    )
    respx.get("http://fake-owui.test/api/v1/knowledge/kb-product/files").mock(
        return_value=Response(200, json={"items": [{"id": "file-a", "filename": "datasheet.txt", "meta": {}}]})
    )
    respx.get("http://fake-owui.test/api/v1/knowledge/kb-instructions/files").mock(
        return_value=Response(200, json={"items": []})
    )

    resp = await client.get(f"/api/courses/{project['id']}/modules/{module['id']}/generation-context")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "product_files": [{"knowledge_id": "kb-product", "knowledge_name": "Product Docs", "filenames": ["datasheet.txt"]}],
        "competitor_files": [],
        "instructions_files": [{"knowledge_id": "kb-instructions", "knowledge_name": "kb-instructions", "filenames": []}],
        "visual_present": False,
        "feedback_notes_count": 0,
        "has_current_version": False,
    }


@respx.mock
async def test_generate_from_scratch_pulls_files_from_all_product_collections(client):
    """Product material can be split across several collections — a
    generation call must merge files from every one of them, not just the
    first."""
    project = (
        await client.post(
            "/api/courses",
            json={
                "name": "Multi-collection project",
                "product_knowledge_ids": ["kb-product-a", "kb-product-b"],
                "instructions_knowledge_ids": ["kb-instructions"],
            },
        )
    ).json()
    module = (
        await client.post(
            f"/api/courses/{project['id']}/modules",
            json={"title": "Module 01", "learning_objectives": []},
        )
    ).json()

    respx.get("http://fake-owui.test/api/v1/knowledge/kb-product-a/files").mock(
        return_value=Response(200, json={"items": [{"id": "file-a", "filename": "datasheet-a.txt", "meta": {}}]})
    )
    respx.get("http://fake-owui.test/api/v1/files/file-a/data/content").mock(
        return_value=Response(200, json={"content": "Product A supports 1000 FPS."})
    )
    respx.get("http://fake-owui.test/api/v1/knowledge/kb-product-b/files").mock(
        return_value=Response(200, json={"items": [{"id": "file-b", "filename": "datasheet-b.txt", "meta": {}}]})
    )
    respx.get("http://fake-owui.test/api/v1/files/file-b/data/content").mock(
        return_value=Response(200, json={"content": "Product B ships in Q3."})
    )
    respx.get("http://fake-owui.test/api/v1/knowledge/kb-instructions/files").mock(
        return_value=Response(200, json={"items": []})
    )
    chat_route = respx.post("http://fake-owui.test/api/v1/chat/completions").mock(
        return_value=Response(200, json={"choices": [{"message": {"content": GENERATED_HTML_V1}}]})
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        return_value=Response(200, json={"id": "kb-output", "name": "x", "description": ""})
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/kb-output/file/add").mock(return_value=Response(200))
    respx.post("http://fake-owui.test/api/v1/files/").mock(
        return_value=Response(200, json={"id": "file-out-1", "filename": "m.md"})
    )

    resp = await client.post(
        f"/api/courses/{project['id']}/modules/{module['id']}/output/generate",
        json={"model": "gpt-4o-mini", "instruction": "Write it."},
    )
    assert resp.status_code == 200

    sent_prompt = json.loads(chat_route.calls[0].request.content)["messages"][1]["content"]
    assert "Product A supports 1000 FPS." in sent_prompt
    assert "Product B ships in Q3." in sent_prompt


@respx.mock
async def test_generate_from_scratch_when_no_prior_version_exists(client):
    project, module = await _create_project_with_module(client)

    respx.get("http://fake-owui.test/api/v1/knowledge/kb-product/files").mock(
        return_value=Response(200, json={"items": [{"id": "file-a", "filename": "datasheet.txt", "meta": {}}]})
    )
    respx.get("http://fake-owui.test/api/v1/files/file-a/data/content").mock(
        return_value=Response(200, json={"content": "Elite supports 1000 FPS."})
    )
    respx.get("http://fake-owui.test/api/v1/knowledge/kb-instructions/files").mock(
        return_value=Response(200, json={"items": []})
    )
    respx.post("http://fake-owui.test/api/v1/chat/completions").mock(
        return_value=Response(200, json={"choices": [{"message": {"content": GENERATED_HTML_V1}}]})
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        return_value=Response(200, json={"id": "kb-output", "name": "x", "description": ""})
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/kb-output/file/add").mock(return_value=Response(200))
    upload_route = respx.post("http://fake-owui.test/api/v1/files/").mock(
        return_value=Response(200, json={"id": "file-out-1", "filename": "m.md"})
    )

    resp = await client.post(
        f"/api/courses/{project['id']}/modules/{module['id']}/output/generate",
        json={"model": "gpt-4o-mini", "instruction": "Write the first version."},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["content_type"] == "text/html"
    assert body["has_html"] is True
    assert body["is_current"] is True

    kb_content = upload_route.calls[-1].request.content.decode("utf-8")  # raw artifact uploads first
    assert "Original lecture content." in kb_content
    assert "Write the first version." in kb_content  # notes = instruction


@respx.mock
async def test_generate_can_scope_to_a_subset_of_product_collections(client):
    """An explicit product_knowledge_ids list narrows which collections this
    one call draws from — kb-product-b's files endpoint is deliberately
    never mocked, so the request would error if it were fetched anyway."""
    project = (
        await client.post(
            "/api/courses",
            json={
                "name": "Scoped project",
                "product_knowledge_ids": ["kb-product-a", "kb-product-b"],
                "instructions_knowledge_ids": ["kb-instructions"],
            },
        )
    ).json()
    module = (
        await client.post(
            f"/api/courses/{project['id']}/modules",
            json={"title": "Module 01", "learning_objectives": []},
        )
    ).json()

    respx.get("http://fake-owui.test/api/v1/knowledge/kb-product-a/files").mock(
        return_value=Response(200, json={"items": [{"id": "file-a", "filename": "datasheet-a.txt", "meta": {}}]})
    )
    respx.get("http://fake-owui.test/api/v1/files/file-a/data/content").mock(
        return_value=Response(200, json={"content": "Product A supports 1000 FPS."})
    )
    respx.get("http://fake-owui.test/api/v1/knowledge/kb-instructions/files").mock(
        return_value=Response(200, json={"items": []})
    )
    chat_route = respx.post("http://fake-owui.test/api/v1/chat/completions").mock(
        return_value=Response(200, json={"choices": [{"message": {"content": GENERATED_HTML_V1}}]})
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        return_value=Response(200, json={"id": "kb-output", "name": "x", "description": ""})
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/kb-output/file/add").mock(return_value=Response(200))
    respx.post("http://fake-owui.test/api/v1/files/").mock(
        return_value=Response(200, json={"id": "file-out-1", "filename": "m.md"})
    )

    resp = await client.post(
        f"/api/courses/{project['id']}/modules/{module['id']}/output/generate",
        json={"model": "gpt-4o-mini", "instruction": "Write it.", "product_knowledge_ids": ["kb-product-a"]},
    )
    assert resp.status_code == 200

    sent_prompt = json.loads(chat_route.calls[0].request.content)["messages"][1]["content"]
    assert "Product A supports 1000 FPS." in sent_prompt


@respx.mock
async def test_generate_persists_scoping_choices_for_the_next_call(client):
    """last_generation_settings prefills the next generate/revise call on
    this module, so a deliberately narrowed scope doesn't have to be redone
    by hand every time."""
    project, module = await _create_project_with_module(client)

    respx.get("http://fake-owui.test/api/v1/knowledge/kb-instructions/files").mock(
        return_value=Response(200, json={"items": []})
    )
    respx.post("http://fake-owui.test/api/v1/chat/completions").mock(
        return_value=Response(200, json={"choices": [{"message": {"content": GENERATED_HTML_V1}}]})
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        return_value=Response(200, json={"id": "kb-output", "name": "x", "description": ""})
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/kb-output/file/add").mock(return_value=Response(200))
    respx.post("http://fake-owui.test/api/v1/files/").mock(
        return_value=Response(200, json={"id": "file-out-1", "filename": "m.md"})
    )

    resp = await client.post(
        f"/api/courses/{project['id']}/modules/{module['id']}/output/generate",
        json={
            "model": "gpt-4o-mini",
            "instruction": "Write it.",
            "product_knowledge_ids": [],
            "instructions_knowledge_ids": [],
            "include_visual": False,
        },
    )
    assert resp.status_code == 200

    modules = (await client.get(f"/api/courses/{project['id']}/modules")).json()
    saved = modules[0]["last_generation_settings"]
    assert saved["product_knowledge_ids"] == []
    assert saved["instructions_knowledge_ids"] == []
    assert saved["include_visual"] is False


@respx.mock
async def test_revise_uses_current_html_as_context_and_creates_new_version(client):
    project, module = await _create_project_with_module(client)

    # First, publish a manual v1.0 with real HTML so a "current version" exists.
    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        return_value=Response(200, json={"id": "kb-output", "name": "x", "description": ""})
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/kb-output/file/add").mock(return_value=Response(200))
    respx.post("http://fake-owui.test/api/v1/files/").mock(
        return_value=Response(200, json={"id": "file-out-1", "filename": "m.md"})
    )
    await client.post(
        f"/api/courses/{project['id']}/modules/{module['id']}/output",
        files={"file": ("module_01.html", GENERATED_HTML_V1.encode("utf-8"), "text/html")},
    )

    respx.get("http://fake-owui.test/api/v1/knowledge/kb-product/files").mock(
        return_value=Response(200, json={"items": []})
    )
    respx.get("http://fake-owui.test/api/v1/knowledge/kb-instructions/files").mock(
        return_value=Response(200, json={"items": []})
    )
    edit_payload = json.dumps(
        {
            "edits": [
                {
                    "find": "</body></html>",
                    "replace": '<section><h2>Practice</h2><p>New practice exercise added.</p></section></body></html>',
                }
            ]
        }
    )
    chat_route = respx.post("http://fake-owui.test/api/v1/chat/completions").mock(
        return_value=Response(200, json={"choices": [{"message": {"content": edit_payload}}]})
    )
    update_route = respx.post("http://fake-owui.test/api/v1/files/file-out-1/data/content/update").mock(
        return_value=Response(200)
    )

    resp = await client.post(
        f"/api/courses/{project['id']}/modules/{module['id']}/output/generate",
        json={"model": "gpt-4o-mini", "instruction": "Add a practice exercise section."},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_current"] is True

    # the revise prompt embedded the CURRENT html, proving it read it back off disk
    sent_prompt = json.loads(chat_route.calls[0].request.content)["messages"][1]["content"]
    assert "Original lecture content." in sent_prompt
    assert "Add a practice exercise section." in sent_prompt

    assert update_route.called
    assert "New practice exercise added." in update_route.calls[0].request.content.decode("utf-8")

    versions = (
        await client.get(f"/api/courses/{project['id']}/modules/{module['id']}/output/versions")
    ).json()
    assert len(versions) == 2
    current = next(v for v in versions if v["is_current"])
    old = next(v for v in versions if not v["is_current"])
    assert current["filename"] == "Module 01 — Intro.html"
    assert old["is_current"] is False


@respx.mock
async def test_revise_always_pulls_in_current_product_and_instructions(client):
    project, module = await _create_project_with_module(client)
    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        return_value=Response(200, json={"id": "kb-output", "name": "x", "description": ""})
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/kb-output/file/add").mock(return_value=Response(200))
    respx.post("http://fake-owui.test/api/v1/files/").mock(
        return_value=Response(200, json={"id": "file-out-1", "filename": "m.md"})
    )
    await client.post(
        f"/api/courses/{project['id']}/modules/{module['id']}/output",
        files={"file": ("module_01.html", GENERATED_HTML_V1.encode("utf-8"), "text/html")},
    )

    respx.get("http://fake-owui.test/api/v1/knowledge/kb-product/files").mock(
        return_value=Response(200, json={"items": [{"id": "file-a", "filename": "datasheet.txt", "meta": {}}]})
    )
    respx.get("http://fake-owui.test/api/v1/files/file-a/data/content").mock(
        return_value=Response(200, json={"content": "Elite supports 1000 FPS."})
    )
    respx.get("http://fake-owui.test/api/v1/knowledge/kb-instructions/files").mock(
        return_value=Response(200, json={"items": []})
    )
    edit_payload = json.dumps({"edits": [{"find": "</body></html>", "replace": "<p>done</p></body></html>"}]})
    chat_route = respx.post("http://fake-owui.test/api/v1/chat/completions").mock(
        return_value=Response(200, json={"choices": [{"message": {"content": edit_payload}}]})
    )
    respx.post("http://fake-owui.test/api/v1/files/file-out-1/data/content/update").mock(return_value=Response(200))

    resp = await client.post(
        f"/api/courses/{project['id']}/modules/{module['id']}/output/generate",
        json={
            "model": "gpt-4o-mini",
            "instruction": "Add a practice exercise using a real product fact.",
        },
    )
    assert resp.status_code == 200

    sent_prompt = json.loads(chat_route.calls[0].request.content)["messages"][1]["content"]
    assert "Elite supports 1000 FPS." in sent_prompt


@respx.mock
async def test_generate_new_module_always_lists_other_modules_and_optionally_their_content(client):
    project, module_a = await _create_project_with_module(client)
    module_b = (
        await client.post(
            f"/api/courses/{project['id']}/modules",
            json={"title": "Module 09 — Final Test", "learning_objectives": ["Test retained knowledge"]},
        )
    ).json()

    # module_a already has a published version with real content
    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        return_value=Response(200, json={"id": "kb-output", "name": "x", "description": ""})
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/kb-output/file/add").mock(return_value=Response(200))
    respx.post("http://fake-owui.test/api/v1/files/").mock(
        side_effect=[
            Response(200, json={"id": "raw-a-1", "filename": "module_01.html"}),
            Response(200, json={"id": "file-out-a", "filename": "m.md"}),
            Response(200, json={"id": "raw-b-1", "filename": "module_09.html"}),
            Response(200, json={"id": "file-out-b", "filename": "m2.md"}),
        ]
    )
    await client.post(
        f"/api/courses/{project['id']}/modules/{module_a['id']}/output",
        files={"file": ("module_01.html", GENERATED_HTML_V1.encode("utf-8"), "text/html")},
    )

    respx.get("http://fake-owui.test/api/v1/knowledge/kb-product/files").mock(
        return_value=Response(200, json={"items": []})
    )
    respx.get("http://fake-owui.test/api/v1/knowledge/kb-instructions/files").mock(
        return_value=Response(200, json={"items": []})
    )
    chat_route = respx.post("http://fake-owui.test/api/v1/chat/completions").mock(
        return_value=Response(200, json={"choices": [{"message": {"content": GENERATED_HTML_V1}}]})
    )

    resp = await client.post(
        f"/api/courses/{project['id']}/modules/{module_b['id']}/output/generate",
        json={
            "model": "gpt-4o-mini",
            "instruction": "Only quiz on what this course actually covered.",
            "other_module_ids": [module_a["id"]],
        },
    )
    assert resp.status_code == 200

    sent_prompt = json.loads(chat_route.calls[0].request.content)["messages"][1]["content"]
    assert "Module 01 — Intro" in sent_prompt  # always listed
    assert "Explain the basics" in sent_prompt  # its learning objective
    assert "Original lecture content." in sent_prompt  # its actual extracted content, since opted in
    assert "VISUAL STYLE TEMPLATE" in sent_prompt  # style reference always included for a fresh module
    assert "<h1>Module 01</h1>" in sent_prompt  # the reference module's real HTML, not stripped text


@respx.mock
async def test_generate_new_module_includes_style_reference_even_without_other_modules_content(client):
    """A brand-new module needs a real visual template to match even when the
    caller didn't opt into pulling in the other modules' actual TEXT content —
    style and content are independent concerns (confirmed live: a from-scratch
    module generated with no style reference invented its own unrelated look)."""
    project, module_a = await _create_project_with_module(client)
    module_b = (
        await client.post(
            f"/api/courses/{project['id']}/modules",
            json={"title": "Module 02 — Objections", "learning_objectives": ["Handle objections"]},
        )
    ).json()

    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        return_value=Response(200, json={"id": "kb-output", "name": "x", "description": ""})
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/kb-output/file/add").mock(return_value=Response(200))
    respx.post("http://fake-owui.test/api/v1/files/").mock(
        side_effect=[
            Response(200, json={"id": "raw-a-1", "filename": "module_01.html"}),
            Response(200, json={"id": "file-out-a", "filename": "m.md"}),
            Response(200, json={"id": "raw-b-1", "filename": "module_02.html"}),
            Response(200, json={"id": "file-out-b", "filename": "m2.md"}),
        ]
    )
    await client.post(
        f"/api/courses/{project['id']}/modules/{module_a['id']}/output",
        files={"file": ("module_01.html", GENERATED_HTML_V1.encode("utf-8"), "text/html")},
    )

    respx.get("http://fake-owui.test/api/v1/knowledge/kb-product/files").mock(
        return_value=Response(200, json={"items": []})
    )
    respx.get("http://fake-owui.test/api/v1/knowledge/kb-instructions/files").mock(
        return_value=Response(200, json={"items": []})
    )
    chat_route = respx.post("http://fake-owui.test/api/v1/chat/completions").mock(
        return_value=Response(200, json={"choices": [{"message": {"content": GENERATED_HTML_V1}}]})
    )

    resp = await client.post(
        f"/api/courses/{project['id']}/modules/{module_b['id']}/output/generate",
        json={"model": "gpt-4o-mini", "instruction": "Write it"},
    )
    assert resp.status_code == 200

    sent_prompt = json.loads(chat_route.calls[0].request.content)["messages"][1]["content"]
    assert "VISUAL STYLE TEMPLATE" in sent_prompt
    assert "<h1>Module 01</h1>" in sent_prompt


@respx.mock
async def test_regenerate_from_scratch_ignores_the_existing_version_and_rewrites_fully(client):
    """A module that came out badly (e.g. an earlier from-scratch generation
    invented its own layout instead of matching the course) can't reasonably
    be fixed via small find/replace edits — regenerate_from_scratch forces
    the from-scratch path (materials, other-modules, style reference) even
    though a current version already exists, superseding it with a full
    rewrite instead of patching it."""
    project, module_a = await _create_project_with_module(client)
    module_b = (
        await client.post(
            f"/api/courses/{project['id']}/modules",
            json={"title": "Module 09 — Final Test", "learning_objectives": []},
        )
    ).json()

    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        return_value=Response(200, json={"id": "kb-output", "name": "x", "description": ""})
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/kb-output/file/add").mock(return_value=Response(200))
    respx.post("http://fake-owui.test/api/v1/files/").mock(
        side_effect=[
            Response(200, json={"id": "raw-a-1", "filename": "module_01.html"}),
            Response(200, json={"id": "file-out-a", "filename": "m.md"}),
            Response(200, json={"id": "raw-b-1", "filename": "module_09_v1.html"}),
            Response(200, json={"id": "file-out-b", "filename": "m2.md"}),
            Response(200, json={"id": "raw-b-2", "filename": "module_09_v2.html"}),
        ]
    )
    await client.post(
        f"/api/courses/{project['id']}/modules/{module_a['id']}/output",
        files={"file": ("module_01.html", GENERATED_HTML_V1.encode("utf-8"), "text/html")},
    )
    # module_b already has a badly-styled version, unrelated to the rest of the course
    respx.get("http://fake-owui.test/api/v1/knowledge/kb-product/files").mock(
        return_value=Response(200, json={"items": []})
    )
    respx.get("http://fake-owui.test/api/v1/knowledge/kb-instructions/files").mock(
        return_value=Response(200, json={"items": []})
    )
    respx.post("http://fake-owui.test/api/v1/chat/completions").mock(
        return_value=Response(
            200, json={"choices": [{"message": {"content": "<html><body>Off-style v1</body></html>"}}]}
        )
    )
    await client.post(
        f"/api/courses/{project['id']}/modules/{module_b['id']}/output/generate",
        json={"model": "gpt-4o-mini", "instruction": "Write it"},
    )

    # now regenerate from scratch — must go down the from-scratch path again,
    # not treat the badly-styled version as "current html" to revise
    chat_route = respx.post("http://fake-owui.test/api/v1/chat/completions").mock(
        return_value=Response(200, json={"choices": [{"message": {"content": GENERATED_HTML_V1}}]})
    )
    respx.post("http://fake-owui.test/api/v1/files/file-out-b/data/content/update").mock(return_value=Response(200))
    resp = await client.post(
        f"/api/courses/{project['id']}/modules/{module_b['id']}/output/generate",
        json={"model": "gpt-4o-mini", "instruction": "Redo it properly", "regenerate_from_scratch": True},
    )
    assert resp.status_code == 200

    sent_prompt = json.loads(chat_route.calls[0].request.content)["messages"][1]["content"]
    assert "Off-style v1" not in sent_prompt  # never treated as current_html to revise
    assert "VISUAL STYLE TEMPLATE" in sent_prompt  # gets the real style template this time
    assert "<h1>Module 01</h1>" in sent_prompt

    versions = (
        await client.get(f"/api/courses/{project['id']}/modules/{module_b['id']}/output/versions")
    ).json()
    assert len(versions) == 2  # nothing lost — the badly-styled version is kept in history


@respx.mock
async def test_content_endpoint_returns_cached_html_for_diffing(client):
    project, module = await _create_project_with_module(client)
    respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
        return_value=Response(200, json={"id": "kb-output", "name": "x", "description": ""})
    )
    respx.post("http://fake-owui.test/api/v1/knowledge/kb-output/file/add").mock(return_value=Response(200))
    respx.post("http://fake-owui.test/api/v1/files/").mock(
        return_value=Response(200, json={"id": "file-out-1", "filename": "m.md"})
    )
    await client.post(
        f"/api/courses/{project['id']}/modules/{module['id']}/output",
        files={"file": ("module_01.html", GENERATED_HTML_V1.encode("utf-8"), "text/html")},
    )
    versions = (
        await client.get(f"/api/courses/{project['id']}/modules/{module['id']}/output/versions")
    ).json()
    version_id = versions[0]["id"]

    resp = await client.get(
        f"/api/courses/{project['id']}/modules/{module['id']}/output/versions/{version_id}/content"
    )
    assert resp.status_code == 200
    assert resp.json()["content"] == GENERATED_HTML_V1


async def test_content_endpoint_404s_when_no_html_cached(client):
    project, module = await _create_project_with_module(client)
    with respx.mock:
        respx.post("http://fake-owui.test/api/v1/knowledge/create").mock(
            return_value=Response(200, json={"id": "kb-output", "name": "x", "description": ""})
        )
        respx.post("http://fake-owui.test/api/v1/knowledge/kb-output/file/add").mock(return_value=Response(200))
        respx.post("http://fake-owui.test/api/v1/files/").mock(
            return_value=Response(200, json={"id": "file-out-1", "filename": "m.md"})
        )
        await client.post(
            f"/api/courses/{project['id']}/modules/{module['id']}/output",
            files={"file": ("notes.txt", b"plain text, not html", "text/plain")},
        )
    versions = (
        await client.get(f"/api/courses/{project['id']}/modules/{module['id']}/output/versions")
    ).json()
    version_id = versions[0]["id"]

    resp = await client.get(
        f"/api/courses/{project['id']}/modules/{module['id']}/output/versions/{version_id}/content"
    )
    assert resp.status_code == 404


@respx.mock
async def test_generate_rejects_non_html_model_response(client):
    project, module = await _create_project_with_module(client)
    respx.get("http://fake-owui.test/api/v1/knowledge/kb-product/files").mock(
        return_value=Response(200, json={"items": []})
    )
    respx.get("http://fake-owui.test/api/v1/knowledge/kb-instructions/files").mock(
        return_value=Response(200, json={"items": []})
    )
    respx.post("http://fake-owui.test/api/v1/chat/completions").mock(
        return_value=Response(200, json={"choices": [{"message": {"content": "I refuse."}}]})
    )

    resp = await client.post(
        f"/api/courses/{project['id']}/modules/{module['id']}/output/generate",
        json={"model": "gpt-4o-mini", "instruction": "Write it"},
    )
    assert resp.status_code == 502
