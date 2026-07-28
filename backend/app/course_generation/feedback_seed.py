"""Parse a free-form reviewer feedback document (like the prototype's
feed_back.txt) into discrete, queryable CourseFeedbackNote rows.

The source format observed in practice: an untitled "general" preamble of
paragraph-separated notes, followed by "===Module N===" (spacing around the
`=` markers is inconsistent) sections, each containing one or more
paragraph-separated notes about that module. A trailing section can cover a
cross-cutting concern (e.g. "=== PRACTICAL CASES ... ===") rather than a
numbered module — treated the same way, just labelled by its own heading.

Category is inferred by keyword heuristics rather than an LLM call — this
runs once per import, the source text is short, and deterministic output is
easier to test and to trust than a model guess.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_SECTION_RE = re.compile(r"^={2,}\s*(.+?)\s*={2,}\s*$", re.MULTILINE)

_CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    # Checked in this order because vocabulary overlaps across categories
    # (e.g. "подзаголовков" contains "заголовк", the ui keyword for "make it
    # a heading" — but "некорректная ПОСЛЕДОВАТЕЛЬНОСТЬ подзаголовков" is a
    # sequencing/structure issue). Most specific / least ambiguous first.
    ("factual_error", ("неверная информация", "ошибочн")),
    ("structure", ("последовательност", "убрать данный модуль", "перегенерировать", "локальн", "некорректн", "неверн")),
    ("content_repetition", ("повторяется", "с нуля", "заново")),
    ("packaging", ("scorm", "mbz", "moodle", "кнопк", "пакет")),
    ("ui", ("горизонтальн", "вертикальн", "выделить крупнее", "заметнее", "div", "заголовк")),
]


@dataclass
class ParsedFeedbackNote:
    note_text: str
    category: str
    module_label: str | None  # e.g. "Module 1" | None for general notes


def _classify(text: str) -> str:
    lowered = text.lower()
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(k in lowered for k in keywords):
            return category
    return "structure"


def _split_notes(body: str) -> list[str]:
    paragraphs = re.split(r"\n\s*\n", body.strip())
    return [p.strip() for p in paragraphs if p.strip()]


def parse_feedback_file(text: str) -> list[ParsedFeedbackNote]:
    matches = list(_SECTION_RE.finditer(text))

    notes: list[ParsedFeedbackNote] = []

    preamble_end = matches[0].start() if matches else len(text)
    preamble = text[:preamble_end]
    # Drop a leading "Общее:" / "General:" label line if present — it's a
    # heading, not a note of its own.
    preamble = re.sub(r"^\s*(Общее|General)\s*:\s*\n", "", preamble, flags=re.IGNORECASE)
    for note_text in _split_notes(preamble):
        notes.append(ParsedFeedbackNote(note_text=note_text, category=_classify(note_text), module_label=None))

    for i, m in enumerate(matches):
        label = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end]
        for note_text in _split_notes(body):
            notes.append(ParsedFeedbackNote(note_text=note_text, category=_classify(note_text), module_label=label))

    return notes
