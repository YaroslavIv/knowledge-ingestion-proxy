"""Pull real, readable lecture content out of a published module deliverable
so it's actually queryable in the output knowledge base — not just a
manifest pointing at a download.

Accepts either a SCORM-style zip (finds index.html inside) or a plain .html
upload directly — a future generation stage can just emit HTML with no
SCORM wrapping at all and this still works unchanged.
"""
from __future__ import annotations

import zipfile
from io import BytesIO

from bs4 import BeautifulSoup

from app.parsing.cleanup import clean_markdown_artifacts

_NON_CONTENT_TAGS = ("script", "style", "svg", "noscript")


def extract_html_from_upload(filename: str, content_type: str, data: bytes) -> str | None:
    """Return the raw HTML string found in an upload, or None if there isn't
    one (a non-HTML, non-zip file, or a zip with no .html member inside).
    """
    name = (filename or "").lower()
    ctype = (content_type or "").lower()

    if name.endswith((".html", ".htm")) or ctype in ("text/html", "application/xhtml+xml"):
        return data.decode("utf-8", errors="replace")

    if name.endswith(".zip") or ctype in ("application/zip", "application/x-zip-compressed"):
        try:
            with zipfile.ZipFile(BytesIO(data)) as zf:
                html_names = [n for n in zf.namelist() if n.lower().endswith((".html", ".htm"))]
                if not html_names:
                    return None
                preferred = next((n for n in html_names if n.lower().endswith("index.html")), html_names[0])
                return zf.read(preferred).decode("utf-8", errors="replace")
        except zipfile.BadZipFile:
            return None

    return None


def extract_text_from_html(html: str) -> str:
    """Strip an interactive course page down to its real lecture text —
    headings, paragraphs, learning objectives, quiz questions — dropping
    CSS/JS/SVG chrome that has nothing to do with the actual content.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(_NON_CONTENT_TAGS):
        tag.decompose()
    root = soup.find("main") or soup.body or soup
    text = root.get_text(separator="\n", strip=True)
    return clean_markdown_artifacts(text)
