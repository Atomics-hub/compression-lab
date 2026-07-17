"""Compression Lab public API with lazy product implementation loading."""

from __future__ import annotations

from ._constants import DEFAULT_EXTENSION, DEFAULT_MAX_OUTPUT_SIZE

__version__ = "0.1.0"

__all__ = [
    "DEFAULT_EXTENSION",
    "DEFAULT_MAX_OUTPUT_SIZE",
    "FrameInfo",
    "compress",
    "compress_file",
    "decompress",
    "decompress_file",
    "inspect_frame",
    "__version__",
]

_LAZY_API_EXPORTS = frozenset(__all__) - {
    "DEFAULT_EXTENSION",
    "DEFAULT_MAX_OUTPUT_SIZE",
    "__version__",
}


def __getattr__(name: str):
    if name not in _LAZY_API_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from . import api

    value = getattr(api, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
