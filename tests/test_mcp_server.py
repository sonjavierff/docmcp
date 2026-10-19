from __future__ import annotations

import anyio
import pytest

from docmcp.inspect import inspect_template
from docmcp.server import server


def test_inspect_docx(docx_template):
    report = inspect_template(str(docx_template))
    assert report["format"] == "docx"
    assert "titulo" in report["variables"]
    assert "filas" in report["variables"]
    loops = {entry["iterable"] for entry in report["loops"]}
    assert {"secciones", "categorias", "filas"} <= loops
    assert "version" in report["conditions"]
    assert any(t["token"] == "{{ titulo }}" for t in report["tokens"])


def test_inspect_odt(odt_template):
    report = inspect_template(str(odt_template))
    assert report["format"] == "odt"
    assert "titulo" in report["variables"]
    loops = {entry["iterable"] for entry in report["loops"]}
    assert {"secciones", "categorias", "filas"} <= loops


def test_server_exposes_tools():
    async def main():
        return await server.list_tools()

    tools = anyio.run(main)
    names = {t.name for t in tools}
    assert names == {
        "create_document",
        "fill_template",
        "inspect_template",
        "list_templates",
        "save_template",
        "extract_text",
    }


def test_server_call_tool_create(tmp_path):
    async def main():
        return await server.call_tool(
            "create_document",
            {"output_path": str(tmp_path / "a.md"), "content": "# Hola"},
        )

    result = anyio.run(main)
    assert not result.is_error
    assert "Hola" in (tmp_path / "a.md").read_text(encoding="utf-8")


def test_server_call_tool_error_is_readable(tmp_path):
    from mcp.server.mcpserver.exceptions import ToolError

    async def main():
        await server.call_tool("extract_text", {"path": str(tmp_path / "missing.md")})

    with pytest.raises(ToolError) as excinfo:
        anyio.run(main)
    assert "missing.md" in str(excinfo.value)
