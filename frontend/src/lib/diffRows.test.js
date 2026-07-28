import { describe, expect, it } from "vitest";
import { buildDiffRows } from "./diffRows.js";

describe("buildDiffRows", () => {
  it("marks every line as context when nothing changed", () => {
    const rows = buildDiffRows("a\nb\nc", "a\nb\nc");
    expect(rows).toEqual([
      { type: "context", text: "a" },
      { type: "context", text: "b" },
      { type: "context", text: "c" },
    ]);
  });

  it("marks a changed line as a remove followed by an add", () => {
    const rows = buildDiffRows("a\nb\nc", "a\nx\nc");
    expect(rows).toEqual([
      { type: "context", text: "a" },
      { type: "remove", text: "b" },
      { type: "add", text: "x" },
      { type: "context", text: "c" },
    ]);
  });

  it("handles pure additions", () => {
    const rows = buildDiffRows("a", "a\nb\nc");
    expect(rows).toEqual([
      { type: "context", text: "a" },
      { type: "add", text: "b" },
      { type: "add", text: "c" },
    ]);
  });

  it("handles pure removals", () => {
    const rows = buildDiffRows("a\nb\nc", "a");
    expect(rows).toEqual([
      { type: "context", text: "a" },
      { type: "remove", text: "b" },
      { type: "remove", text: "c" },
    ]);
  });

  it("does not emit a phantom trailing blank row for newline-terminated text", () => {
    const rows = buildDiffRows("a\nb\n", "a\nb\n");
    expect(rows).toEqual([
      { type: "context", text: "a" },
      { type: "context", text: "b" },
    ]);
  });
});
