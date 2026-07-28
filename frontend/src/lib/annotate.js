// Pure, framework-free helpers for the redaction editor. Kept separate from
// any Svelte component so they can be unit-tested in isolation.

/**
 * Merge overlapping/adjacent [start, end) ranges and sort by start.
 */
function mergeRanges(ranges) {
  const sorted = [...ranges].sort((a, b) => a.start - b.start);
  const merged = [];
  for (const r of sorted) {
    const last = merged[merged.length - 1];
    if (last && r.start <= last.end) {
      last.end = Math.max(last.end, r.end);
    } else {
      merged.push({ ...r });
    }
  }
  return merged;
}

function escapeHtml(s) {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/**
 * Build the backdrop HTML for the highlighted-textarea pattern: the same
 * text as the real <textarea>, with redacted spans wrapped in <mark>, and
 * (optionally) chunk boundaries rendered as alternating background bands
 * (a `<span class="chunk-band chunk-even|chunk-odd">` per chunk).
 *
 * Chunks and redactions are independent, possibly-overlapping range sets
 * (chunk_overlap means adjacent chunks can share text), so this walks all
 * boundary points from both sets together and renders one run per resulting
 * segment with whichever combination of classes applies to it — rather than
 * nesting two separate range-wrapping passes, which can't express "half in
 * chunk 2, half in chunk 3, all redacted" cleanly.
 *
 * A trailing newline is appended so the backdrop's height matches a
 * textarea's, which always renders at least one trailing line.
 */
export function buildAnnotatedHtml(text, redactions, chunks = [], flagged = [], repeated = []) {
  const mergedRedactions = mergeRanges(redactions);
  const clampRanges = (ranges) =>
    ranges
      .map((r) => ({ start: Math.max(0, Math.min(r.start, text.length)), end: Math.max(0, Math.min(r.end, text.length)) }))
      .filter((r) => r.end > r.start);
  const validChunks = clampRanges(chunks);
  const validFlagged = clampRanges(flagged);
  const validRepeated = clampRanges(repeated);

  const boundaries = new Set([0, text.length]);
  for (const set of [mergedRedactions, validChunks, validFlagged, validRepeated]) {
    for (const r of set) {
      boundaries.add(r.start);
      boundaries.add(r.end);
    }
  }
  const points = [...boundaries].sort((a, b) => a - b);

  let html = "";
  for (let i = 0; i < points.length - 1; i++) {
    const segStart = points[i];
    const segEnd = points[i + 1];
    if (segStart >= segEnd) continue;

    const isRedacted = mergedRedactions.some((r) => r.start <= segStart && segEnd <= r.end);
    const isFlagged = !isRedacted && validFlagged.some((f) => f.start <= segStart && segEnd <= f.end);
    const isRepeated = !isRedacted && !isFlagged && validRepeated.some((r) => r.start <= segStart && segEnd <= r.end);
    const chunkIndex = validChunks.findIndex((c) => c.start <= segStart && segEnd <= c.end);
    // Marks the first segment of every chunk after the first, so the
    // backdrop can render an explicit boundary marker there (rather than
    // relying on the subtler alternating-background tint alone).
    const isChunkStart = chunkIndex > 0 && validChunks[chunkIndex].start === segStart;

    const classes = [];
    if (chunkIndex !== -1) classes.push(chunkIndex % 2 === 0 ? "chunk-even" : "chunk-odd");
    if (isChunkStart) classes.push("chunk-start");
    if (isRedacted) classes.push("redacted");
    if (isFlagged) classes.push("flagged");
    if (isRepeated) classes.push("repeated");

    const segment = escapeHtml(text.slice(segStart, segEnd));
    if (classes.length === 0) {
      html += segment;
    } else {
      const tag = isRedacted || isFlagged || isRepeated ? "mark" : "span";
      html += `<${tag} class="${classes.join(" ")}">${segment}</${tag}>`;
    }
  }
  return html + "\n";
}

// Figure/table/image captions left behind once a PDF's actual images are
// stripped by parsing — e.g. "**Figure 4**: A good example of...", "**Figure
// 10:** Not enough zoom" (the colon can land either just inside or just
// outside a closing **), or, just as often, plain unformatted text with no
// bold markup at all: "Figure 13. Parameters in the Filters and output tab".
// The source PDF doesn't reliably render captions as bold, so requiring `**`
// missed real captions. Anchored to the start of a line (optional leading
// whitespace/asterisks only) instead, so an inline body reference like "see
// Figure 13 for details" — which is never at the start of its own line —
// isn't mistaken for a leftover caption. These are only *flagged* for the
// user's attention, never auto-redacted — the user decides whether the
// leftover caption text is worth keeping.
const FIGURE_CAPTION_RE =
  /^[ \t]*\**[ \t]*(?:Figure|Fig\.?|Table|Image|Diagram|Chart|Photo)\s*\d+(?:\.\d+)?\s*[.:]?\s*\**\s*[.:]?\s*[^\n]*/gim;

export function detectFlaggedSpans(text) {
  const spans = [];
  for (const match of text.matchAll(FIGURE_CAPTION_RE)) {
    spans.push({ start: match.index, end: match.index + match[0].length });
  }
  return spans;
}

// Running headers/footers are often "dynamic" — the same banner but with a
// varying page number embedded ("INTELLIGENT SECURITY SYSTEMS — Page 3" /
// "... — Page 4") — so repeats are grouped by a normalized key (digit runs
// collapsed to a placeholder) rather than requiring byte-for-byte equality.
function _repeatKey(trimmedLine) {
  return trimmedLine.replace(/\d+/g, "#");
}

/**
 * Detect likely page headers/footers: short lines that recur several times
 * throughout the document (e.g. a running header like "INTELLIGENT SECURITY
 * SYSTEMS" repeated once per page, possibly with a varying page number).
 * This is a frequency heuristic, not a syntax pattern like the figure-
 * caption detector, so it's deliberately conservative — length-bounded
 * (skips both trivial short lines like "1" or "---" and long ones, which are
 * unlikely to be a header/footer) and requires several repeats — and, like
 * figure captions, only *flags* candidates rather than removing them: the
 * user decides whether a given repeat is really header noise or legitimate
 * repeated content.
 */
export function detectRepeatedLineSpans(text, { minOccurrences = 3, minLength = 6, maxLength = 100 } = {}) {
  const lines = text.split("\n");
  const inRange = (trimmed) => trimmed.length >= minLength && trimmed.length <= maxLength;

  const counts = new Map();
  for (const line of lines) {
    const trimmed = line.trim();
    if (!inRange(trimmed)) continue;
    const key = _repeatKey(trimmed);
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }

  const repeatedKeys = new Set([...counts.entries()].filter(([, count]) => count >= minOccurrences).map(([key]) => key));
  if (repeatedKeys.size === 0) return [];

  const spans = [];
  let cursor = 0;
  for (const line of lines) {
    const trimmed = line.trim();
    if (inRange(trimmed) && repeatedKeys.has(_repeatKey(trimmed))) {
      const offsetInLine = line.indexOf(trimmed);
      const start = cursor + offsetInLine;
      spans.push({ start, end: start + trimmed.length });
    }
    cursor += line.length + 1; // +1 for the '\n' consumed by split()
  }
  return spans;
}

/**
 * Rebase redaction offsets after a text edit.
 *
 * Uses a simple "common prefix + common suffix" diff: this is exact for the
 * overwhelming majority of real <textarea> input events (single-point
 * insert/delete/paste), which is all this UI needs to handle — a full
 * Myers-diff is not warranted here.
 *
 * If an edit's replaced range overlaps a redaction span, that span is
 * clipped to whatever portion survives outside the edit, or dropped
 * entirely if fully consumed by the edit.
 */
export function rebaseRedactions(oldText, newText, redactions) {
  const { editStart, oldEnd, newEnd } = diffRange(oldText, newText);
  const deletedLen = oldEnd - editStart;
  const insertedLen = newEnd - editStart;
  const shift = insertedLen - deletedLen;

  const result = [];
  for (const r of redactions) {
    if (r.end <= editStart) {
      // entirely before the edit: unaffected
      result.push({ ...r });
    } else if (r.start >= oldEnd) {
      // entirely after the edit: shift by the length delta
      result.push({ start: r.start + shift, end: r.end + shift });
    } else {
      // overlaps the edited range: clip to the surviving portion(s)
      const before = r.start < editStart ? { start: r.start, end: editStart } : null;
      const after = r.end > oldEnd ? { start: oldEnd + shift, end: r.end + shift } : null;
      if (before) result.push(before);
      if (after) result.push(after);
    }
  }
  return result;
}

function diffRange(a, b) {
  let prefix = 0;
  const maxPrefix = Math.min(a.length, b.length);
  while (prefix < maxPrefix && a[prefix] === b[prefix]) prefix++;

  let suffix = 0;
  const maxSuffix = Math.min(a.length, b.length) - prefix;
  while (suffix < maxSuffix && a[a.length - 1 - suffix] === b[b.length - 1 - suffix]) suffix++;

  return {
    editStart: prefix,
    oldEnd: a.length - suffix,
    newEnd: b.length - suffix,
  };
}
