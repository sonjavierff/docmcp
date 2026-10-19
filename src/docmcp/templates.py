"""Registry of reusable document templates.

Registered templates live in ``DOCMCP_TEMPLATES_DIR`` (default
``~/.config/opencode/doc-templates``) and are described by an ``index.json``
sidecar. Any absolute path can also be used directly, bypassing the registry.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path

SUPPORTED_FORMATS = (".md", ".txt", ".docx", ".odt")
DEFAULT_TEMPLATES_DIR = "~/.config/opencode/doc-templates"


def templates_dir() -> Path:
    raw = os.environ.get("DOCMCP_TEMPLATES_DIR") or DEFAULT_TEMPLATES_DIR
    path = Path(raw).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _index_path(directory: Path) -> Path:
    return directory / "index.json"


def _load_index(directory: Path) -> dict:
    path = _index_path(directory)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_index(directory: Path, index: dict) -> None:
    _index_path(directory).write_text(
        json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def list_templates() -> list[dict]:
    directory = templates_dir()
    index = _load_index(directory)
    entries: dict[str, dict] = {}
    for path in sorted(directory.iterdir()):
        if path.is_file() and path.suffix.lower() in SUPPORTED_FORMATS:
            meta = index.get(path.stem, {})
            entries[path.stem] = {
                "name": path.stem,
                "file": str(path),
                "format": path.suffix.lstrip("."),
                "description": meta.get("description", ""),
                "registered": path.stem in index,
            }
    for name, meta in index.items():
        if name not in entries:
            entries[name] = {
                "name": name,
                "file": None,
                "format": meta.get("format", ""),
                "description": meta.get("description", ""),
                "registered": True,
                "missing": True,
            }
    return sorted(entries.values(), key=lambda e: e["name"])


def save_template(source_path: str, name: str, description: str = "") -> dict:
    source = Path(source_path).expanduser()
    if not source.is_file():
        raise FileNotFoundError(f"Source file not found: {source}")
    ext = source.suffix.lower()
    if ext not in SUPPORTED_FORMATS:
        raise ValueError(
            f"Unsupported template format '{ext}'. Supported: {', '.join(SUPPORTED_FORMATS)}"
        )
    name = (name or source.stem).strip()
    if not name or "/" in name or "\\" in name:
        raise ValueError("Template name must be a simple non-empty string")

    directory = templates_dir()
    destination = directory / f"{name}{ext}"
    shutil.copy2(source, destination)

    index = _load_index(directory)
    index[name] = {
        "file": destination.name,
        "format": ext.lstrip("."),
        "description": description,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
    }
    _save_index(directory, index)
    return {
        "name": name,
        "file": str(destination),
        "format": ext.lstrip("."),
        "description": description,
    }


def resolve_template(name_or_path: str) -> Path:
    candidate = Path(name_or_path).expanduser()
    if candidate.is_file():
        return candidate

    directory = templates_dir()
    direct = directory / name_or_path
    if direct.is_file():
        return direct

    index = _load_index(directory)
    if name_or_path in index:
        path = directory / index[name_or_path]["file"]
        if path.is_file():
            return path

    if not candidate.suffix:
        for ext in SUPPORTED_FORMATS:
            path = directory / f"{name_or_path}{ext}"
            if path.is_file():
                return path

    raise FileNotFoundError(
        f"Template '{name_or_path}' not found. It was not a readable path and is not "
        f"registered in {directory}"
    )
