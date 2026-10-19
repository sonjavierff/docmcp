from __future__ import annotations

from docmcp.document import create_document, extract_text
from docmcp.engines import docx_engine

MD = """# Manual de prueba

Párrafo con **negrita**, *cursiva*, `código` y un [enlace](https://example.com).

## Sección

- punto uno
- punto dos
  - sub punto

1. primero
2. segundo

> Una cita

```python
print("hola")
```

| Col A | Col B |
|-------|-------|
| 1     | 2     |

---

Texto final.
"""


def test_create_markdown(tmp_path):
    out = tmp_path / "doc.md"
    result = create_document(str(out), MD, {})
    assert result["format"] == "md"
    text = extract_text(str(out))
    assert "# Manual de prueba" in text
    assert "**negrita**" in text
    assert "- punto uno" in text
    assert "  - sub punto" in text  # nested item keeps indentation
    assert 'print("hola")' in text


def test_create_txt(tmp_path):
    out = tmp_path / "doc.txt"
    create_document(str(out), MD, {})
    text = extract_text(str(out))
    assert "Manual de prueba" in text
    assert "=====" in text
    assert "**negrita**" not in text
    assert "- sub punto" in text


def test_create_docx(tmp_path):
    out = tmp_path / "doc.docx"
    create_document(str(out), MD, {"title": "T", "author": "A"})
    assert docx_engine.extract_docx_text(str(out))
    text = extract_text(str(out))
    assert "Manual de prueba" in text


def test_create_odt(tmp_path):
    out = tmp_path / "doc.odt"
    create_document(str(out), MD, {"title": "T", "author": "A"})
    assert extract_text(str(out))


def test_invalid_format(tmp_path):
    import pytest

    with pytest.raises(ValueError):
        create_document(str(tmp_path / "doc.pdf"), MD, {})
