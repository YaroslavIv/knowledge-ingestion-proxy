from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

_HEADING_LEVELS = {f"Heading {i}": i for i in range(1, 7)}
_HEADING_LEVELS["Title"] = 1


def parse_docx(data: bytes) -> tuple[str, list[str]]:
    """Extract markdown from a .docx, preserving heading levels and tables.

    python-docx + explicit style mapping gives real structure (unlike
    docx2txt, which Open WebUI's own default loader uses and which only
    produces flat text) — this is what makes the chunk-preview's
    header-based splitting meaningful instead of one undifferentiated blob.
    """
    import io

    warnings: list[str] = []
    doc = Document(io.BytesIO(data))

    blocks: list[str] = []
    for element in _iter_block_items(doc):
        if isinstance(element, Paragraph):
            text = element.text.strip()
            if not text:
                continue
            level = _HEADING_LEVELS.get(element.style.name if element.style else "")
            if level:
                blocks.append(f"{'#' * level} {text}")
            else:
                blocks.append(text)
        elif isinstance(element, Table):
            blocks.append(_table_to_markdown(element))

    if not blocks:
        warnings.append("No text content found in document")

    return "\n\n".join(blocks), warnings


def _iter_block_items(doc: Document):
    """Yield paragraphs and tables in the order they appear in the document body."""
    from docx.oxml.ns import qn

    body = doc.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, doc)
        elif child.tag == qn("w:tbl"):
            yield Table(child, doc)


def _table_to_markdown(table: Table) -> str:
    rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
    if not rows:
        return ""
    header, *body = rows
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    lines += ["| " + " | ".join(row) + " |" for row in body]
    return "\n".join(lines)
