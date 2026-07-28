import { describe, expect, it } from "vitest";
import {
  buildAnnotatedHtml,
  detectFlaggedSpans,
  detectRepeatedLineSpans,
  rebaseRedactions,
} from "./annotate.js";

describe("buildAnnotatedHtml", () => {
  it("wraps a redacted span in a mark tag", () => {
    const html = buildAnnotatedHtml("keep SECRET keep", [{ start: 5, end: 11 }]);
    expect(html).toBe('keep <mark class="redacted">SECRET</mark> keep\n');
  });

  it("escapes html-significant characters", () => {
    const html = buildAnnotatedHtml("<b>&</b>", []);
    expect(html).toBe("&lt;b&gt;&amp;&lt;/b&gt;\n");
  });

  it("merges overlapping redactions before rendering", () => {
    const html = buildAnnotatedHtml("abcdef", [
      { start: 1, end: 4 },
      { start: 3, end: 5 },
    ]);
    expect(html).toBe('a<mark class="redacted">bcde</mark>f\n');
  });

  it("renders chunk boundaries as alternating spans, marking the start of every chunk after the first", () => {
    const html = buildAnnotatedHtml(
      "abcdef",
      [],
      [
        { start: 0, end: 3 },
        { start: 3, end: 6 },
      ],
    );
    expect(html).toBe('<span class="chunk-even">abc</span><span class="chunk-odd chunk-start">def</span>\n');
  });

  it("does not mark the very first chunk as a chunk-start (no boundary before it)", () => {
    const html = buildAnnotatedHtml("abc", [], [{ start: 0, end: 3 }]);
    expect(html).toBe('<span class="chunk-even">abc</span>\n');
  });

  it("marks the start of every chunk boundary across 3+ chunks", () => {
    const html = buildAnnotatedHtml(
      "abcdefghi",
      [],
      [
        { start: 0, end: 3 },
        { start: 3, end: 6 },
        { start: 6, end: 9 },
      ],
    );
    expect(html).toBe(
      '<span class="chunk-even">abc</span>' +
        '<span class="chunk-odd chunk-start">def</span>' +
        '<span class="chunk-even chunk-start">ghi</span>\n',
    );
  });

  it("combines a redaction with chunk bands using a single mark for the overlap", () => {
    const html = buildAnnotatedHtml(
      "abcdef",
      [{ start: 1, end: 3 }],
      [
        { start: 0, end: 3 },
        { start: 3, end: 6 },
      ],
    );
    expect(html).toBe(
      '<span class="chunk-even">a</span><mark class="chunk-even redacted">bc</mark><span class="chunk-odd chunk-start">def</span>\n',
    );
  });

  it("renders a flagged span as a mark with a distinct class", () => {
    const html = buildAnnotatedHtml("keep this text", [], [], [{ start: 5, end: 9 }]);
    expect(html).toBe('keep <mark class="flagged">this</mark> text\n');
  });

  it("redaction takes precedence over flagged for the same span", () => {
    const html = buildAnnotatedHtml("keep this text", [{ start: 5, end: 9 }], [], [{ start: 5, end: 9 }]);
    expect(html).toBe('keep <mark class="redacted">this</mark> text\n');
  });
});

describe("detectFlaggedSpans", () => {
  it("finds a figure caption and flags the whole line", () => {
    const text = "Intro text.\n\n**Figure 4** : A good example of a camera installation (described below).\n\nMore text.";
    const spans = detectFlaggedSpans(text);
    expect(spans).toHaveLength(1);
    const { start, end } = spans[0];
    expect(text.slice(start, end)).toBe(
      "**Figure 4** : A good example of a camera installation (described below).",
    );
  });

  it("finds multiple caption styles (Table, Fig.)", () => {
    const text = "**Table 1** : Specs.\nSome text.\n**Fig. 2** : A diagram.";
    const spans = detectFlaggedSpans(text);
    expect(spans).toHaveLength(2);
  });

  it("finds a caption whose colon lands inside the closing ** (e.g. '**Figure 10:**')", () => {
    const text = "Intro.\n\n**Figure 10:** Not enough zoom\n\nMore text.";
    const spans = detectFlaggedSpans(text);
    expect(spans).toHaveLength(1);
    const { start, end } = spans[0];
    expect(text.slice(start, end)).toBe("**Figure 10:** Not enough zoom");
  });

  it("returns no spans when there are no captions", () => {
    expect(detectFlaggedSpans("Just a normal paragraph with **bold text** in it.")).toEqual([]);
  });

  it("finds a plain, unformatted caption with no bold markup at all", () => {
    const text = "Intro.\n\nFigure 13. Parameters in the Filters and output tab\n\nMore text.";
    const spans = detectFlaggedSpans(text);
    expect(spans).toHaveLength(1);
    const { start, end } = spans[0];
    expect(text.slice(start, end)).toBe("Figure 13. Parameters in the Filters and output tab");
  });

  it("finds a plain caption with a decimal figure number", () => {
    const text = "Figure 3.2: Sensor placement diagram";
    const spans = detectFlaggedSpans(text);
    expect(spans).toHaveLength(1);
    expect(text.slice(spans[0].start, spans[0].end)).toBe(text);
  });

  it("does not flag an inline body reference to a figure mid-sentence", () => {
    const text = "For more information, see Figure 13 for details on the filter tab.";
    expect(detectFlaggedSpans(text)).toEqual([]);
  });

  it("does not flag a sentence that merely starts with the word describing a figure in prose", () => {
    const text = "Figures like this one are common throughout the manual.";
    // "Figures" (plural) isn't "Figure" + digits, so this must not match
    expect(detectFlaggedSpans(text)).toEqual([]);
  });
});

describe("detectRepeatedLineSpans", () => {
  it("flags a running header repeated 3+ times", () => {
    const text = [
      "INTELLIGENT SECURITY SYSTEMS",
      "The camera supports night vision out of the box.",
      "INTELLIGENT SECURITY SYSTEMS",
      "Mounting brackets are sold separately from the unit.",
      "INTELLIGENT SECURITY SYSTEMS",
      "Cabling should be run through weatherproof conduit.",
    ].join("\n");
    const spans = detectRepeatedLineSpans(text);
    expect(spans).toHaveLength(3);
    for (const { start, end } of spans) {
      expect(text.slice(start, end)).toBe("INTELLIGENT SECURITY SYSTEMS");
    }
  });

  it("matches a dynamic header whose page number varies", () => {
    const text = [
      "INTELLIGENT SECURITY SYSTEMS - Page 1",
      "content",
      "INTELLIGENT SECURITY SYSTEMS - Page 2",
      "content",
      "INTELLIGENT SECURITY SYSTEMS - Page 3",
    ].join("\n");
    const spans = detectRepeatedLineSpans(text);
    expect(spans).toHaveLength(3);
    expect(text.slice(spans[0].start, spans[0].end)).toBe("INTELLIGENT SECURITY SYSTEMS - Page 1");
    expect(text.slice(spans[2].start, spans[2].end)).toBe("INTELLIGENT SECURITY SYSTEMS - Page 3");
  });

  it("ignores lines that are too short (page numbers, rules)", () => {
    const text = ["1", "---", "1", "---", "1", "---"].join("\n");
    expect(detectRepeatedLineSpans(text)).toEqual([]);
  });

  it("ignores lines that only repeat once or twice", () => {
    const text = ["A repeated banner line here", "content", "A repeated banner line here", "content"].join("\n");
    expect(detectRepeatedLineSpans(text)).toEqual([]);
  });

  it("returns no spans for normal prose with no repeats", () => {
    const text = "This is just a normal paragraph.\nAnd another different one.\nAnd a third one, still different.";
    expect(detectRepeatedLineSpans(text)).toEqual([]);
  });
});

describe("buildAnnotatedHtml with repeated-line highlighting", () => {
  it("renders a repeated span as a yellow-class mark", () => {
    const html = buildAnnotatedHtml("keep this text", [], [], [], [{ start: 5, end: 9 }]);
    expect(html).toBe('keep <mark class="repeated">this</mark> text\n');
  });

  it("flagged (figure caption) takes precedence over repeated for the same span", () => {
    const html = buildAnnotatedHtml("keep this text", [], [], [{ start: 5, end: 9 }], [{ start: 5, end: 9 }]);
    expect(html).toBe('keep <mark class="flagged">this</mark> text\n');
  });
});

describe("rebaseRedactions", () => {
  it("leaves redactions before the edit untouched", () => {
    const result = rebaseRedactions("aaSECRETbbb", "aaSECRETbbbXXX", [{ start: 2, end: 8 }]);
    expect(result).toEqual([{ start: 2, end: 8 }]);
  });

  it("shifts redactions after an insertion earlier in the text", () => {
    const result = rebaseRedactions("aaSECRETbbb", "aaXXXSECRETbbb", [{ start: 2, end: 8 }]);
    expect(result).toEqual([{ start: 5, end: 11 }]);
  });

  it("shifts redactions after a deletion earlier in the text", () => {
    const result = rebaseRedactions("aaaaSECRETbbb", "aSECRETbbb", [{ start: 4, end: 10 }]);
    expect(result).toEqual([{ start: 1, end: 7 }]);
  });

  it("clips a redaction whose tail is consumed by an edit", () => {
    // redaction covers "CRET" region originally; edit deletes into the middle of it
    const result = rebaseRedactions("aaSECRETbbb", "aaSEbbb", [{ start: 4, end: 8 }]);
    // original text: a a S E C R E T b b b (indices 0..10)
    // redaction [4,8) = "CRET"; edit deletes "CRET" (indices 4..8) -> nothing survives after
    expect(result).toEqual([]);
  });

  it("drops a redaction fully consumed by the edit", () => {
    const result = rebaseRedactions("aaSECRETbbb", "aabbb", [{ start: 2, end: 8 }]);
    expect(result).toEqual([]);
  });

  it("keeps the surviving prefix of a redaction clipped by an edit", () => {
    // redaction [2,8) = "SECRET"; edit replaces indices [5,8) "RET" with "XX"
    const result = rebaseRedactions("aaSECRETbbb", "aaSECXXbbb", [{ start: 2, end: 8 }]);
    expect(result).toEqual([{ start: 2, end: 5 }]);
  });
});
