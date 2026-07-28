import { describe, expect, it } from "vitest";
import { defaultModelId } from "./defaultModel.js";

describe("defaultModelId", () => {
  it("picks the preferred model when it's in the list", () => {
    const models = [{ id: "gpt-4o-mini" }, { id: "gpt-5.4" }, { id: "o3" }];
    expect(defaultModelId(models)).toBe("gpt-5.4");
  });

  it("falls back to the first model when the preferred one isn't available", () => {
    const models = [{ id: "gpt-4o-mini" }, { id: "o3" }];
    expect(defaultModelId(models)).toBe("gpt-4o-mini");
  });

  it("returns an empty string for an empty list", () => {
    expect(defaultModelId([])).toBe("");
    expect(defaultModelId(null)).toBe("");
  });

  it("supports overriding the preferred model", () => {
    const models = [{ id: "a" }, { id: "b" }];
    expect(defaultModelId(models, "b")).toBe("b");
  });
});
