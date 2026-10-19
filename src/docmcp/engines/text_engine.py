"""Plain text / Markdown engine.

* ``blocks_to_text`` renders the shared block model to readable plain text.
* ``render_text_template`` fills Jinja2 placeholders in ``.md`` / ``.txt`` files.
"""

from __future__ import annotations

import textwrap

from jinja2 import (
    Environment,
    StrictUndefined,
    TemplateSyntaxError,
    Undefined,
    UndefinedError,
)

from ..markdown_parser import Block, blocks_to_markdown, runs_to_text


def _wrap(text: str, width: int = 100) -> list[str]:
    return textwrap.wrap(text, width=width) or [""]


def blocks_to_text(blocks: list[Block]) -> str:
    lines: list[str] = []
    for b in blocks:
        if b.type == "heading":
            title = runs_to_text(b.runs)
            lines.append(title)
            if b.level <= 2:
                lines.append(("=" if b.level == 1 else "-") * len(title))
            lines.append("")
        elif b.type == "paragraph":
            lines.extend(_wrap(runs_to_text(b.runs)))
            lines.append("")
        elif b.type in ("bullet_list", "ordered_list"):
            for n, item in enumerate(b.items, start=1):
                prefix = f"{n}. " if b.type == "ordered_list" else "- "
                text = runs_to_text(item.runs)
                indent = "  " * item.depth
                wrapped = _wrap(text.strip(), width=98 - len(indent))
                lines.append(indent + prefix + wrapped[0])
                lines.extend(" " * (len(indent) + len(prefix)) + w for w in wrapped[1:])
            lines.append("")
        elif b.type == "code":
            lines.extend("    " + ln for ln in b.text.split("\n"))
            lines.append("")
        elif b.type == "quote":
            for ln in _wrap(runs_to_text(b.runs), width=98):
                lines.append("> " + ln)
            lines.append("")
        elif b.type == "table":
            lines.extend(_table_to_text(b))
            lines.append("")
        elif b.type == "hr":
            lines.append("-" * 40)
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _table_to_text(b: Block) -> list[str]:
    table = ([b.header] if b.header else []) + b.rows
    if not table:
        return []
    cols = max(len(r) for r in table)
    widths = [0] * cols
    for row in table:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    out: list[str] = []
    for idx, row in enumerate(table):
        cells = [
            row[i].ljust(widths[i]) if i < len(row) else " " * widths[i]
            for i in range(cols)
        ]
        out.append("| " + " | ".join(cells) + " |")
        if idx == 0 and b.header:
            out.append("+-" + "-+-".join("-" * w for w in widths) + "-+")
    return out


def md_from_blocks(blocks: list[Block]) -> str:
    return blocks_to_markdown(blocks)


def make_env(strict: bool = True) -> Environment:
    return Environment(
        undefined=StrictUndefined if strict else Undefined,
        autoescape=False,
        keep_trailing_newline=True,
        trim_blocks=False,
        lstrip_blocks=False,
    )


def render_text_template(template_text: str, context: dict, strict: bool = True) -> str:
    env = make_env(strict)
    try:
        return env.from_string(template_text).render(context)
    except TemplateSyntaxError as exc:
        raise ValueError(
            f"Jinja2 syntax error in template: {exc.message} (line {exc.lineno})"
        ) from exc
    except UndefinedError as exc:
        raise ValueError(f"Template variable error: {exc.message}") from exc
