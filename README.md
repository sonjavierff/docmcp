# docmcp

MCP server to generate documentation and manuals and to fill document templates.

Supported formats: Markdown (`.md`), plain text (`.txt`), Word (`.docx`) and
OpenDocument Text (`.odt`).

## Tools

| Tool | Description |
| --- | --- |
| `create_document` | Create a document from Markdown content. The output format is chosen by the file extension. |
| `fill_template` | Fill a template (Jinja2 `{{ var }}`, `{% for %}`, `{% if %}`) and write the result, keeping the template format. |
| `inspect_template` | List the variables, loops, conditions and tags used by a template. |
| `list_templates` | List the templates registered in the templates directory. |
| `save_template` | Register a template so it can be referenced by name. |
| `extract_text` | Extract the text of an existing document. |

## Templates

Templates use Jinja2 syntax. For `.docx` templates the docxtpl row/paragraph tags
(`{% tr for x in y %}`, `{% tr endfor %}`, `{% p if x %}`) are also supported. For
`.odt` templates, tags may span multiple spans and loops/conditions may wrap
paragraphs, list items or table rows.

Registered templates live in `~/.config/opencode/doc-templates` (override with the
`DOCMCP_TEMPLATES_DIR` environment variable) and are described by an `index.json`
sidecar. Absolute paths can also be used directly.

## Usage

Run the server (stdio transport):

```sh
uv run docmcp        # or: python -m docmcp
```

Register it in `~/.config/opencode/opencode.jsonc`:

```jsonc
"docmcp": {
  "type": "local",
  "command": ["/home/javi/docmcp/.venv/bin/python", "-m", "docmcp"],
  "enabled": true
}
```

## Development

```sh
uv sync
uv run pytest
uv run ruff check src tests
uv run ruff format src tests
```
