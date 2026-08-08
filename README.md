# Knowledge Ingestion Proxy

A document intake tool that sits in front of [Open WebUI](https://github.com/open-webui/open-webui). Upload a
PDF/DOCX/text document, review and fix the parsed text, permanently redact any secret/confidential spans, then push
the cleaned result straight into an Open WebUI knowledge base.

Design background and the reasoning behind it: see `docs/mas-baseline/DB_SCHEMA.md` and
`docs/mas-baseline/INTEGRATION_NOTES.md` in the `open-webui` repo this proxy targets.

## How it works

The UI mirrors Open WebUI's own **Knowledge** section (same list-page layout, badges, "+ New Knowledge" pill) so it
feels like a native extension rather than a separate tool:

1. **Knowledge list** (`/`): pick an existing knowledge base or create a new one.
2. **Knowledge detail**: shows every document already in that base. Click one to open it in an editable pane —
   fix it and click **Update** to re-sync it (re-embeds into every knowledge base collection referencing that file,
   not just a display-text edit).
3. **Add Content**: upload a new PDF/DOCX/TXT/Markdown file. It's parsed **in this proxy**, not by Open WebUI (better
   structure than Open WebUI's own default `pypdf`/`docx2txt` loaders — headings and tables are preserved as
   markdown). The extracted text appears in an editable pane; fix any parsing mistakes directly.
4. Select any text (secrets, confidential sections) and click **Redact selection** — marked spans are shown with a
   red bar and are **permanently cut**, with no placeholder or trace, before anything is sent onward. A live,
   alternating-band overlay also shows the approximate chunk boundaries Open WebUI's embedding pipeline will use
   (computed from the real instance's `CHUNK_SIZE`/`CHUNK_OVERLAP`/splitter config).
5. Click **Send to Open WebUI** — the already-clean text is uploaded as a single file, linked to that knowledge base,
   and immediately visible/usable in Open WebUI like any other document.

The original file bytes are **never persisted** anywhere — not here, not in Open WebUI — only the cleaned text that
resulted from your edits/redactions ever gets stored, and only in Open WebUI once you hit submit.

## Requirements

- A running Open WebUI instance (any recent version with the Knowledge Bases feature).
- One dedicated Open WebUI **service-account user** with:
  - role = `admin` (needed to read `/api/v1/retrieval/config` for the chunk-related settings)
  - API keys enabled (`Settings → Account → API Keys`, and the instance-wide `ENABLE_API_KEY` setting)
- Python 3.11+, Node.js 20+.

## Backend setup

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# .env (or export directly)
cat > .env <<'EOF'
PROXY_OWUI_BASE_URL=http://localhost:8080
PROXY_OWUI_API_KEY=<service-account api key>
EOF

.venv/bin/uvicorn app.main:app --port 8123 --reload
```

Run the test suite:

```bash
.venv/bin/pytest -q
```

## Frontend setup

```bash
cd frontend
npm install
npm run dev  # serves on http://localhost:5173, proxying to the backend at http://localhost:8123
```

Point it at a non-default backend URL with `VITE_PROXY_API_BASE_URL` (see `frontend/src/lib/api.js`).

Run the pure-logic unit tests (redaction offset math):

```bash
npx vitest run
```

### Building for production behind a reverse proxy at a sub-path

If this proxy is served under a path prefix (e.g. Caddy/nginx exposing it at `https://host/proxy/` rather than at
the domain root), the production build needs **both** of these set to that same prefix, or the built JS silently
falls back to calling `http://localhost:8123` directly — which only ever works if you happen to open the page on
the very machine running the backend, and fails ("Failed to fetch") for literally everyone else:

```powershell
# PowerShell
$env:VITE_PROXY_API_BASE_URL = "/proxy"
npm run build -- --base=/proxy/
```

```bash
# bash
VITE_PROXY_API_BASE_URL=/proxy npm run build -- --base=/proxy/
```

- `--base=/proxy/` (a Vite build flag) makes `index.html` reference its own JS/CSS under `/proxy/assets/...` instead
  of `/assets/...`, so they resolve correctly once the reverse proxy strips the `/proxy` prefix before serving them.
- `VITE_PROXY_API_BASE_URL=/proxy` makes every `fetch()` call in the app target `/proxy/api/...` (same-origin,
  relative) instead of the `http://localhost:8123` dev default — matching whatever path your reverse proxy forwards
  to the backend (e.g. a Caddy `handle /proxy/api/* { uri strip_prefix /proxy; reverse_proxy 127.0.0.1:8123 }`
  block).

Both values must match the actual prefix your reverse proxy strips — if it's serving at `/kb/` instead, use `/kb`
for both.

## Status

- **Milestone 1 — parse, edit, submit**: done.
- **Milestone 2 — redaction**: done. This is the security-critical piece; see
  `backend/app/redaction.py` (server-side cut, used identically for finalize) and
  `frontend/src/lib/annotate.js` (client-side highlighting + offset-rebasing on edits).
- **Milestone 3 — live chunk-boundary preview**: done; see `backend/app/chunking/preview.py` (an approximation —
  it deliberately skips replicating Open WebUI's optional Markdown-header pre-split; see that file's docstring).
- **Knowledge list + detail UI**: mirrors Open WebUI's own Knowledge pages (`frontend/src/lib/Knowledge.svelte`,
  `KnowledgeDetail.svelte`), built with Tailwind CSS using the same gray-scale tokens as `open-webui/src/tailwind.css`
  so `dark:` variants match. Supports editing/updating already-committed files and adding new ones from within a
  knowledge base's own page.

## Known limitations (v1)

- Legacy `.doc`, `.rtf`, `.odt` are not supported — convert to `.docx`/`.pdf`/`.txt` first.
- No multi-user auth on in-progress sessions — anyone with a session id can view/edit it. This is meant to run
  behind whatever perimeter auth (VPN/SSO proxy) you already have, not as an internet-facing service.
- In-progress sessions (including not-yet-redacted text) live in a local SQLite table with a 24h TTL and are
  deleted immediately on successful submit — see `backend/app/models.py` for the exact retention rationale.
