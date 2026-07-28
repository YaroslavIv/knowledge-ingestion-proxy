"""Local, append-only version history for generated module deliverables
(e.g. SCORM packages).

Open WebUI has no reliable way to hold an opaque binary artifact as a
knowledge-base "file": its upload pipeline always tries to extract/embed
text content for retrieval, and forcing that on a zip either produces
garbage chunks or — confirmed empirically against a real instance — fails
silently to link the file to the knowledge base at all. So the real bytes
never go through Open WebUI: they're cached here, on disk, forever (every
version, not just the current one). What the project's output knowledge
base actually holds is a short metadata header plus the *real lecture text*
extracted from the deliverable (see html_extract.py) — plain text updates
to it are what the existing, already-proven TrackedFile/TrackedCollection
version machinery (bump_file_version, "Changed in vX.Y" badges) tracks, and
it's genuinely searchable/askable, not just a pointer to a download.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from app.config import settings


def _outputs_dir() -> Path:
    path = Path(settings.course_outputs_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_output_bytes(data: bytes) -> str:
    """Write one version's raw bytes to disk and return the stored path."""
    stored_path = _outputs_dir() / str(uuid.uuid4())
    stored_path.write_bytes(data)
    return str(stored_path)


def load_stored_text(stored_path: str) -> str:
    """Read a previously saved version's bytes back as text — used to feed a
    version's HTML back into an LLM revise prompt, or to diff two versions.
    """
    return Path(stored_path).read_text(encoding="utf-8", errors="replace")


def build_kb_content(
    module_title: str,
    version_tag: str,
    filename: str,
    content_type: str,
    size: int,
    published_at: str,
    notes: str = "",
    lecture_text: str | None = None,
) -> str:
    lines = [
        f"# {module_title} — Output {version_tag}",
        "",
        f"- Source file: {filename}",
        f"- Content-Type: {content_type}",
        f"- Size: {size} bytes",
        f"- Published: {published_at}",
    ]
    if notes.strip():
        lines += ["", "## What changed", notes.strip()]

    if lecture_text and lecture_text.strip():
        lines += ["", "---", "", lecture_text.strip()]
    else:
        lines += [
            "",
            "No readable text could be extracted from this upload (not an HTML/SCORM "
            "package) — the original file is still available for download from the "
            "Knowledge Ingestion Proxy's course generator.",
        ]
    return "\n".join(lines) + "\n"
