import { describe, expect, it } from "vitest";
import { buildPath, parseRoute } from "./router.js";

describe("parseRoute", () => {
  it("parses a bare section path", () => {
    expect(parseRoute("/knowledge")).toEqual({ section: "knowledge", id: null });
    expect(parseRoute("/courses")).toEqual({ section: "courses", id: null });
    expect(parseRoute("/coe")).toEqual({ section: "coe", id: null });
  });

  it("parses a section path with an id", () => {
    expect(parseRoute("/knowledge/abc-123")).toEqual({ section: "knowledge", id: "abc-123" });
    expect(parseRoute("/courses/proj-1")).toEqual({ section: "courses", id: "proj-1" });
  });

  it("ignores a trailing slash", () => {
    expect(parseRoute("/knowledge/")).toEqual({ section: "knowledge", id: null });
  });

  it("falls back to the knowledge list for an unknown or bare path", () => {
    expect(parseRoute("/")).toEqual({ section: "knowledge", id: null });
    expect(parseRoute("/nope")).toEqual({ section: "knowledge", id: null });
    expect(parseRoute("")).toEqual({ section: "knowledge", id: null });
  });

  it("decodes a percent-encoded id", () => {
    expect(parseRoute("/knowledge/abc%20def")).toEqual({ section: "knowledge", id: "abc def" });
  });
});

describe("buildPath", () => {
  it("builds a bare section path with no id", () => {
    expect(buildPath("knowledge", null)).toBe("/knowledge");
    expect(buildPath("courses", null)).toBe("/courses");
  });

  it("builds a section path with an id", () => {
    expect(buildPath("knowledge", "abc-123")).toBe("/knowledge/abc-123");
  });

  it("percent-encodes the id", () => {
    expect(buildPath("knowledge", "abc def")).toBe("/knowledge/abc%20def");
  });

  it("falls back to knowledge for an unknown section", () => {
    expect(buildPath("bogus", null)).toBe("/knowledge");
  });
});
