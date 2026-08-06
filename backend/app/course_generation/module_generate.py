"""Module content generation/revision stage: the LLM call that actually
writes (or edits) a module's interactive HTML lecture page — the piece
still missing after module-splitting, since `propose_modules` only decides
*structure*, never lecture content.

Two shapes, chosen by whether a current output version already exists:
- generate-from-scratch (`current_html is None`): write a new self-contained
  interactive HTML page from the module spec plus product/instructions
  material and the caller's instruction. The model returns the complete
  document directly.
- revise (`current_html` given): a real imported module page can be well
  over 100KB — far past what a single chat completion can *return* even
  though it fits easily as *input* (output token budgets are much smaller
  than context windows). Asking the model to echo the whole document back
  reliably gets silently truncated mid-page on large modules — confirmed
  live against a real 161KB module page. So revisions are expressed as a
  small set of exact find/replace edits instead, applied programmatically
  here — output size scales with the size of the change, not the document.
"""
from __future__ import annotations

import json
import re

from app.owui_client import OwuiClient

SYSTEM_PROMPT_GENERATE = (
    "You write a single self-contained interactive HTML lecture page for one "
    "module of a sales-onboarding course. Always respond with the complete "
    "raw HTML document only — no markdown code fences, no commentary before "
    "or after it. Keep the markup readably formatted across multiple lines, "
    "never minified onto one line, since every version is diffed against "
    "the previous one."
)

SYSTEM_PROMPT_REVISE = (
    "You revise an existing interactive HTML lecture page for one module of "
    "a sales-onboarding course. The page can be very large, so instead of "
    "rewriting it, you describe your change as a small set of precise "
    "find/replace edits and respond with JSON only — never the full "
    "document."
)

_FENCE_RE = re.compile(r"^```(?:html)?\s*|\s*```$", re.IGNORECASE)


def _strip_fences(text: str) -> str:
    return _FENCE_RE.sub("", text.strip()).strip()


def apply_edits(current_html: str, edits: list[dict]) -> str:
    """Apply a sequence of exact-string find/replace edits, in order.

    Each `find` must appear in the (progressively edited) document exactly
    once — ambiguous or missing anchors fail loudly rather than silently
    editing the wrong spot or corrupting the document.
    """
    html = current_html
    for i, edit in enumerate(edits):
        find = edit.get("find") or ""
        replace = edit.get("replace", "")
        if not find:
            raise ValueError(f"Edit {i} is missing a non-empty 'find' string")
        count = html.count(find)
        if count == 0:
            raise ValueError(f"Edit {i}: could not find the text to replace: {find[:120]!r}")
        if count > 1:
            raise ValueError(f"Edit {i}: text to replace is not unique ({count} occurrences): {find[:120]!r}")
        html = html.replace(find, replace, 1)
    return html


def build_generate_prompt(
    title: str,
    learning_objectives: list[str],
    current_html: str | None,
    instruction: str,
    product_excerpts: list[dict],
    methodology_text: str,
    feedback_notes: list[str],
    other_modules: list[dict] | None = None,
    other_modules_content: list[dict] | None = None,
    style_reference_html: str | None = None,
) -> str:
    feedback_block = "\n".join(f"- {n}" for n in feedback_notes) if feedback_notes else "(none yet)"

    if current_html:
        # Always included, for both a from-scratch write and a revise — a
        # revise that only ever saw its own previous HTML (not the actual
        # current collections) could keep citing facts the source material
        # no longer has, with nothing to ever correct that.
        files_block = (
            "\n\n".join(f"### {f['filename']}\n{f['excerpt']}" for f in product_excerpts) or "(no files)"
        )
        materials_section = f"""
CURRENT PRODUCT MATERIAL (filename + excerpt) — this is the collections' real content right now;
if it conflicts with something already written in the page below (e.g. material was since removed
or corrected), prefer this and update the page accordingly, even if the requested change doesn't
explicitly mention it:
{files_block}

METHODOLOGY AND STRUCTURAL RULES:
{methodology_text or "(no methodology notes provided)"}
"""

        return f"""You are revising the existing interactive HTML page for the course module "{title}".
The page is large, so describe your change as one or more precise find/replace edits instead of
returning the whole document.

CURRENT VERSION (full HTML):
{current_html}
{materials_section}
KNOWN PAST MISTAKES TO AVOID (from previous course reviews):
{feedback_block}

REQUESTED CHANGE:
{instruction}

Return JSON only, in this exact shape:
{{"edits": [{{"find": "...", "replace": "..."}}]}}

Rules:
- Each "find" string must be copied VERBATIM (character-for-character, including whitespace) from
  the CURRENT VERSION above, and must appear in it EXACTLY ONCE, so it can be located reliably.
- To insert new content (e.g. a new section) without deleting anything, make "find" a short anchor
  string right before where the new content belongs, and "replace" that same anchor string followed
  by the new content.
- Keep each edit as small and scoped as the requested change actually requires — do not rewrite
  surrounding content that wasn't asked for.
"""

    objectives_block = "\n".join(f"- {o}" for o in learning_objectives) or "(none listed)"
    files_block = "\n\n".join(f"### {f['filename']}\n{f['excerpt']}" for f in product_excerpts) or "(no files)"

    other_modules_block = ""
    if other_modules:
        other_modules_block = "\n".join(
            f"- {m['title']}: {', '.join(m.get('learning_objectives') or []) or '(no objectives listed)'}"
            for m in other_modules
        )
    other_modules_section = f"""
OTHER MODULES ALREADY IN THIS COURSE (for context and consistency — don't repeat their content,
reference them by name if relevant):
{other_modules_block or "(none yet)"}
""" if other_modules else ""

    other_modules_content_section = ""
    if other_modules_content:
        content_block = "\n\n".join(f"### {m['title']}\n{m['text']}" for m in other_modules_content)
        other_modules_content_section = f"""
ACTUAL CONTENT OF THE OTHER MODULES — use this to ground anything that must reflect what was really
taught in this course (e.g. a final test/quiz module must only ask about material that actually
appears here, not invented facts):
{content_block}
"""

    style_reference_section = ""
    if style_reference_html:
        style_reference_section = f"""
VISUAL STYLE TEMPLATE TO MATCH — this is the full HTML of another module already in this same
course. Reuse its CSS/design system exactly: same colors, fonts, spacing, layout structure, and
interactive components (accordions, quizzes, tabs, etc. — whatever pattern it uses). Do NOT reuse
or reference its actual text/content, only its look, structure and conventions, so every module in
the course feels like one consistent product:
{style_reference_html}
"""

    return f"""Write a new self-contained interactive HTML lecture page for the course module "{title}".

LEARNING OBJECTIVES:
{objectives_block}

SOURCE MATERIAL THIS MODULE SHOULD DRAW ON (filename + excerpt):
{files_block}

METHODOLOGY AND STRUCTURAL RULES (follow these):
{methodology_text or "(no methodology notes provided)"}
{other_modules_section}{other_modules_content_section}{style_reference_section}
KNOWN PAST MISTAKES TO AVOID (from previous course reviews):
{feedback_block}

ADDITIONAL GUIDANCE FOR THIS MODULE:
{instruction or "(none — use your judgement)"}

Return the complete HTML document for this module's lecture page — nothing else.
"""


async def generate_module_output(
    client: OwuiClient,
    model: str,
    title: str,
    learning_objectives: list[str],
    current_html: str | None,
    instruction: str,
    product_excerpts: list[dict],
    methodology_text: str,
    feedback_notes: list[str],
    other_modules: list[dict] | None = None,
    other_modules_content: list[dict] | None = None,
    style_reference_html: str | None = None,
) -> str:
    prompt = build_generate_prompt(
        title,
        learning_objectives,
        current_html,
        instruction,
        product_excerpts,
        methodology_text,
        feedback_notes,
        other_modules=other_modules,
        other_modules_content=other_modules_content,
        style_reference_html=style_reference_html,
    )

    if current_html:
        raw = await client.chat_completion(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_REVISE},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        data = json.loads(raw)
        edits = data.get("edits")
        if not isinstance(edits, list) or not edits:
            raise ValueError("Model response did not contain an 'edits' list")
        return apply_edits(current_html, edits)

    raw = await client.chat_completion(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_GENERATE},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
    )
    html = _strip_fences(raw)
    if not html.startswith("<"):
        raise ValueError("Model response did not look like an HTML document")
    if "</html>" not in html.lower():
        raise ValueError(
            "Model response looks truncated (no closing </html> tag) — the document may be too "
            "long for this model's output limit; try a shorter module or a different model"
        )
    return html
