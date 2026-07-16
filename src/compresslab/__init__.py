"""Compression Lab public API."""

from .api import (
    DEFAULT_EXTENSION,
    DEFAULT_MAX_OUTPUT_SIZE,
    FrameInfo,
    compress,
    compress_file,
    decompress,
    decompress_file,
    inspect_frame,
)

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
