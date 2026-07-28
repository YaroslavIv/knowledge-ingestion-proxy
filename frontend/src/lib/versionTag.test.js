import { describe, expect, it } from "vitest";
import { suggestNextVersionTag } from "./versionTag.js";

describe("suggestNextVersionTag", () => {
  it("bumps a trailing N.N", () => {
    expect(suggestNextVersionTag("uvss 2.0")).toBe("uvss 2.1");
    expect(suggestNextVersionTag("v1.9")).toBe("v1.10");
  });

  it("falls back to appending v2 without a numeric pattern", () => {
    expect(suggestNextVersionTag("release")).toBe("release v2");
  });
});
