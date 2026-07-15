from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path
from typing import Callable, Optional


_Transform = Callable[[bytes], bytes]
_LIBRARY: Optional[ctypes.CDLL] = None
_LOAD_ATTEMPTED = False


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
