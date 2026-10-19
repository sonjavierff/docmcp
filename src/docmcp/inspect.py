"""Inspect templates: list placeholders, loops, conditions and variables."""

from __future__ import annotations

import re

from jinja2 import Environment, TemplateSyntaxError, meta

from .document import detect_format, extract_text

TOKEN_RE = re.compile(r"{{.*?}}|{%-?.*?-?%}|{#.*?#}", re.DOTALL)
RE_FOR = re.compile(
    r"{%-?\s*(?:\w+\s+)?for\s+([A-Za-z_]\w*)\s+in\s+(.+?)\s*-?%}", re.DOTALL
)
RE_ENDFOR = re.compile(r"{%-?\s*(?:\w+\s+)?endfor\s*-?%}")
RE_IF = re.compile(r"{%-?\s*(?:\w+\s+)?if\s+(.+?)\s*-?%}")
RE_ENDIF = re.compile(r"{%-?\s*(?:\w+\s+)?endif\s*-?%}")


def inspect_template(path: str) -> dict:
    fmt = detect_format(path)
    text = extract_text(path)

    tokens = []
    for m in TOKEN_RE.finditer(text):
        snippet = text[max(0, m.start() - 50) : m.end() + 50].replace("\n", " ")
        tokens.append({"token": m.group(0).strip(), "context": snippet.strip()})

    loops = [
        {"variable": m.group(1), "iterable": m.group(2)} for m in RE_FOR.finditer(text)
    ]
    conditions = [m.group(1) for m in RE_IF.finditer(text)]

    variables: list[str] = []
    parse_error: str | None = None
    if fmt == ".docx":
        try:
            from docxtpl import DocxTemplate

            variables = sorted(
                DocxTemplate(str(path)).get_undeclared_template_variables()
            )
        except Exception as exc:  # noqa: BLE001 - surface any docxtpl error to the caller
            parse_error = str(exc)
    else:
        try:
            env = Environment()
            variables = sorted(meta.find_undeclared_variables(env.parse(text)))
        except TemplateSyntaxError as exc:
            parse_error = f"{exc.message} (line {exc.lineno})"

    for_open, for_close = len(RE_FOR.findall(text)), len(RE_ENDFOR.findall(text))
    if_open, if_close = len(RE_IF.findall(text)), len(RE_ENDIF.findall(text))
    unbalanced = for_open != for_close or if_open != if_close

    return {
        "template": str(path),
        "format": fmt.lstrip("."),
        "variables": variables,
        "loops": loops,
        "conditions": conditions,
        "tokens": tokens,
        "unbalanced_blocks": unbalanced,
        "parse_error": parse_error,
    }
