import zipfile
from io import BytesIO

from app.course_generation.html_extract import extract_html_from_upload, extract_text_from_html

SAMPLE_HTML = """<!DOCTYPE html>
<html><head><title>t</title>
<style>body{color:red}</style>
<script>console.log('hi')</script>
</head>
<body class="course-redesign">
<main class="main">
<h2 class="module-title">Module 01 — Intro</h2>
<p>UVSS is a vehicle inspection system.</p>
<ul><li>Explain what it is</li><li>Explain why it matters</li></ul>
</main>
</body></html>"""


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def test_extract_html_from_plain_html_upload():
    html = extract_html_from_upload("module.html", "text/html", SAMPLE_HTML.encode("utf-8"))
    assert html is not None
    assert "Module 01" in html


def test_extract_html_from_zip_prefers_index_html():
    data = _zip_bytes({"imsmanifest.xml": b"<manifest/>", "index.html": SAMPLE_HTML.encode("utf-8")})
    html = extract_html_from_upload("module.zip", "application/zip", data)
    assert html is not None
    assert "Module 01" in html


def test_extract_html_from_zip_falls_back_to_any_html_file():
    data = _zip_bytes({"content.html": SAMPLE_HTML.encode("utf-8")})
    html = extract_html_from_upload("module.zip", "application/zip", data)
    assert html is not None


def test_extract_html_returns_none_for_zip_without_html():
    data = _zip_bytes({"data.bin": b"\x00\x01\x02"})
    assert extract_html_from_upload("module.zip", "application/zip", data) is None


def test_extract_html_returns_none_for_bad_zip():
    assert extract_html_from_upload("module.zip", "application/zip", b"not a real zip") is None


def test_extract_html_returns_none_for_unrelated_file_type():
    assert extract_html_from_upload("readme.txt", "text/plain", b"hello") is None


def test_extract_text_from_html_strips_style_and_script_keeps_content():
    text = extract_text_from_html(SAMPLE_HTML)
    assert "color:red" not in text
    assert "console.log" not in text
    assert "Module 01 — Intro" in text
    assert "UVSS is a vehicle inspection system." in text
    assert "Explain what it is" in text
    assert "Explain why it matters" in text
