from __future__ import annotations

import ctypes
import os
from pathlib import Path
import sys
from typing import Optional


_LIBRARY: Optional[ctypes.CDLL] = None
_LOAD_ATTEMPTED = False


def _library_filename() -> str:
    if sys.platform == "darwin":
        return "libcompression_lab_dense_native.dylib"
    if sys.platform == "win32":
        return "compression_lab_dense_native.dll"
    return "libcompression_lab_dense_native.so"


def _library_path() -> Path:
    override = os.environ.get("COMPRESSION_LAB_DENSE_NATIVE_LIB")
    if override:
        return Path(override)
    packaged = Path(__file__).resolve().parent / "_native" / _library_filename()
    if packaged.is_file():
        return packaged
    repository = Path(__file__).resolve().parents[2]
    target = repository / "native-dense" / "target"
    default = target / "release" / _library_filename()
    if default.is_file() or sys.platform != "darwin":
        return default
    machine = os.uname().machine.lower()
    triple = (
        "aarch64-apple-darwin"
        if machine in {"arm64", "aarch64"}
        else "x86_64-apple-darwin"
    )
    cross_compiled = target / triple / "release" / _library_filename()
    return cross_compiled if cross_compiled.is_file() else default


def _configure_transform(library: ctypes.CDLL, name: str) -> None:
    function = getattr(library, name)
    function.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
        ctypes.POINTER(ctypes.c_uint8),
    ]
    function.restype = ctypes.c_int


def _configure_reassemble(library: ctypes.CDLL, name: str) -> None:
    function = getattr(library, name)
    function.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_uint8,
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    function.restype = ctypes.c_int


def _load_library() -> Optional[ctypes.CDLL]:
    global _LIBRARY, _LOAD_ATTEMPTED
    if _LOAD_ATTEMPTED:
        return _LIBRARY
    _LOAD_ATTEMPTED = True
    path = _library_path()
    if not path.is_file():
        return None
    library = ctypes.CDLL(str(path))
    for name in (
        "clab_dense_adaptive_transform",
        "clab_dense_parallel_transform",
        "clab_dense_plane_transform",
    ):
        _configure_transform(library, name)
    for name in (
        "clab_dense_adaptive_reassemble",
        "clab_dense_parallel_reassemble",
        "clab_dense_plane_reassemble",
    ):
        _configure_reassemble(library, name)
    library.clab_dense_sample_alphabet.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    library.clab_dense_sample_alphabet.restype = ctypes.c_int
    _LIBRARY = library
    return library


def dense_adaptive_native_available() -> bool:
    return _load_library() is not None


def dense_parallel_native_available() -> bool:
    return _load_library() is not None


def dense_plane_native_available() -> bool:
    return _load_library() is not None


def _transform(name: str, label: str, data: bytes) -> tuple[bytes, bool]:
    library = _load_library()
    if library is None:
        raise RuntimeError("compression-lab dense native library is not built")
    source = ctypes.c_char_p(data)
    capacity = len(data) + len(data) // 8 + 4096
    output = ctypes.create_string_buffer(max(1, capacity))
    output_len = ctypes.c_size_t()
    starts_with_token = ctypes.c_uint8()
    function = getattr(library, name)
    result = function(
        source,
        len(data),
        output,
        capacity,
        ctypes.byref(output_len),
        ctypes.byref(starts_with_token),
    )
    if result == 3:
        capacity = output_len.value
        output = ctypes.create_string_buffer(max(1, capacity))
        result = function(
            source,
            len(data),
            output,
            capacity,
            ctypes.byref(output_len),
            ctypes.byref(starts_with_token),
        )
    if result != 0:
        raise ValueError(f"native {label} transform rejected input with status {result}")
    return output.raw[: output_len.value], bool(starts_with_token.value)


def _reassemble(
    name: str,
    label: str,
    data: bytes,
    starts_with_token: bool,
    expected_size: int,
) -> bytes:
    if expected_size < 0:
        raise ValueError("expected size cannot be negative")
    library = _load_library()
    if library is None:
        raise RuntimeError("compression-lab dense native library is not built")
    source = ctypes.c_char_p(data)
    output = ctypes.create_string_buffer(max(1, expected_size))
    result = getattr(library, name)(
        source,
        len(data),
        int(starts_with_token),
        output,
        expected_size,
    )
    if result != 0:
        raise ValueError(
            f"native {label} reassembly rejected invalid data with status {result}"
        )
    return output.raw[:expected_size]


def dense_adaptive_transform(data: bytes) -> tuple[bytes, bool]:
    return _transform("clab_dense_adaptive_transform", "DMA1", data)


def dense_adaptive_reassemble(
    data: bytes, starts_with_token: bool, expected_size: int
) -> bytes:
    return _reassemble(
        "clab_dense_adaptive_reassemble",
        "DMA1",
        data,
        starts_with_token,
        expected_size,
    )


def dense_parallel_transform(data: bytes) -> tuple[bytes, bool]:
    return _transform("clab_dense_parallel_transform", "DMA2", data)


def dense_parallel_reassemble(
    data: bytes, starts_with_token: bool, expected_size: int
) -> bytes:
    return _reassemble(
        "clab_dense_parallel_reassemble",
        "DMA2",
        data,
        starts_with_token,
        expected_size,
    )


def dense_plane_transform(data: bytes) -> tuple[bytes, bool]:
    return _transform("clab_dense_plane_transform", "DMP1", data)


def dense_plane_reassemble(
    data: bytes, starts_with_token: bool, expected_size: int
) -> bytes:
    return _reassemble(
        "clab_dense_plane_reassemble",
        "DMP1",
        data,
        starts_with_token,
        expected_size,
    )


def dense_sample_alphabet(data: bytes, sample_size: int = 64 * 1024) -> int:
    if sample_size <= 0:
        raise ValueError("sample size must be positive")
    library = _load_library()
    if library is None:
        raise RuntimeError("compression-lab dense native library is not built")
    source = ctypes.c_char_p(data)
    alphabet_size = ctypes.c_size_t()
    result = library.clab_dense_sample_alphabet(
        source,
        len(data),
        sample_size,
        ctypes.byref(alphabet_size),
    )
    if result != 0:
        raise ValueError(f"native dense selector rejected input with status {result}")
    return alphabet_size.value
