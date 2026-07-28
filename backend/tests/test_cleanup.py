from app.parsing.cleanup import clean_markdown_artifacts


def test_strips_sup_tag_and_content():
    assert clean_markdown_artifacts("the device<sup>9</sup> supports it") == "the device supports it"


def test_strips_br_tag_replacing_with_newline():
    assert clean_markdown_artifacts("line one<br>line two") == "line one\nline two"
    assert clean_markdown_artifacts("line one<br/>line two") == "line one\nline two"
    assert clean_markdown_artifacts("line one<br />line two") == "line one\nline two"


def test_strips_bold_footnote_number():
    assert clean_markdown_artifacts("supported**9** on this model") == "supported on this model"


def test_collapses_resulting_double_spaces():
    assert clean_markdown_artifacts("a<sup>1</sup> b") == "a b"


def test_noop_on_plain_text():
    text = "# Heading\n\nNormal paragraph with no artifacts at all."
    assert clean_markdown_artifacts(text) == text


def test_unbolds_generic_bold_text_keeping_content():
    # This PDF converter renders nearly everything (headings, spec values,
    # callouts) as bold, so bold markup itself is treated as noise unless the
    # span is a figure/table/etc. caption (see test below).
    text = "Normal paragraph with **some bold text** in it."
    assert clean_markdown_artifacts(text) == "Normal paragraph with some bold text in it."


def test_unbolds_bold_spec_values():
    assert clean_markdown_artifacts("Lens: **50mm**") == "Lens: 50mm"
    assert clean_markdown_artifacts("Frame rate: **1-5 fps**") == "Frame rate: 1-5 fps"


def test_unbolds_bold_numbered_subheading():
    assert clean_markdown_artifacts("**5. Camera Frame Rate**") == "5. Camera Frame Rate"


def test_strips_short_html_comment_markers_keeping_surrounding_text():
    text = "<!-- Start of picture text -->\nZoom: 4x\n<!-- End of picture text -->"
    assert clean_markdown_artifacts(text) == "\nZoom: 4x\n"


def test_strips_u_tag_pair():
    assert clean_markdown_artifacts("this is <u>underlined</u> text") == "this is underlined text"


def test_strips_stray_unpaired_closing_u_tag():
    assert clean_markdown_artifacts("underlined</u> text") == "underlined text"


def test_strips_bold_callout_label_keeping_text():
    assert clean_markdown_artifacts("**NOTE:** do not expose to sunlight") == "NOTE: do not expose to sunlight"
    assert clean_markdown_artifacts("**WARNING:** high voltage") == "WARNING: high voltage"


def test_does_not_strip_figure_table_caption_bold():
    # Figure/table captions must stay bold — the frontend flags them for
    # review, it doesn't rely on this backend cleanup to find them.
    text = "**Figure 4**: A good example of a camera installation."
    assert clean_markdown_artifacts(text) == text
    text2 = "**Table 2**: Supported resolutions."
    assert clean_markdown_artifacts(text2) == text2


def test_collapses_runs_of_three_or_more_newlines_to_one_blank_line():
    assert clean_markdown_artifacts("a\n\n\n\n\n\nb") == "a\n\nb"
    assert clean_markdown_artifacts("a\n\n\nb") == "a\n\nb"


def test_keeps_a_single_blank_line_untouched():
    assert clean_markdown_artifacts("a\n\nb") == "a\n\nb"


def test_collapses_excess_newlines_left_by_stripped_html_comment():
    text = "before\n\n<!-- Start of picture text -->\n\n\nafter"
    assert clean_markdown_artifacts(text) == "before\n\nafter"


def test_strips_trailing_whitespace_on_blank_lines():
    assert clean_markdown_artifacts("a\n   \n  \nb") == "a\n\nb"
