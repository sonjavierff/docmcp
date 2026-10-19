"""Parse Markdown into a small, format-agnostic block model.

The block model is consumed by every engine (text, docx, odt) so that a single
Markdown source can be rendered into any supported output format.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from markdown_it import MarkdownIt


@dataclass
class Run:
    """An inline piece of text with formatting flags."""

    text: str
    bold: bool = False
    italic: bool = False
    code: bool = False
    link: str | None = None


@dataclass
class ListItem:
    """A list item with its nesting depth (0 = top level)."""

    runs: list[Run]
    depth: int = 0


@dataclass
class Block:
    """A block level element."""

    type: str  # heading | paragraph | bullet_list | ordered_list | code | quote | table | hr
    level: int = 0
    runs: list[Run] = field(default_factory=list)
    items: list[ListItem] = field(default_factory=list)
    text: str = ""
    lang: str = ""
    header: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)


def _md() -> MarkdownIt:
    return MarkdownIt("commonmark").enable(["table", "strikethrough"])


def runs_to_text(runs: list[Run]) -> str:
    return "".join(r.text for r in runs)


def _inline_runs(token) -> list[Run]:
    runs: list[Run] = []
    bold = 0
    italic = 0
    link: str | None = None
    for child in token.children or []:
        t = child.type
        if t == "text":
            runs.append(Run(child.content, bold > 0, italic > 0, link=link))
        elif t == "code_inline":
            runs.append(Run(child.content, bold > 0, italic > 0, code=True, link=link))
        elif t == "strong_open":
            bold += 1
        elif t == "strong_close":
            bold = max(0, bold - 1)
        elif t == "em_open":
            italic += 1
        elif t == "em_close":
            italic = max(0, italic - 1)
        elif t == "link_open":
            link = child.attrGet("href") or ""
        elif t == "link_close":
            link = None
        elif t == "softbreak":
            runs.append(Run(" ", bold > 0, italic > 0, link=link))
        elif t == "hardbreak":
            runs.append(Run("\n", bold > 0, italic > 0, link=link))
        elif t == "html_inline":
            pass
        elif t == "image":
            alt = child.content or ""
            runs.append(Run(alt, bold > 0, italic > 0, link=link))
    return runs


def _parse_list(tokens, i: int, depth: int = 0):
    """Parse a list starting at ``tokens[i]`` (bullet_list_open/ordered_list_open)."""
    items: list[ListItem] = []
    i += 1
    while i < len(tokens) and tokens[i].type not in (
        "bullet_list_close",
        "ordered_list_close",
    ):
        tok = tokens[i]
        if tok.type == "list_item_open":
            j = i + 1
            item_runs: list[Run] = []
            while j < len(tokens) and tokens[j].type != "list_item_close":
                if tokens[j].type == "inline":
                    if item_runs:
                        item_runs.append(Run(" "))
                    item_runs.extend(_inline_runs(tokens[j]))
                elif tokens[j].type in ("bullet_list_open", "ordered_list_open"):
                    sub, j = _parse_list(tokens, j, depth + 1)
                    items.extend(sub)
                    continue
                j += 1
            if item_runs:
                items.append(ListItem(runs=item_runs, depth=depth))
            i = j + 1
        else:
            i += 1
    return items, i + 1


def _parse_table(tokens, i: int):
    i += 1  # skip table_open
    header: list[str] = []
    rows: list[list[str]] = []
    current: list[str] | None = None
    in_head = False
    while i < len(tokens) and tokens[i].type != "table_close":
        t = tokens[i].type
        if t == "thead_open":
            in_head = True
        elif t == "thead_close":
            in_head = False
        elif t == "tablestyle":
            pass
        elif t == "tr_open":
            current = []
        elif t == "tr_close":
            if in_head:
                header = current or []
            else:
                rows.append(current or [])
            current = None
        elif t == "inline" and current is not None:
            current.append(runs_to_text(_inline_runs(tokens[i])))
        i += 1
    return header, rows, i + 1


def parse_markdown(text: str) -> list[Block]:
    """Parse Markdown ``text`` into a list of :class:`Block`."""
    tokens = _md().parse(text or "")
    blocks: list[Block] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        t = tok.type
        if t == "heading_open":
            inline = tokens[i + 1]
            blocks.append(
                Block(type="heading", level=int(tok.tag[1]), runs=_inline_runs(inline))
            )
            i += 3
        elif t == "paragraph_open":
            inline = tokens[i + 1]
            blocks.append(Block(type="paragraph", runs=_inline_runs(inline)))
            i += 3
        elif t in ("bullet_list_open", "ordered_list_open"):
            ordered = t.startswith("ordered")
            items, i = _parse_list(tokens, i)
            blocks.append(
                Block(type="ordered_list" if ordered else "bullet_list", items=items)
            )
        elif t == "fence":
            blocks.append(
                Block(
                    type="code",
                    text=tok.content.rstrip("\n"),
                    lang=(tok.info or "").strip(),
                )
            )
            i += 1
        elif t == "code_block":
            blocks.append(Block(type="code", text=tok.content.rstrip("\n")))
            i += 1
        elif t == "blockquote_open":
            runs: list[Run] = []
            j = i + 1
            depth = 1
            while j < len(tokens):
                if tokens[j].type == "blockquote_open":
                    depth += 1
                elif tokens[j].type == "blockquote_close":
                    depth -= 1
                    if depth == 0:
                        break
                elif tokens[j].type == "inline":
                    if runs:
                        runs.append(Run(" "))
                    runs.extend(_inline_runs(tokens[j]))
                j += 1
            blocks.append(Block(type="quote", runs=runs))
            i = j + 1
        elif t == "table_open":
            header, rows, i = _parse_table(tokens, i)
            blocks.append(Block(type="table", header=header, rows=rows))
        elif t == "hr":
            blocks.append(Block(type="hr"))
            i += 1
        else:
            i += 1
    return blocks


def blocks_to_markdown(blocks: list[Block]) -> str:
    """Render the block model back to Markdown (canonical form)."""
    out: list[str] = []
    for b in blocks:
        if b.type == "heading":
            out.append("#" * max(1, min(b.level, 6)) + " " + _runs_md(b.runs))
        elif b.type == "paragraph":
            out.append(_runs_md(b.runs))
        elif b.type in ("bullet_list", "ordered_list"):
            for n, item in enumerate(b.items, start=1):
                prefix = f"{n}. " if b.type == "ordered_list" else "- "
                out.append("  " * item.depth + prefix + _runs_md(item.runs))
        elif b.type == "code":
            fence = "```"
            out.append(f"{fence}{b.lang}\n{b.text}\n{fence}")
        elif b.type == "quote":
            out.append("> " + _runs_md(b.runs))
        elif b.type == "table":
            if b.header:
                out.append("| " + " | ".join(b.header) + " |")
                out.append("| " + " | ".join("---" for _ in b.header) + " |")
            for row in b.rows:
                out.append("| " + " | ".join(row) + " |")
        elif b.type == "hr":
            out.append("---")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _runs_md(runs: list[Run]) -> str:
    parts: list[str] = []
    for r in runs:
        text = r.text
        if r.code and text.strip():
            text = f"`{text}`"
        elif r.bold and text.strip():
            text = f"**{text}**"
        elif r.italic and text.strip():
            text = f"*{text}*"
        if r.link:
            text = f"[{text}]({r.link})"
        parts.append(text)
    return "".join(parts)
