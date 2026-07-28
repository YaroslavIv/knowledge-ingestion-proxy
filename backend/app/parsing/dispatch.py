from dataclasses import dataclass

from fastapi import HTTPException, status

from app.parsing.cleanup import clean_markdown_artifacts
from app.parsing.docx import parse_docx
from app.parsing.pdf import parse_pdf
from app.parsing.plaintext import parse_plaintext

_DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

_UNSUPPORTED_EXTENSIONS = {".doc", ".rtf", ".odt", ".ppt", ".pptx", ".xls", ".xlsx"}


@dataclass
class ParseResult:
    text: str
    warnings: list[str]


def parse_document(filename: str, content_type: str | None, data: bytes) -> ParseResult:
    ext = _extension(filename)

    if ext == ".pdf" or content_type == "application/pdf":
        text, warnings = parse_pdf(data)
    elif ext == ".docx" or content_type == _DOCX_CONTENT_TYPE:
        text, warnings = parse_docx(data)
    elif ext in {".txt", ".md", ".markdown"} or (content_type and content_type.startswith("text/")):
        text, warnings = parse_plaintext(data)
    elif ext in _UNSUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"'{ext}' is not supported yet in v1 (legacy Office formats). "
                "Convert to .docx/.pdf/.txt, or use Open WebUI's own upload directly."
            ),
        )
    else:
        # Unknown extension: try plaintext as a last resort rather than failing outright.
        text, warnings = parse_plaintext(data)
        warnings.append(f"Unrecognized file type '{ext or content_type}'; treated as plain text")

    return ParseResult(text=clean_markdown_artifacts(text), warnings=warnings)


def _extension(filename: str) -> str:
    if "." not in filename:
        return ""
    return "." + filename.rsplit(".", 1)[-1].lower()
