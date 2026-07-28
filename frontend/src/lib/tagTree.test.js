import { describe, expect, it } from "vitest";
import { buildTagTree, matchesTagPath } from "./tagTree.js";

describe("buildTagTree", () => {
  it("builds a flat list of top-level nodes when tags have no nesting", () => {
    const tree = buildTagTree([{ tags: ["coe"] }, { tags: ["course"] }]);
    expect(tree).toEqual([
      { name: "coe", path: "coe", children: [] },
      { name: "course", path: "course", children: [] },
    ]);
  });

  it("nests a child tag under its parent", () => {
    const tree = buildTagTree([{ tags: ["course"] }, { tags: ["course/uvss"] }]);
    expect(tree).toEqual([
      { name: "course", path: "course", children: [{ name: "uvss", path: "course/uvss", children: [] }] },
    ]);
  });

  it("de-duplicates the same tag appearing on multiple items", () => {
    const tree = buildTagTree([{ tags: ["course/uvss"] }, { tags: ["course/uvss"] }]);
    expect(tree).toEqual([
      { name: "course", path: "course", children: [{ name: "uvss", path: "course/uvss", children: [] }] },
    ]);
  });

  it("handles items with no tags at all", () => {
    expect(buildTagTree([{ tags: [] }, {}])).toEqual([]);
  });
});

describe("matchesTagPath", () => {
  it("matches an item tagged with the exact path", () => {
    expect(matchesTagPath({ tags: ["course"] }, "course")).toBe(true);
  });

  it("matches an item tagged with something nested under the path", () => {
    expect(matchesTagPath({ tags: ["course/uvss"] }, "course")).toBe(true);
  });

  it("does not match a sibling tag", () => {
    expect(matchesTagPath({ tags: ["coe"] }, "course")).toBe(false);
  });

  it("narrows correctly at a deeper path", () => {
    expect(matchesTagPath({ tags: ["course"] }, "course/uvss")).toBe(false);
    expect(matchesTagPath({ tags: ["course/uvss"] }, "course/uvss")).toBe(true);
  });

  it("passes everything through when no path is selected", () => {
    expect(matchesTagPath({ tags: [] }, null)).toBe(true);
  });
});
