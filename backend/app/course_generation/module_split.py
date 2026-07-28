"""Module-splitting stage: proposes how product material should be broken
into course modules, WITHOUT writing any lecture content itself.

This is a first-class stage (unlike the prototype, where the module
breakdown was implicit inside whichever monolithic lecture-generation call
happened to run) precisely so a human can review/edit the proposed
breakdown — titles, learning objectives, which source files feed which
module — before anything gets written to a knowledge base as generated
course content.
"""
from __future__ import annotations

import json

from app.owui_client import OwuiClient

SYSTEM_PROMPT = (
    "You design the module breakdown for a full onboarding course aimed at "
    "new salespeople who may be seeing this product for the first time. "
    "You never write lecture content — only propose how the material should "
    "be organized into modules, each with clear learning objectives and the "
    "specific source documents it should draw on. Respond with JSON only."
)

_EXCERPT_CHARS = 1500


def build_file_excerpts(files: list[tuple[str, str]]) -> list[dict]:
    """files: [(filename, full_content), ...] -> [{"filename", "excerpt"}, ...]

    Only an excerpt (not full content) goes into the splitting prompt —
    this stage decides structure, not content, so it doesn't need (and for
    large files like a 400KB product-line doc, can't afford) the full text.
    """
    return [
        {"filename": filename, "excerpt": content[:_EXCERPT_CHARS]}
        for filename, content in files
    ]


def build_prompt(
    product_files: list[dict],
    methodology_text: str,
    feedback_notes: list[str],
    target_audience: str,
    language: str,
) -> str:
    files_block = "\n\n".join(f"### {f['filename']}\n{f['excerpt']}" for f in product_files) or "(no files)"
    feedback_block = "\n".join(f"- {n}" for n in feedback_notes) if feedback_notes else "(none yet)"

    return f"""Propose a module breakdown for a {target_audience} onboarding course, written in {language}.

METHODOLOGY AND STRUCTURAL RULES (follow these):
{methodology_text or "(no methodology notes provided)"}

KNOWN PAST MISTAKES TO AVOID (from previous course reviews — do not repeat these):
{feedback_block}

AVAILABLE PRODUCT MATERIAL (filename + excerpt of each):
{files_block}

Design a logical module sequence covering this material. For each module, decide:
- a clear, descriptive title
- 3-6 learning objectives (what the learner will be able to do after this module)
- which of the listed filenames are its source material (source_refs)

Return JSON only, in this exact shape:
{{"modules": [{{"title": "...", "learning_objectives": ["...", "..."], "source_refs": ["filename1", "filename2"]}}]}}
"""


async def propose_modules(
    client: OwuiClient,
    model: str,
    product_files: list[dict],
    methodology_text: str,
    feedback_notes: list[str],
    target_audience: str = "sales",
    language: str = "en",
) -> list[dict]:
    prompt = build_prompt(product_files, methodology_text, feedback_notes, target_audience, language)
    raw = await client.chat_completion(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    data = json.loads(raw)
    modules = data.get("modules", [])
    if not isinstance(modules, list):
        raise ValueError("Model response did not contain a 'modules' list")
    return modules
