from __future__ import annotations

import ctypes
import ctypes.util
import os
import sys
from pathlib import Path
from typing import Callable, Optional


_Transform = Callable[[bytes], bytes]
_LIBRARY: Optional[ctypes.CDLL] = None
_LOAD_ATTEMPTED = False
_ZSTD_LIBRARY: Optional[ctypes.CDLL] = None
_ZSTD_LOAD_ATTEMPTED = False
_ZSTD_CONTENTSIZE_UNKNOWN = (1 << 64) - 1
_ZSTD_CONTENTSIZE_ERROR = (1 << 64) - 2


def _library_filename() -> str:
    if sys.platform == "darwin":
        return "libcompression_lab_native.dylib"
    if sys.platform == "win32":
        return "compression_lab_native.dll"
    return "libcompression_lab_native.so"


def _library_path() -> Path:
    override = os.environ.get("COMPRESSION_LAB_NATIVE_LIB")
    if override:
        return Path(override)
    repository = Path(__file__).resolve().parents[2]
    return repository / "native" / "target" / "release" / _library_filename()


def _load_library() -> Optional[ctypes.CDLL]:
    global _LIBRARY, _LOAD_ATTEMPTED
    if _LOAD_ATTEMPTED:
        return _LIBRARY
    _LOAD_ATTEMPTED = True
    path = _library_path()
    if not path.is_file():
        return None
    library = ctypes.CDLL(str(path))
    for name in ("clab_delta_transpose", "clab_inverse_delta_transpose"):
        function = getattr(library, name)
        function.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p]
        function.restype = ctypes.c_int
    _LIBRARY = library
    return library


def native_available() -> bool:
    return _load_library() is not None


def _call(name: str, data: bytes) -> bytes:
    library = _load_library()
    if library is None:
        raise RuntimeError("compression-lab native library is not built")
    if not data:
        return b""
    source = ctypes.create_string_buffer(data, len(data))
    output = ctypes.create_string_buffer(len(data))
    result = getattr(library, name)(source, len(data), output)
    if result != 0:
        raise RuntimeError(f"native transform failed with status {result}")
    return output.raw


def delta_transpose(data: bytes) -> bytes:
    return _call("clab_delta_transpose", data)


def inverse_delta_transpose(data: bytes) -> bytes:
    return _call("clab_inverse_delta_transpose", data)


def _load_zstd() -> Optional[ctypes.CDLL]:
    global _ZSTD_LIBRARY, _ZSTD_LOAD_ATTEMPTED
    if _ZSTD_LOAD_ATTEMPTED:
        return _ZSTD_LIBRARY
    _ZSTD_LOAD_ATTEMPTED = True
    override = os.environ.get("COMPRESSION_LAB_ZSTD_LIB")
    candidates = [
        candidate
        for candidate in (
            override,
            "/opt/homebrew/lib/libzstd.dylib",
            "/usr/local/lib/libzstd.dylib",
            "/usr/lib/libzstd.so",
        )
        if candidate
    ]
    candidates.append("")
    for candidate in candidates:
        if not candidate:
            candidate = ctypes.util.find_library("zstd") or ""
        if not candidate:
            return None
        try:
            library = ctypes.CDLL(candidate)
        except OSError:
            continue
        library.ZSTD_compressBound.argtypes = [ctypes.c_size_t]
        library.ZSTD_compressBound.restype = ctypes.c_size_t
        library.ZSTD_compress.argtypes = [
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_int,
        ]
        library.ZSTD_compress.restype = ctypes.c_size_t
        library.ZSTD_decompress.argtypes = [
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_void_p,
            ctypes.c_size_t,
        ]
        library.ZSTD_decompress.restype = ctypes.c_size_t
        library.ZSTD_getFrameContentSize.argtypes = [
            ctypes.c_void_p,
            ctypes.c_size_t,
        ]
        library.ZSTD_getFrameContentSize.restype = ctypes.c_ulonglong
        library.ZSTD_isError.argtypes = [ctypes.c_size_t]
        library.ZSTD_isError.restype = ctypes.c_uint
        library.ZSTD_getErrorName.argtypes = [ctypes.c_size_t]
        library.ZSTD_getErrorName.restype = ctypes.c_char_p
        _ZSTD_LIBRARY = library
        return library
    return None


def zstd_available() -> bool:
    return _load_zstd() is not None


def _zstd_error(library: ctypes.CDLL, result: int) -> None:
    if library.ZSTD_isError(result):
        detail = library.ZSTD_getErrorName(result).decode("utf-8", errors="replace")
        raise RuntimeError(f"libzstd error: {detail}")


def zstd_compress(data: bytes, level: int = 3) -> bytes:
    library = _load_zstd()
    if library is None:
        raise RuntimeError("libzstd is unavailable")
    source = ctypes.create_string_buffer(data, max(1, len(data)))
    capacity = int(library.ZSTD_compressBound(len(data)))
    output = ctypes.create_string_buffer(max(1, capacity))
    result = int(library.ZSTD_compress(output, capacity, source, len(data), level))
    _zstd_error(library, result)
    return output.raw[:result]


def zstd_frame_content_size(data: bytes) -> int:
    library = _load_zstd()
    if library is None:
        raise RuntimeError("libzstd is unavailable")
    source = ctypes.create_string_buffer(data, max(1, len(data)))
    result = int(library.ZSTD_getFrameContentSize(source, len(data)))
    if result == _ZSTD_CONTENTSIZE_ERROR:
        raise ValueError("libzstd frame content size is invalid")
    if result == _ZSTD_CONTENTSIZE_UNKNOWN:
        raise ValueError("libzstd frame does not declare its content size")
    return result


def zstd_decompress(data: bytes, expected_size: Optional[int] = None) -> bytes:
    library = _load_zstd()
    if library is None:
        raise RuntimeError("libzstd is unavailable")
    if expected_size is None:
        expected_size = zstd_frame_content_size(data)
    source = ctypes.create_string_buffer(data, max(1, len(data)))
    output = ctypes.create_string_buffer(max(1, expected_size))
    result = int(library.ZSTD_decompress(output, expected_size, source, len(data)))
    _zstd_error(library, result)
    if result != expected_size:
        raise ValueError(
            f"libzstd output size mismatch: expected {expected_size}, got {result}"
        )
    return output.raw[:result]
