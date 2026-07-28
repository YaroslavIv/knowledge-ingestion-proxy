from pydantic import BaseModel


class Redaction(BaseModel):
    start: int
    end: int


def apply_redactions(text: str, redactions: list[Redaction]) -> str:
    """Permanently cut the given [start, end) ranges out of text.

    No placeholder is inserted — the redacted content leaves no trace, per
    requirement. Overlapping/adjacent ranges are merged before cutting so the
    result is well-defined regardless of how the ranges were produced.
    """
    if not redactions:
        return text

    merged = _merge_ranges(sorted(((r.start, r.end) for r in redactions), key=lambda r: r[0]))

    out = []
    cursor = 0
    for start, end in merged:
        start = max(0, min(start, len(text)))
        end = max(0, min(end, len(text)))
        if start > cursor:
            out.append(text[cursor:start])
        cursor = max(cursor, end)
    out.append(text[cursor:])
    return "".join(out)


def map_cut_offset_to_original(offset: int, redactions: list[Redaction]) -> int:
    """Inverse of `apply_redactions`: map an offset in the post-cut text back to
    the corresponding offset in the original (pre-cut) text.

    Needed because chunk boundaries are computed on the cut text (what actually
    gets embedded), but the editor displays the original text with redactions
    merely marked, not removed — so chunk bands must be re-expressed in
    original-text coordinates to line up with what's on screen.
    """
    if not redactions:
        return offset

    merged = _merge_ranges(sorted(((r.start, r.end) for r in redactions), key=lambda r: r[0]))

    cut_cursor = 0
    original_cursor = 0
    for start, end in merged:
        kept_len = start - original_cursor
        if offset < cut_cursor + kept_len:
            return original_cursor + (offset - cut_cursor)
        cut_cursor += kept_len
        original_cursor = end

    return original_cursor + (offset - cut_cursor)


def _merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not ranges:
        return []
    merged = [ranges[0]]
    for start, end in ranges[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged
