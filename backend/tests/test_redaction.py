from app.redaction import Redaction, apply_redactions, map_cut_offset_to_original


def test_no_redactions_returns_text_unchanged():
    assert apply_redactions("hello world", []) == "hello world"


def test_single_redaction_cuts_span_with_no_trace():
    text = "keep SECRET keep"
    result = apply_redactions(text, [Redaction(start=5, end=11)])
    assert result == "keep  keep"
    assert "SECRET" not in result


def test_redaction_at_start_of_string():
    text = "SECRETrest"
    result = apply_redactions(text, [Redaction(start=0, end=6)])
    assert result == "rest"


def test_redaction_at_end_of_string():
    text = "restSECRET"
    result = apply_redactions(text, [Redaction(start=4, end=10)])
    assert result == "rest"


def test_entire_string_redacted():
    text = "ALLSECRET"
    result = apply_redactions(text, [Redaction(start=0, end=len(text))])
    assert result == ""


def test_overlapping_redactions_are_merged():
    text = "aSECRETbSECRETc"
    # two overlapping/adjacent-ish ranges covering "SECRETbSECRET"
    result = apply_redactions(
        text,
        [Redaction(start=1, end=9), Redaction(start=8, end=14)],
    )
    assert result == "ac"


def test_adjacent_redactions_are_merged():
    text = "abXYcd"
    result = apply_redactions(text, [Redaction(start=2, end=3), Redaction(start=3, end=4)])
    assert result == "abcd"


def test_multiple_non_overlapping_redactions_out_of_order():
    text = "0123456789"
    result = apply_redactions(
        text,
        [Redaction(start=7, end=9), Redaction(start=1, end=3)],
    )
    assert result == "0" + "3456" + "9"


def test_map_cut_offset_to_original_no_redactions_is_identity():
    assert map_cut_offset_to_original(5, []) == 5


def test_map_cut_offset_to_original_before_redaction_unchanged():
    # original: "keep SECRET keep", redaction [5,11) removes "SECRET"
    # cut text:  "keep  keep" (len 10)
    redactions = [Redaction(start=5, end=11)]
    assert map_cut_offset_to_original(0, redactions) == 0
    assert map_cut_offset_to_original(4, redactions) == 4


def test_map_cut_offset_to_original_after_redaction_shifts_forward():
    text = "keep SECRET keep"
    redactions = [Redaction(start=5, end=11)]
    cut = apply_redactions(text, redactions)
    assert cut == "keep  keep"
    # position of the final "keep" in cut text
    cut_pos = cut.index("keep", 4)
    original_pos = map_cut_offset_to_original(cut_pos, redactions)
    assert text[original_pos : original_pos + 4] == "keep"


def test_map_cut_offset_to_original_with_multiple_redactions():
    text = "0123456789"
    redactions = [Redaction(start=1, end=3), Redaction(start=7, end=9)]
    cut = apply_redactions(text, redactions)
    assert cut == "0" + "3456" + "9"
    # cut index of '9' should map back to original index 9
    cut_pos = cut.index("9")
    assert map_cut_offset_to_original(cut_pos, redactions) == 9
