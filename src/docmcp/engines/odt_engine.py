"""ODT (OpenDocument Text) engine.

Creation uses ``odfpy``. Template filling is a small, self-contained renderer:

* Variables ``{{ expr }}`` may be split across several ODF text runs/spans.
* ``{% for x in items %}`` / ``{% endfor %}`` and ``{% if cond %}`` / ``{% endif %}``
  may span several sibling paragraphs, list items or table rows and are expanded.
* Control tags must be balanced and properly nested.

Inline styles of a paragraph are preserved unless that paragraph contains a
``{{ }}`` placeholder that spans it, in which case its text is rewritten.
"""

from __future__ import annotations

import copy
import io
import re
import zipfile

from jinja2 import (
    Environment,
    StrictUndefined,
    TemplateSyntaxError,
    Undefined,
    UndefinedError,
)
from lxml import etree
from odf.dc import Creator, Description, Subject, Title
from odf.opendocument import OpenDocumentText
from odf.style import ParagraphProperties, Style, TextProperties
from odf.table import Table, TableCell, TableColumn, TableRow
from odf.text import (
    A,
    H,
    LineBreak,
    List,
    ListItem,
    ListLevelStyleBullet,
    ListLevelStyleNumber,
    ListStyle,
    P,
    Span,
)

from ..markdown_parser import Block, Run

# --------------------------------------------------------------------------- #
# Namespaces and low level helpers
# --------------------------------------------------------------------------- #

NS_OFFICE = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
NS_TEXT = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
NS_TABLE = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"

_MONO = "Liberation Mono"
MAX_LOOP_ITEMS = 10000

RE_FOR_OPEN = re.compile(r"{%-?\s*for\s+([A-Za-z_]\w*)\s+in\s+(.+?)\s*-?%}", re.DOTALL)
RE_ENDFOR = re.compile(r"{%-?\s*endfor\s*-?%}")
RE_IF_OPEN = re.compile(r"{%-?\s*if\s+(.+?)\s*-?%}", re.DOTALL)
RE_ENDIF = re.compile(r"{%-?\s*endif\s*-?%}")

LEAF_TAGS = {"p", "h"}
CONTAINER_TAGS = {
    "text",
    "body",
    "list",
    "list-item",
    "list-header",
    "table",
    "table-row",
    "table-cell",
    "table-header-rows",
    "table-row-group",
    "table-rows",
    "section",
    "index-body",
    "table-of-content",
}


def _qn(namespace: str, tag: str) -> str:
    return f"{{{namespace}}}{tag}"


def _is_element(el) -> bool:
    return isinstance(el.tag, str)


def _localname(el) -> str | None:
    return etree.QName(el).localname if _is_element(el) else None


def _slots(node, is_root: bool = True):
    """Yield ``(kind, node)`` for every text/tail slot in itertext order."""
    if node.text:
        yield ("text", node, node.text)
    for child in node:
        yield from _slots(child, False)
        if child.tail:
            yield ("tail", child, child.tail)


def _text(el) -> str:
    return "".join(v for _, _, v in _slots(el))


def _balance(text: str) -> tuple[int, int]:
    fors = len(RE_FOR_OPEN.findall(text)) - len(RE_ENDFOR.findall(text))
    ifs = len(RE_IF_OPEN.findall(text)) - len(RE_ENDIF.findall(text))
    return fors, ifs


def _opens_kind(text: str) -> str | None:
    fors, ifs = _balance(text)
    if fors > 0:
        return "for"
    if ifs > 0:
        return "if"
    if "{%" in text:
        raise ValueError(
            "Unexpected {% endfor %} / {% endif %} without a matching opening tag"
        )
    return None


class LoopContext:
    def __init__(self, index0: int, length: int):
        self.index0 = index0
        self.index = index0 + 1
        self.length = length
        self.first = index0 == 0
        self.last = index0 == length - 1
        self.revindex = length - index0
        self.revindex0 = length - index0 - 1


# --------------------------------------------------------------------------- #
# Template rendering
# --------------------------------------------------------------------------- #


def _make_env(strict: bool) -> Environment:
    return Environment(undefined=StrictUndefined if strict else Undefined)


def _render_string(text: str, ctx: dict, env: Environment) -> str:
    try:
        return env.from_string(text).render(ctx)
    except TemplateSyntaxError as exc:
        raise ValueError(
            f"Jinja2 syntax error in ODT template: {exc.message} (line {exc.lineno})"
        ) from exc
    except UndefinedError as exc:
        raise ValueError(f"Template variable error: {exc.message}") from exc


def _eval_expr(expr: str, ctx: dict, env: Environment):
    try:
        fn = env.compile_expression(expr, undefined_to_none=False)
    except TemplateSyntaxError as exc:
        raise ValueError(f"Invalid expression '{expr}': {exc.message}") from exc
    try:
        value = fn(ctx)
    except UndefinedError as exc:
        raise ValueError(f"Template variable error in '{expr}': {exc.message}") from exc
    if isinstance(value, Undefined):
        raise ValueError(  # noqa: TRY004 - an undefined variable is a value error
            f"Undefined variable used in expression '{expr}'"
        )
    return value


def _set_leaf_text(el, value: str) -> None:
    for child in list(el):
        el.remove(child)
    lines = value.split("\n")
    el.text = lines[0]
    for line in lines[1:]:
        br = etree.SubElement(el, _qn(NS_TEXT, "line-break"))
        br.tail = line


def _replace_range(el, start: int, end: int) -> None:
    pos = 0
    for kind, node, val in list(_slots(el)):
        s, e = pos, pos + len(val)
        pos = e
        if e <= start or s >= end:
            continue
        lo = max(start, s) - s
        hi = min(end, e) - s
        setattr(node, kind, val[:lo] + val[hi:])


def _strip_in_element(el, pattern: re.Pattern, last: bool) -> bool:
    matches = list(pattern.finditer(_text(el)))
    if not matches:
        return False
    m = matches[-1] if last else matches[0]
    _replace_range(el, m.start(), m.end())
    return True


def _strip_first(elements, pattern: re.Pattern):
    for el in elements:
        if _strip_in_element(el, pattern, last=False):
            return el
    return None


def _strip_last(elements, pattern: re.Pattern):
    for el in reversed(elements):
        if _strip_in_element(el, pattern, last=True):
            return el
    return None


def _is_droppable(el) -> bool:
    ln = _localname(el)
    if ln not in ("p", "h", "table-row", "list-item", "table-cell"):
        return False
    text = _text(el)
    return text.strip() == "" and "{%" not in text and "{{" not in text


def _process_sequence(elements: list, ctx: dict, env: Environment) -> list:
    temp = etree.Element("docmcp-temp")
    for el in elements:
        temp.append(el)
    _process_children(temp, ctx, env)
    return list(temp)


def _render_leaf(el, ctx: dict, env: Environment) -> None:
    text = _text(el)
    if "{{" not in text and "{%" not in text and "{#" not in text:
        return
    safe_inline = {
        "span",
        "s",
        "tab",
        "line-break",
        "bookmark",
        "bookmark-start",
        "bookmark-end",
    }
    protected = any(_localname(ch) not in safe_inline for ch in el if _is_element(ch))
    if protected:
        for node in el.iter():
            if node.text and ("{{" in node.text or "{%" in node.text):
                try:
                    node.text = _render_string(node.text, ctx, env)
                except (TemplateSyntaxError, ValueError):
                    pass
            if node.tail and ("{{" in node.tail or "{%" in node.tail):
                try:
                    node.tail = _render_string(node.tail, ctx, env)
                except (TemplateSyntaxError, ValueError):
                    pass
        return
    rendered = _render_string(text, ctx, env)
    if rendered.strip() == "" and "{%" in text:
        parent = el.getparent()
        if parent is not None:
            parent.remove(el)
        return
    if rendered != text:
        _set_leaf_text(el, rendered)


def _find_region_end(children: list, idx: int) -> int | None:
    kind = _opens_kind(_text(children[idx]))
    if kind is None:
        return None
    open_re = RE_FOR_OPEN if kind == "for" else RE_IF_OPEN
    close_re = RE_ENDFOR if kind == "for" else RE_ENDIF
    depth = 0
    for k in range(idx, len(children)):
        el = children[k]
        if not _is_element(el):
            continue
        t = _text(el)
        depth += len(open_re.findall(t)) - len(close_re.findall(t))
        if depth <= 0:
            return k if k > idx else None
    return None


def _splice(container, index: int, count: int, new_elements: list) -> None:
    children = list(container)
    removed = children[index : index + count]
    for el in removed:
        container.remove(el)
    for offset, el in enumerate(new_elements):
        container.insert(index + offset, el)


def _handle_for(container, body: list, index: int, ctx: dict, env: Environment) -> None:
    m = RE_FOR_OPEN.search(_text(body[0]))
    if not m:
        raise ValueError("Internal error: could not parse {% for %} tag")
    var, expr = m.group(1), m.group(2)
    value = _eval_expr(expr, ctx, env)
    try:
        items = list(value) if value is not None else []
    except TypeError as exc:
        raise ValueError(
            f"'{{% for {var} in {expr} %}}': expression is not iterable"
        ) from exc
    if len(items) > MAX_LOOP_ITEMS:
        raise ValueError(
            f"'{{% for {var} in {expr} %}}' produced too many items (>{MAX_LOOP_ITEMS})"
        )

    count = len(body)
    mod_close = _strip_last(body, RE_ENDFOR)
    mod_open = _strip_first(body, RE_FOR_OPEN)
    drop = {id(x) for x in (mod_open, mod_close) if x is not None and _is_droppable(x)}
    body = [el for el in body if id(el) not in drop]

    result: list = []
    length = len(items)
    for n, item in enumerate(items):
        subctx = dict(ctx)
        subctx[var] = item
        subctx["loop"] = LoopContext(n, length)
        result.extend(
            _process_sequence([copy.deepcopy(el) for el in body], subctx, env)
        )

    _splice(container, index, count, result)


def _handle_if(container, body: list, index: int, ctx: dict, env: Environment) -> None:
    m = RE_IF_OPEN.search(_text(body[0]))
    if not m:
        raise ValueError("Internal error: could not parse {% if %} tag")
    expr = m.group(1)
    count = len(body)
    cond = bool(_eval_expr(expr, ctx, env))
    if not cond:
        _splice(container, index, count, [])
        return

    new_body = [copy.deepcopy(el) for el in body]
    mod_close = _strip_last(new_body, RE_ENDIF)
    mod_open = _strip_first(new_body, RE_IF_OPEN)
    drop = {id(x) for x in (mod_open, mod_close) if x is not None and _is_droppable(x)}
    new_body = [el for el in new_body if id(el) not in drop]
    result = _process_sequence(new_body, dict(ctx), env)
    _splice(container, index, count, result)


def _handle_row_loop(row, ctx: dict, env: Environment) -> None:
    cells = [c for c in row if _localname(c) == "table-cell"]
    open_cell = next((c for c in cells if _balance(_text(c))[0] > 0), None)
    if open_cell is None:
        _process_children(row, ctx, env)
        return
    m = RE_FOR_OPEN.search(_text(open_cell))
    if not m:
        _process_children(row, ctx, env)
        return
    var, expr = m.group(1), m.group(2)
    value = _eval_expr(expr, ctx, env)
    try:
        items = list(value) if value is not None else []
    except TypeError as exc:
        raise ValueError(
            f"'{{% for {var} in {expr} %}}': expression is not iterable"
        ) from exc
    if len(items) > MAX_LOOP_ITEMS:
        raise ValueError(
            f"'{{% for {var} in {expr} %}}' produced too many items (>{MAX_LOOP_ITEMS})"
        )

    _strip_last([row], RE_ENDFOR)
    _strip_first([row], RE_FOR_OPEN)

    parent = row.getparent()
    index = parent.index(row)
    result = []
    length = len(items)
    for n, item in enumerate(items):
        subctx = dict(ctx)
        subctx[var] = item
        subctx["loop"] = LoopContext(n, length)
        dup = copy.deepcopy(row)
        _process_children(dup, subctx, env)
        result.append(dup)
    _splice(parent, index, 1, result)


def _handle_row_if(row, ctx: dict, env: Environment) -> None:
    cells = [c for c in row if _localname(c) == "table-cell"]
    open_cell = next((c for c in cells if _balance(_text(c))[1] > 0), None)
    m = RE_IF_OPEN.search(_text(open_cell)) if open_cell is not None else None
    if not m:
        _process_children(row, ctx, env)
        return
    expr = m.group(1)
    cond = bool(_eval_expr(expr, ctx, env))
    if not cond:
        parent = row.getparent()
        if parent is not None:
            parent.remove(row)
        return
    _strip_last([row], RE_ENDIF)
    _strip_first([row], RE_IF_OPEN)
    _process_children(row, ctx, env)


def _handle_row(row, ctx: dict, env: Environment) -> None:
    cells = [c for c in row if _localname(c) == "table-cell"]
    balances = [_balance(_text(c)) for c in cells]
    total_for = sum(b[0] for b in balances)
    total_if = sum(b[1] for b in balances)
    if total_for == 0 and total_if == 0 and any(b[0] > 0 for b in balances):
        _handle_row_loop(row, ctx, env)
    elif total_for == 0 and total_if == 0 and any(b[1] > 0 for b in balances):
        _handle_row_if(row, ctx, env)
    else:
        _process_children(row, ctx, env)


def _process_element(el, ctx: dict, env: Environment) -> None:
    ln = _localname(el)
    if ln in LEAF_TAGS:
        _render_leaf(el, ctx, env)
    elif ln == "table-row":
        _handle_row(el, ctx, env)
    elif ln in CONTAINER_TAGS:
        _process_children(el, ctx, env)


def _process_children(container, ctx: dict, env: Environment) -> None:
    i = 0
    while True:
        children = list(container)
        if i >= len(children):
            break
        el = children[i]
        if not _is_element(el):
            i += 1
            continue
        text = _text(el)
        if "{%" in text and _balance(text) != (0, 0):
            end = _find_region_end(children, i)
            if end is not None:
                kind = _opens_kind(text)
                body = children[i : end + 1]
                if kind == "for":
                    _handle_for(container, body, i, ctx, env)
                else:
                    _handle_if(container, body, i, ctx, env)
                i = 0
                continue
            if _localname(el) in CONTAINER_TAGS:
                _process_children(el, ctx, env)
                i += 1
                continue
            kind = _opens_kind(text)
            raise ValueError(
                f"Unclosed {{{{ {kind} }}}} block: no matching {{% end{kind} %}} found"
            )
        _process_element(el, ctx, env)
        i += 1


def fill_odt(template_path: str, context: dict, strict: bool = True) -> bytes:
    with zipfile.ZipFile(template_path) as z:
        names = z.namelist()
        entries = {n: z.read(n) for n in names}

    parser = etree.XMLParser(
        resolve_entities=False, huge_tree=True, remove_blank_text=False
    )
    content = entries["content.xml"]
    root = etree.fromstring(content, parser)
    body = root.find(f".//{_qn(NS_OFFICE, 'text')}")
    if body is None:
        raise ValueError("Invalid ODT: no office:text element in content.xml")

    env = _make_env(strict)
    _process_children(body, dict(context), env)

    entries["content.xml"] = etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", standalone=True
    )
    return _rezip(names, entries)


def _rezip(names: list[str], entries: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        if "mimetype" in entries:
            info = zipfile.ZipInfo("mimetype")
            info.compress_type = zipfile.ZIP_STORED
            z.writestr(info, entries["mimetype"])
        for name in names:
            if name == "mimetype":
                continue
            z.writestr(name, entries[name])
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #


def extract_odt_text(path: str) -> str:
    with zipfile.ZipFile(path) as z:
        content = z.read("content.xml")
    root = etree.fromstring(
        content, etree.XMLParser(resolve_entities=False, huge_tree=True)
    )
    body = root.find(f".//{_qn(NS_OFFICE, 'text')}")
    lines: list[str] = []
    if body is not None:
        _walk_odt(body, lines)
    return "\n".join(ln for ln in lines if ln.strip())


def _walk_odt(el, lines: list[str]) -> None:
    for child in el:
        ln = _localname(child)
        if ln == "table-row":
            cells = [_text(c) for c in child if _localname(c) == "table-cell"]
            lines.append(" | ".join(cells))
        elif ln == "h":
            lvl = child.get(_qn(NS_TEXT, "outline-level")) or "1"
            try:
                lvl_int = int(lvl)
            except ValueError:
                lvl_int = 1
            lines.append("#" * lvl_int + " " + _text(child))
        elif ln == "p":
            lines.append(_text(child))
        elif ln == "line-break":
            continue
        else:
            _walk_odt(child, lines)


# --------------------------------------------------------------------------- #
# Creation
# --------------------------------------------------------------------------- #


class _OdtBuilder:
    def __init__(self):
        self.doc = OpenDocumentText()
        self._text_styles: dict = {}
        self._heading_styles: dict = {}
        self._code_style = self._mk_par_style(
            "CodeBlock", background="#F2F2F2", mono=True
        )
        self._quote_style = self._mk_par_style(
            "QuoteBlock", indent="0.5cm", italic=True
        )
        self._hr_style = self._mk_par_style("HRule", border=True)
        self._list_bullet = self._mk_list_bullet()
        self._list_number = self._mk_list_number()

    def _mk_text_style(self, bold=False, italic=False, mono=False) -> Style:
        key = (bold, italic, mono)
        if key in self._text_styles:
            return self._text_styles[key]
        name = f"T{int(bold)}{int(italic)}{int(mono)}"
        st = Style(name=name, family="text")
        props = {}
        if bold:
            props["fontweight"] = "bold"
        if italic:
            props["fontstyle"] = "italic"
        if mono:
            props["fontfamily"] = _MONO
        st.addElement(TextProperties(**props))
        self.doc.automaticstyles.addElement(st)
        self._text_styles[key] = st
        return st

    def _mk_par_style(
        self, name, background=None, indent=None, mono=False, italic=False, border=False
    ) -> Style:
        st = Style(name=name, family="paragraph")
        pp = {}
        if background:
            pp["backgroundcolor"] = background
        if indent:
            pp["marginleft"] = indent
        if border:
            pp["borderbottom"] = "0.5pt solid #AAAAAA"
        if pp:
            st.addElement(ParagraphProperties(**pp))
        tp = {}
        if mono:
            tp["fontfamily"] = _MONO
        if italic:
            tp["fontstyle"] = "italic"
        if tp:
            st.addElement(TextProperties(**tp))
        self.doc.automaticstyles.addElement(st)
        return st

    def _mk_heading_style(self, level: int) -> Style:
        if level in self._heading_styles:
            return self._heading_styles[level]
        sizes = {1: "18pt", 2: "15pt", 3: "13pt", 4: "12pt"}
        st = Style(name=f"Heading{level}", family="paragraph")
        st.addElement(ParagraphProperties(marginbottom="0.2cm"))
        tp = {"fontweight": "bold", "fontsize": sizes.get(level, "11pt")}
        if level >= 4:
            tp["fontstyle"] = "italic"
        st.addElement(TextProperties(**tp))
        self.doc.automaticstyles.addElement(st)
        self._heading_styles[level] = st
        return st

    def _mk_list_bullet(self) -> ListStyle:
        ls = ListStyle(name="BulletList")
        for lvl in range(1, 5):
            ls.addElement(ListLevelStyleBullet(bulletchar="•", level=lvl))
        self.doc.automaticstyles.addElement(ls)
        return ls

    def _mk_list_number(self) -> ListStyle:
        ls = ListStyle(name="NumberList")
        for lvl in range(1, 5):
            ls.addElement(ListLevelStyleNumber(level=lvl, numsuffix=".", numformat="1"))
        self.doc.automaticstyles.addElement(ls)
        return ls

    def _add_runs(self, el, runs: list[Run]) -> None:
        for r in runs:
            if not r.text:
                continue
            if r.link:
                a = A(href=r.link)
                a.addElement(Span(text=r.text))
                el.addElement(a)
            elif r.bold or r.italic or r.code:
                el.addElement(
                    Span(
                        text=r.text,
                        stylename=self._mk_text_style(r.bold, r.italic, r.code),
                    )
                )
            else:
                el.addText(r.text)

    def add_block(self, b: Block) -> None:
        if b.type == "heading":
            level = max(1, min(b.level, 4))
            h = H(outlinelevel=level, stylename=self._mk_heading_style(level))
            self._add_runs(h, b.runs)
            self.doc.text.addElement(h)
        elif b.type == "paragraph":
            p = P()
            self._add_runs(p, b.runs)
            self.doc.text.addElement(p)
        elif b.type in ("bullet_list", "ordered_list"):
            style = self._list_bullet if b.type == "bullet_list" else self._list_number
            lst = List(stylename=style)
            for item in b.items:
                li = ListItem()
                p = P()
                if item.depth:
                    p.addText("    " * item.depth)
                self._add_runs(p, item.runs)
                li.addElement(p)
                lst.addElement(li)
            self.doc.text.addElement(lst)
        elif b.type == "code":
            p = P(stylename=self._code_style)
            lines = b.text.split("\n")
            for n, line in enumerate(lines):
                p.addText(line)
                if n < len(lines) - 1:
                    p.addElement(LineBreak())
            self.doc.text.addElement(p)
        elif b.type == "quote":
            p = P(stylename=self._quote_style)
            self._add_runs(p, b.runs)
            self.doc.text.addElement(p)
        elif b.type == "table":
            self._add_table(b)
        elif b.type == "hr":
            self.doc.text.addElement(P(stylename=self._hr_style, text=""))

    def _add_table(self, b: Block) -> None:
        cols = len(b.header) if b.header else (len(b.rows[0]) if b.rows else 0)
        if cols == 0:
            return
        rows = ([b.header] if b.header else []) + b.rows
        table = Table(name="Table1")
        table.addElement(TableColumn(numbercolumnsrepeated=cols))
        for i, row in enumerate(rows):
            tr = TableRow()
            for j in range(cols):
                cell = TableCell(valuetype="string")
                p = P()
                text = row[j] if j < len(row) else ""
                if i == 0 and b.header:
                    p.addElement(
                        Span(text=text, stylename=self._mk_text_style(bold=True))
                    )
                else:
                    p.addText(text)
                cell.addElement(p)
                tr.addElement(cell)
            table.addElement(tr)
        self.doc.text.addElement(table)

    def set_meta(self, meta: dict) -> None:
        if meta.get("title"):
            self.doc.meta.addElement(Title(text=str(meta["title"])))
        if meta.get("author"):
            self.doc.meta.addElement(Creator(text=str(meta["author"])))
        if meta.get("subject"):
            self.doc.meta.addElement(Subject(text=str(meta["subject"])))
        if meta.get("comments"):
            self.doc.meta.addElement(Description(text=str(meta["comments"])))

    def save(self) -> bytes:
        buf = io.BytesIO()
        self.doc.save(buf)
        return buf.getvalue()


def create_odt(blocks: list[Block], meta: dict | None = None) -> bytes:
    builder = _OdtBuilder()
    for b in blocks:
        builder.add_block(b)
    builder.set_meta(meta or {})
    return builder.save()
