"""docmcp - MCP server to create documentation/manuals and fill templates.

Supported formats: Markdown (.md), plain text (.txt), Word (.docx) and
OpenDocument Text (.odt). Templates use Jinja2 syntax ({{ var }}, {% for %},
{% if %}) and are filled keeping the template format.
"""

from __future__ import annotations

import functools
import zipfile

from jinja2 import TemplateError
from lxml.etree import XMLSyntaxError
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import document
from . import inspect as inspect_mod
from . import templates as templates_mod

server = MCPServer(
    name="docmcp",
    version="0.1.0",
    instructions=(
        "Create documentation and manuals in md, txt, docx and odt, and fill provided "
        "templates (Jinja2 placeholders). Use inspect_template to discover a template's "
        "variables before calling fill_template."
    ),
)

_ANTICIPATED = (
    ValueError,
    KeyError,
    OSError,
    zipfile.BadZipFile,
    TemplateError,
    XMLSyntaxError,
)


def _guard(fn):
    """Turn anticipated errors into tool errors so the client sees the message."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ToolError:
            raise
        except _ANTICIPATED as exc:
            raise ToolError(str(exc) or type(exc).__name__) from exc

    return wrapper


def _meta(title, author, subject, comments) -> dict:
    meta = {}
    if title:
        meta["title"] = title
    if author:
        meta["author"] = author
    if subject:
        meta["subject"] = subject
    if comments:
        meta["comments"] = comments
    return meta


@server.tool()
@_guard
def create_document(
    output_path: str,
    content: str,
    title: str | None = None,
    author: str | None = None,
    subject: str | None = None,
    comments: str | None = None,
) -> dict:
    """Create a new document from Markdown content.

    The output format is selected by the file extension (.md, .txt, .docx or .odt).
    Supports headings, paragraphs, bullet/numbered lists, tables, code blocks,
    quotes, bold/italic and links. title/author/subject/comments are stored as
    document metadata for docx and odt.

    Args:
        output_path: Destination file path; the extension selects the format.
        content: Document body written in Markdown.
        title: Document title (metadata for docx/odt).
        author: Author (metadata for docx/odt).
        subject: Subject (metadata for docx/odt).
        comments: Comments/description (metadata for docx/odt).
    """
    return document.create_document(
        output_path, content, _meta(title, author, subject, comments)
    )


@server.tool()
@_guard
def fill_template(
    template: str,
    output_path: str,
    context: dict,
    strict: bool = True,
) -> dict:
    """Fill a provided template with values and write the result.

    Templates use Jinja2 syntax: {{ variable }}, {% for item in list %}...{% endfor %},
    {% if cond %}...{% endif %}. Works with .docx (Word), .odt (OpenDocument), .md and
    .txt templates; the output keeps the template's format. For Word templates, docxtpl
    tags such as {% tr for x in y %} and {% p if x %} are also supported.

    Args:
        template: Absolute path to the template, or a name registered in the templates directory.
        output_path: Destination file path (same format as the template).
        context: Values for the template tags (nested objects and lists are supported).
        strict: If true (default), fail when the context is missing a variable the template uses.
    """
    resolved = templates_mod.resolve_template(template)
    return document.fill_template(
        str(resolved), output_path, context or {}, strict=strict
    )


@server.tool()
@_guard
def inspect_template(template: str) -> dict:
    """Analyse a template and list its variables, loops, conditions and tags.

    Returns the variables a template expects, the loops and conditions it contains, and
    every Jinja2 tag with a short context snippet. Call this before fill_template to know
    which context keys to provide.

    Args:
        template: Absolute path to the template, or a name registered in the templates directory.
    """
    resolved = templates_mod.resolve_template(template)
    return inspect_mod.inspect_template(str(resolved))


@server.tool()
@_guard
def list_templates() -> dict:
    """List the templates available in the templates directory.

    The directory defaults to ~/.config/opencode/doc-templates and can be overridden with
    the DOCMCP_TEMPLATES_DIR environment variable.
    """
    return {
        "templates": templates_mod.list_templates(),
        "directory": str(templates_mod.templates_dir()),
    }


@server.tool()
@_guard
def save_template(source_path: str, name: str, description: str = "") -> dict:
    """Register a template so it can be referenced by name.

    Copies a file (.md, .txt, .docx or .odt) into the templates directory and records a
    description, so it can later be used from fill_template and inspect_template by name.

    Args:
        source_path: Path of the template file to register.
        name: Short name to register it under.
        description: Optional description of the template.
    """
    return templates_mod.save_template(source_path, name, description)


@server.tool()
@_guard
def extract_text(path: str) -> dict:
    """Extract the text content of an existing document (.md, .txt, .docx or .odt).

    Useful to read a template or an already generated manual.

    Args:
        path: Path of the document to read.
    """
    return {"path": path, "text": document.extract_text(path)}


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
