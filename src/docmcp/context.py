"""Context helpers.

Jinja2 resolves ``foo.bar`` as ``getattr(foo, "bar")`` and then ``foo["bar"]``.
With plain dicts this breaks for keys whose name collides with a dict method
(``items``, ``keys``, ``values``, ``get``...): ``{{ c.items }}`` would return
the bound method instead of the value. :class:`AttrDict` wraps mappings so that
keys always win, making nested contexts behave as users expect.
"""

from __future__ import annotations


class AttrDict:
    __slots__ = ("_d",)

    def __init__(self, mapping: dict):
        object.__setattr__(self, "_d", mapping)

    def __getattr__(self, name: str):
        try:
            return self._d[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __getitem__(self, key):
        return self._d[key]

    def __contains__(self, key) -> bool:
        return key in self._d

    def __iter__(self):
        return iter(self._d)

    def __len__(self) -> int:
        return len(self._d)

    def __repr__(self) -> str:
        return repr(self._d)


def wrap(value):
    """Recursively wrap dicts in :class:`AttrDict` (lists/tuples are mapped too)."""
    if isinstance(value, dict):
        return AttrDict({k: wrap(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return [wrap(v) for v in value]
    return value


def wrap_context(context: dict) -> dict:
    """Wrap a top-level context: plain dict on top, :class:`AttrDict` for nested values.

    The top level stays a real ``dict`` so it can be passed directly to Jinja's
    ``render()`` and copied, while nested mappings gain key-first attribute access.
    """
    return {k: wrap(v) for k, v in context.items()}
