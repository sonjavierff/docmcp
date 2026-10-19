from __future__ import annotations

import os
from pathlib import Path

import pytest

from docmcp import templates as templates_mod
from docmcp.context import AttrDict, wrap, wrap_context


def test_attrdict_key_wins_over_method():
    d = AttrDict({"items": [1, 2], "keys": "k"})
    assert d.items == [1, 2]
    assert d.keys == "k"
    assert d["items"] == [1, 2]
    with pytest.raises(AttributeError):
        _ = d.missing


def test_wrap_context_top_level_is_plain_dict():
    ctx = wrap_context({"a": {"items": [1]}})
    assert isinstance(ctx, dict)
    assert not isinstance(ctx, AttrDict)
    assert isinstance(ctx["a"], AttrDict)
    assert ctx["a"].items == [1]


def test_wrap_lists():
    wrapped = wrap([{"items": 1}, 2])
    assert wrapped[0].items == 1
    assert wrapped[1] == 2


def test_templates_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCMCP_TEMPLATES_DIR", str(tmp_path / "tpls"))
    source = tmp_path / "manual.md"
    source.write_text("# {{ titulo }}", encoding="utf-8")

    saved = templates_mod.save_template(str(source), "manual", "plantilla de manual")
    assert saved["name"] == "manual"

    listed = templates_mod.list_templates()
    assert any(t["name"] == "manual" and t["registered"] for t in listed)

    registered = Path(os.environ["DOCMCP_TEMPLATES_DIR"]) / "manual.md"
    assert templates_mod.resolve_template("manual") == registered
    assert templates_mod.resolve_template("manual.md") == registered

    with pytest.raises(FileNotFoundError):
        templates_mod.resolve_template("no-such-template")


def test_templates_dir_env(tmp_path, monkeypatch):
    target = tmp_path / "custom"
    monkeypatch.setenv("DOCMCP_TEMPLATES_DIR", str(target))
    assert templates_mod.templates_dir() == target
    assert target.is_dir()


def test_save_template_rejects_unknown_format(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCMCP_TEMPLATES_DIR", str(tmp_path / "tpls"))
    bad = tmp_path / "x.pdf"
    bad.write_bytes(b"%PDF")
    with pytest.raises(ValueError):
        templates_mod.save_template(str(bad), "x")
