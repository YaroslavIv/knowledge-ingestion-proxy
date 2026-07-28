import re

# Footnote-reference markers left over from PDF->markdown conversion, e.g.
# "the device<sup>9</sup> supports" — noise, not meaningful content, so both
# the tag and its digit content are dropped.
_SUP_TAG_RE = re.compile(r"<sup[^>]*>.*?</sup>", re.IGNORECASE | re.DOTALL)
_BOLD_FOOTNOTE_RE = re.compile(r"\*\*\d+\*\*")

# <br> is a literal line-break marker leaking through as raw HTML; the closest
# semantic equivalent in the plain/markdown text this proxy works with is an
# actual newline.
_BR_TAG_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)

# <u>/</u> (underline) markers, including stray unpaired closing tags left by
# the converter when the matching opener got lost — pure formatting noise
# either way, so the tags are dropped but their text content is kept.
_U_TAG_RE = re.compile(r"</?u[^>]*>", re.IGNORECASE)

# Short single-line structural markers some PDF->markdown converters emit
# around text they extracted from inside an image, e.g.
# "<!-- Start of picture text -->" / "<!-- End of picture text -->". These
# are delimiters, not content — capped at one line so a hypothetical large,
# genuinely content-bearing HTML comment is left alone rather than risking
# eating real text.
_HTML_COMMENT_MARKER_RE = re.compile(r"<!--[^\n]{0,200}-->")

# Some PDF->markdown converters (this proxy's PDF parser included) render
# nearly all emphasized/labelled text as bold, regardless of whether it's
# actually a heading, a spec value ("**50mm**"), a range ("**1-5 fps**"), a
# callout ("**NOTE:**"), or a numbered sub-heading ("**5. Camera Frame
# Rate**") — none of that is meaningful as literal "**...**" markup once the
# document is going to be embedded, so the markup is stripped and the text
# kept. Figure/table/etc. captions are the one deliberate exception: they're
# kept bold so the frontend's caption flagger (annotate.js FIGURE_CAPTION_RE)
# can still find and highlight them for review.
_CAPTION_RE = re.compile(
    r"^(?:figure|fig\.?|table|image|diagram|chart|photo)\s*\d+\s*:?\s*$",
    re.IGNORECASE,
)
_BOLD_SPAN_RE = re.compile(r"\*\*([^*\n]+?)\*\*")

_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_SPACE_BEFORE_PUNCT_RE = re.compile(r" +([.,;:!?])")

# Leftover blank-line runs from stripped tags/comments/bold markers above
# (removing a whole line's content but not its surrounding newlines is what
# produces these) — collapse any run of 3+ newlines down to a single blank
# line (2 newlines), and drop now-empty trailing whitespace on each line.
_TRAILING_LINE_WHITESPACE_RE = re.compile(r"[ \t]+\n")
_EXCESS_NEWLINES_RE = re.compile(r"\n{3,}")


def _unbold_unless_caption(match: re.Match) -> str:
    content = match.group(1)
    if _CAPTION_RE.match(content.strip()):
        return match.group(0)
    return content


def clean_markdown_artifacts(text: str) -> str:
    """Strip conversion artifacts that pymupdf4llm (and similar PDF->markdown
    converters) commonly leave behind: HTML <sup>/<br>/<u> tags, short
    structural HTML comments, bold-only footnote-reference numbers, bold
    markup around everything else that isn't a figure/table/etc. caption, and
    runs of 3+ blank lines left behind by all of the above. Safe to run on
    any parsed text — it's a no-op when these patterns aren't present.
    """
    text = _SUP_TAG_RE.sub("", text)
    text = _BOLD_FOOTNOTE_RE.sub("", text)
    text = _BR_TAG_RE.sub("\n", text)
    text = _U_TAG_RE.sub("", text)
    text = _HTML_COMMENT_MARKER_RE.sub("", text)
    text = _BOLD_SPAN_RE.sub(_unbold_unless_caption, text)
    text = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", text)
    text = _MULTI_SPACE_RE.sub(" ", text)
    text = _TRAILING_LINE_WHITESPACE_RE.sub("\n", text)
    text = _EXCESS_NEWLINES_RE.sub("\n\n", text)
    return text
