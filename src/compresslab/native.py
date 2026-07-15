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


class _ZstdInBuffer(ctypes.Structure):
    _fields_ = [
        ("src", ctypes.c_void_p),
        ("size", ctypes.c_size_t),
        ("pos", ctypes.c_size_t),
    ]


class _ZstdOutBuffer(ctypes.Structure):
    _fields_ = [
        ("dst", ctypes.c_void_p),
        ("size", ctypes.c_size_t),
        ("pos", ctypes.c_size_t),
    ]


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
    library.clab_structured_text_encode.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    library.clab_structured_text_encode.restype = ctypes.c_int
    library.clab_structured_text_decode.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    library.clab_structured_text_decode.restype = ctypes.c_int
    library.clab_structured_text_decoder_create.argtypes = [ctypes.c_size_t]
    library.clab_structured_text_decoder_create.restype = ctypes.c_void_p
    library.clab_structured_text_decoder_update.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    library.clab_structured_text_decoder_update.restype = ctypes.c_int
    library.clab_structured_text_decoder_finish.argtypes = [ctypes.c_void_p]
    library.clab_structured_text_decoder_finish.restype = ctypes.c_int
    library.clab_structured_text_decoder_free.argtypes = [ctypes.c_void_p]
    library.clab_structured_text_decoder_free.restype = None
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


def structured_text_encode(
    data: bytes, dictionary_limit: int, sample_budget: int = 1024 * 1024
) -> bytes:
    library = _load_library()
    if library is None:
        raise RuntimeError("compression-lab native library is not built")
    source = ctypes.create_string_buffer(data, max(1, len(data)))
    capacity = len(data) * 2 + 6 + 254 * 65
    output = ctypes.create_string_buffer(max(1, capacity))
    output_len = ctypes.c_size_t()
    result = library.clab_structured_text_encode(
        source,
        len(data),
        dictionary_limit,
        sample_budget,
        output,
        capacity,
        ctypes.byref(output_len),
    )
    if result != 0:
        raise RuntimeError(f"native structured-text encode failed with status {result}")
    return output.raw[:output_len.value]


def structured_text_decode(data: bytes, expected_size: int) -> bytes:
    library = _load_library()
    if library is None:
        raise RuntimeError("compression-lab native library is not built")
    source = ctypes.create_string_buffer(data, max(1, len(data)))
    output = ctypes.create_string_buffer(max(1, expected_size))
    result = library.clab_structured_text_decode(
        source, len(data), output, expected_size
    )
    if result != 0:
        raise ValueError(f"native structured-text decode failed with status {result}")
    return output.raw[:expected_size]


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
        library.ZSTD_createDStream.argtypes = []
        library.ZSTD_createDStream.restype = ctypes.c_void_p
        library.ZSTD_freeDStream.argtypes = [ctypes.c_void_p]
        library.ZSTD_freeDStream.restype = ctypes.c_size_t
        library.ZSTD_initDStream.argtypes = [ctypes.c_void_p]
        library.ZSTD_initDStream.restype = ctypes.c_size_t
        library.ZSTD_decompressStream.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_ZstdOutBuffer),
            ctypes.POINTER(_ZstdInBuffer),
        ]
        library.ZSTD_decompressStream.restype = ctypes.c_size_t
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


def structured_text_zstd_stream_decode(
    data: bytes,
    transformed_size: int,
    expected_size: int,
    chunk_size: int = 256 * 1024,
) -> bytes:
    native = _load_library()
    zstd = _load_zstd()
    if native is None or zstd is None:
        raise RuntimeError("native streaming structured-text decode is unavailable")
    if chunk_size < 1:
        raise ValueError("streaming decode chunk size must be positive")

    stream = zstd.ZSTD_createDStream()
    decoder = native.clab_structured_text_decoder_create(expected_size)
    if not stream or not decoder:
        if stream:
            zstd.ZSTD_freeDStream(stream)
        if decoder:
            native.clab_structured_text_decoder_free(decoder)
        raise RuntimeError("failed to allocate streaming structured-text decoder")

    source = ctypes.create_string_buffer(data, max(1, len(data)))
    source_buffer = _ZstdInBuffer(
        ctypes.cast(source, ctypes.c_void_p), len(data), 0
    )
    output = ctypes.create_string_buffer(max(1, expected_size))
    total_transformed = 0
    try:
        result = int(zstd.ZSTD_initDStream(stream))
        _zstd_error(zstd, result)
        chunk = ctypes.create_string_buffer(chunk_size)
        while True:
            chunk_buffer = _ZstdOutBuffer(
                ctypes.cast(chunk, ctypes.c_void_p), len(chunk), 0
            )
            result = int(
                zstd.ZSTD_decompressStream(
                    stream, ctypes.byref(chunk_buffer), ctypes.byref(source_buffer)
                )
            )
            _zstd_error(zstd, result)
            produced = int(chunk_buffer.pos)
            total_transformed += produced
            if total_transformed > transformed_size:
                raise ValueError("structured-text transformed size exceeds declaration")
            status = native.clab_structured_text_decoder_update(
                decoder, chunk, produced, output, expected_size
            )
            if status != 0:
                raise ValueError(
                    f"native streaming structured-text decode failed with status {status}"
                )
            if result == 0:
                if source_buffer.pos != source_buffer.size:
                    raise ValueError("structured-text zstd payload has trailing data")
                break
            if source_buffer.pos == source_buffer.size and produced == 0:
                raise ValueError("structured-text zstd payload is truncated")

        if total_transformed != transformed_size:
            raise ValueError("structured-text transformed size mismatch")
        status = native.clab_structured_text_decoder_finish(decoder)
        if status != 0:
            raise ValueError(
                f"native streaming structured-text finish failed with status {status}"
            )
        return output.raw[:expected_size]
    finally:
        native.clab_structured_text_decoder_free(decoder)
        zstd.ZSTD_freeDStream(stream)
