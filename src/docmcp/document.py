"""Format dispatch: create documents, fill templates and extract text."""

from __future__ import annotations

from pathlib import Path

from .context import wrap_context
from .engines import docx_engine, odt_engine, text_engine
from .markdown_parser import parse_markdown

SUPPORTED_FORMATS = (".md", ".txt", ".docx", ".odt")
TEXT_FORMATS = (".md", ".txt")
BINARY_FORMATS = (".docx", ".odt")


def detect_format(path: str | Path) -> str:
    ext = Path(path).suffix.lower()
    if ext not in SUPPORTED_FORMATS:
        raise ValueError(
            f"Unsupported format '{ext or path}'. Supported formats: {', '.join(SUPPORTED_FORMATS)}"
        )
    return ext


def create_document(output_path: str, content: str, meta: dict | None = None) -> dict:
    out = Path(output_path).expanduser()
    fmt = detect_format(out)
    blocks = parse_markdown(content)

    if fmt == ".md":
        data = text_engine.md_from_blocks(blocks).encode("utf-8")
    elif fmt == ".txt":
        data = text_engine.blocks_to_text(blocks).encode("utf-8")
    elif fmt == ".docx":
        data = docx_engine.create_docx(blocks, meta)
    else:  # .odt
        data = odt_engine.create_odt(blocks, meta)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return {
        "output": str(out),
        "format": fmt.lstrip("."),
        "bytes": len(data),
        "blocks": len(blocks),
    }


def fill_template(
    template_path: str, output_path: str, context: dict, strict: bool = True
) -> dict:
    template = Path(template_path)
    out = Path(output_path).expanduser()
    tfmt = detect_format(template)
    ofmt = detect_format(out)
    wrapped = wrap_context(context or {})

    if tfmt in TEXT_FORMATS:
        source = template.read_text(encoding="utf-8")
        rendered = text_engine.render_text_template(source, wrapped, strict=strict)
        if ofmt == ".txt" and tfmt == ".md":
            rendered = text_engine.blocks_to_text(parse_markdown(rendered))
        data = rendered.encode("utf-8")
    elif tfmt == ".docx":
        if ofmt != ".docx":
            raise ValueError("A .docx template can only produce a .docx output")
        data = docx_engine.fill_docx(str(template), wrapped, strict=strict)
    elif tfmt == ".odt":
        if ofmt != ".odt":
            raise ValueError("A .odt template can only produce a .odt output")
        data = odt_engine.fill_odt(str(template), wrapped, strict=strict)
    else:
        raise ValueError(f"Unsupported template format: {tfmt}")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return {
        "template": str(template),
        "output": str(out),
        "format": ofmt.lstrip("."),
        "bytes": len(data),
        "context_keys": sorted(context.keys()),
    }


def extract_text(path: str) -> str:
    source = Path(path).expanduser()
    if not source.is_file():
        raise FileNotFoundError(f"File not found: {source}")
    fmt = detect_format(source)
    if fmt in TEXT_FORMATS:
        return source.read_text(encoding="utf-8")
    if fmt == ".docx":
        return docx_engine.extract_docx_text(str(source))
    return odt_engine.extract_odt_text(str(source))
