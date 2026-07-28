import pymupdf4llm


def parse_pdf(data: bytes) -> tuple[str, list[str]]:
    """Extract markdown text from a PDF.

    pymupdf4llm gives header/table-aware markdown out of the box (unlike the
    plain pypdf loader Open WebUI itself falls back to), which makes the
    downstream chunk-preview (MarkdownHeaderTextSplitter first pass) far more
    representative of real document structure.
    """
    warnings: list[str] = []
    try:
        return _to_markdown(data), warnings
    except Exception as e:  # noqa: BLE001 - broad on purpose, we fall back below
        warnings.append(f"pymupdf4llm failed ({e}); fell back to plain page-text extraction")
        return _fallback_plain_text(data), warnings


def _to_markdown(data: bytes) -> str:
    import fitz  # PyMuPDF

    doc = fitz.open(stream=data, filetype="pdf")
    try:
        return pymupdf4llm.to_markdown(doc)
    finally:
        doc.close()


def _fallback_plain_text(data: bytes) -> str:
    import fitz  # PyMuPDF

    doc = fitz.open(stream=data, filetype="pdf")
    try:
        return "\n\n".join(page.get_text() for page in doc)
    finally:
        doc.close()
