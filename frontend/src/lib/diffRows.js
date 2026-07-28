import { diffLines } from "diff";

// jsdiff tokenizes by splitting on "\n", so a shared line without a
// trailing newline in one text but with one in the other ("a" vs "a\nb")
// tokenizes as two different strings ("a" vs "a\n") and never matches as
// context — it shows up as a spurious remove+add of the whole text
// instead. Forcing both sides to end in "\n" keeps line tokens aligned.
function withTrailingNewline(text) {
  return text && !text.endsWith("\n") ? text + "\n" : text;
}

// Turns two full texts into a flat list of {type, text} rows — one per
// line — ready to render as a unified diff: "add"/"remove" lines get a
// +/- prefix and tinted background, "context" lines render plainly.
export function buildDiffRows(oldText, newText) {
  const parts = diffLines(withTrailingNewline(oldText ?? ""), withTrailingNewline(newText ?? ""));
  const rows = [];
  for (const part of parts) {
    const type = part.added ? "add" : part.removed ? "remove" : "context";
    const lines = part.value.split("\n");
    // A trailing-newline-terminated value splits into one extra empty
    // string at the end — drop it so we don't render a phantom blank row.
    if (lines.length > 0 && lines[lines.length - 1] === "") lines.pop();
    for (const text of lines) {
      rows.push({ type, text });
    }
  }
  return rows;
}
