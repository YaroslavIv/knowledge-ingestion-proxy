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
  If those edits don't apply (a missing/ambiguous anchor), the model gets
  one retry with its own error fed back before this falls back to a full
  from-scratch rewrite, so a bad edit never just fails the whole call.
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


def _file_blocks(files: list[dict]) -> str:
    """files: [{"filename", "content"}, ...] — the full text of each file,
    no truncation. Content generation (unlike module-splitting, which only
    needs to decide structure) must see everything, or it can't accurately
    write about material past whatever an excerpt would have cut off."""
    return "\n\n".join(f"### {f['filename']}\n{f['content']}" for f in files) or "(no files)"


def _competitor_section(competitor_files: list[dict] | None) -> str:
    if not competitor_files:
        return ""
    return f"""
COMPETITIVE INTELLIGENCE (filename + content) — use this to sharpen positioning/differentiation
where relevant, without inventing claims the material doesn't actually make:
{_file_blocks(competitor_files)}
"""


def _visual_guidance_section(visual_guidance: str | None) -> str:
    if not visual_guidance:
        return ""
    return f"""
VISUAL/STYLE GUIDE FOR THIS COURSE — describes the intended look of the final HTML (colors, fonts,
layout, components) for every module in this course. It may be literal HTML/CSS to reuse directly,
or written style rules — either way, treat it as the primary source of truth for how the page
should look:
{visual_guidance}
"""


def _other_modules_sections(
    other_modules: list[dict] | None, other_modules_content: list[dict] | None
) -> tuple[str, str]:
    other_modules_block = ""
    if other_modules:
        other_modules_block = "\n".join(
            f"- {m['title']}: {', '.join(m.get('learning_objectives') or []) or '(no objectives listed)'}"
            for m in other_modules
        )
    other_modules_section = (
        f"""
OTHER MODULES ALREADY IN THIS COURSE (for context and consistency — don't repeat their content,
reference them by name if relevant):
{other_modules_block or "(none yet)"}
"""
        if other_modules
        else ""
    )

    other_modules_content_section = ""
    if other_modules_content:
        content_block = "\n\n".join(f"### {m['title']}\n{m['text']}" for m in other_modules_content)
        other_modules_content_section = f"""
ACTUAL CONTENT OF THE OTHER MODULES — use this to ground anything that must reflect what was really
taught in this course (e.g. a final test/quiz module must only ask about material that actually
appears here, not invented facts):
{content_block}
"""
    return other_modules_section, other_modules_content_section


def _style_reference_section(style_reference_html: str | None) -> str:
    if not style_reference_html:
        return ""
    return f"""
VISUAL STYLE TEMPLATE TO MATCH — this is the full HTML of another module already in this same
course. Reuse its CSS/design system exactly: same colors, fonts, spacing, layout structure, and
interactive components (accordions, quizzes, tabs, etc. — whatever pattern it uses). Do NOT reuse
or reference its actual text/content, only its look, structure and conventions, so every module in
the course feels like one consistent product:
{style_reference_html}
"""


def build_generate_prompt(
    title: str,
    learning_objectives: list[str],
    current_html: str | None,
    instruction: str,
    product_files: list[dict],
    methodology_text: str,
    feedback_notes: list[str],
    competitor_files: list[dict] | None = None,
    visual_guidance: str | None = None,
    other_modules: list[dict] | None = None,
    other_modules_content: list[dict] | None = None,
    style_reference_html: str | None = None,
) -> str:
    feedback_block = "\n".join(f"- {n}" for n in feedback_notes) if feedback_notes else "(none yet)"
    competitor_section = _competitor_section(competitor_files)
    visual_section = _visual_guidance_section(visual_guidance)
    other_modules_section, other_modules_content_section = _other_modules_sections(
        other_modules, other_modules_content
    )
    style_reference_section = _style_reference_section(style_reference_html)

    if current_html:
        # Always included, for both a from-scratch write and a revise — a
        # revise that only ever saw its own previous HTML (not the actual
        # current collections) could keep citing facts the source material
        # no longer has, with nothing to ever correct that.
        materials_section = f"""
CURRENT PRODUCT MATERIAL (filename + content) — this is the collections' real content right now;
if it conflicts with something already written in the page below (e.g. material was since removed
or corrected), prefer this and update the page accordingly, even if the requested change doesn't
explicitly mention it:
{_file_blocks(product_files)}

METHODOLOGY AND STRUCTURAL RULES:
{methodology_text or "(no methodology notes provided)"}
"""

        return f"""You are revising the existing interactive HTML page for the course module "{title}".
The page is large, so describe your change as one or more precise find/replace edits instead of
returning the whole document.

CURRENT VERSION (full HTML):
{current_html}
{materials_section}{competitor_section}{visual_section}{other_modules_section}{other_modules_content_section}{style_reference_section}
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

    return f"""Write a new self-contained interactive HTML lecture page for the course module "{title}".

LEARNING OBJECTIVES:
{objectives_block}

SOURCE MATERIAL THIS MODULE SHOULD DRAW ON (filename + content):
{_file_blocks(product_files)}

METHODOLOGY AND STRUCTURAL RULES (follow these):
{methodology_text or "(no methodology notes provided)"}
{competitor_section}{visual_section}{other_modules_section}{other_modules_content_section}{style_reference_section}
KNOWN PAST MISTAKES TO AVOID (from previous course reviews):
{feedback_block}

ADDITIONAL GUIDANCE FOR THIS MODULE:
{instruction or "(none — use your judgement)"}

Return the complete HTML document for this module's lecture page — nothing else.
"""


async def _request_edits(client: OwuiClient, model: str, prompt: str) -> list[dict]:
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
    return edits


async def _request_full_document(client: OwuiClient, model: str, prompt: str) -> str:
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


async def generate_module_output(
    client: OwuiClient,
    model: str,
    title: str,
    learning_objectives: list[str],
    current_html: str | None,
    instruction: str,
    product_files: list[dict],
    methodology_text: str,
    feedback_notes: list[str],
    competitor_files: list[dict] | None = None,
    visual_guidance: str | None = None,
    other_modules: list[dict] | None = None,
    other_modules_content: list[dict] | None = None,
    style_reference_html: str | None = None,
) -> str:
    prompt = build_generate_prompt(
        title,
        learning_objectives,
        current_html,
        instruction,
        product_files,
        methodology_text,
        feedback_notes,
        competitor_files=competitor_files,
        visual_guidance=visual_guidance,
        other_modules=other_modules,
        other_modules_content=other_modules_content,
        style_reference_html=style_reference_html,
    )

    if not current_html:
        return await _request_full_document(client, model, prompt)

    try:
        return apply_edits(current_html, await _request_edits(client, model, prompt))
    except ValueError as first_error:
        # The model's find/replace edits didn't apply cleanly (a missing or
        # ambiguous anchor) — give it one chance to see its own mistake and
        # correct it before giving up on an in-place revise altogether.
        retry_prompt = f"""{prompt}

Your previous response's edits failed to apply: {first_error}
Re-read the CURRENT VERSION above carefully and make sure each "find" string is copied verbatim
(character-for-character) from it and appears in it exactly once. Return corrected JSON edits.
"""
        try:
            return apply_edits(current_html, await _request_edits(client, model, retry_prompt))
        except ValueError:
            # Still couldn't produce edits that apply — fall back to a full
            # rewrite rather than failing the whole call and losing the
            # user's generation request outright; the current version stays
            # in history either way (see courses.py's versioning).
            fresh_prompt = build_generate_prompt(
                title,
                learning_objectives,
                None,
                instruction,
                product_files,
                methodology_text,
                feedback_notes,
                competitor_files=competitor_files,
                visual_guidance=visual_guidance,
                other_modules=other_modules,
                other_modules_content=other_modules_content,
                style_reference_html=style_reference_html,
            )
            return await _request_full_document(client, model, fresh_prompt)
