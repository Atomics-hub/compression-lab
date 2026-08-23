from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from compresslab import dense_native, native


class NativeLoadFallbackTests(unittest.TestCase):
    def _assert_load_failure_is_cached(self, module, failure: object) -> None:
        with tempfile.TemporaryDirectory() as directory:
            library_path = Path(directory) / module._library_filename()
            library_path.touch()
            loader_patch = (
                patch.object(module.ctypes, "CDLL", side_effect=failure)
                if isinstance(failure, BaseException)
                else patch.object(module.ctypes, "CDLL", return_value=failure)
            )
            with (
                patch.object(module, "_LIBRARY", None),
                patch.object(module, "_LOAD_ATTEMPTED", False),
                patch.object(module, "_library_path", return_value=library_path),
                loader_patch as loader,
            ):
                self.assertIsNone(module._load_library())
                self.assertIsNone(module._load_library())
                loader.assert_called_once_with(str(library_path))

    def test_native_loader_falls_back_on_incompatible_binary(self) -> None:
        self._assert_load_failure_is_cached(native, OSError("wrong architecture"))

    def test_dense_loader_falls_back_on_incompatible_binary(self) -> None:
        self._assert_load_failure_is_cached(
            dense_native, OSError("wrong architecture")
        )

    def test_native_loader_falls_back_on_stale_symbol_surface(self) -> None:
        self._assert_load_failure_is_cached(native, object())

    def test_dense_loader_falls_back_on_stale_symbol_surface(self) -> None:
        self._assert_load_failure_is_cached(dense_native, object())

    def _assert_zstd_load_failure_is_cached(self, failure: object) -> None:
        loader_patch = (
            patch.object(native.ctypes, "CDLL", side_effect=failure)
            if isinstance(failure, BaseException)
            else patch.object(native.ctypes, "CDLL", return_value=failure)
        )
        with (
            patch.dict(
                os.environ,
                {"COMPRESSION_LAB_ZSTD_LIB": "/incompatible/libzstd"},
            ),
            patch.object(native, "_ZSTD_LIBRARY", None),
            patch.object(native, "_ZSTD_LOAD_ATTEMPTED", False),
            patch.object(native, "_ZSTD_STREAM_FUNCTIONS", None),
            patch.object(native.ctypes.util, "find_library", return_value=None),
            loader_patch as loader,
        ):
            self.assertIsNone(native._load_zstd())
            call_count = loader.call_count
            self.assertGreater(call_count, 0)
            self.assertIsNone(native._load_zstd())
            self.assertEqual(loader.call_count, call_count)

    def test_zstd_loader_falls_back_on_incompatible_binary(self) -> None:
        self._assert_zstd_load_failure_is_cached(OSError("wrong architecture"))

    def test_zstd_loader_falls_back_on_stale_symbol_surface(self) -> None:
        self._assert_zstd_load_failure_is_cached(object())

    def test_real_invalid_overrides_do_not_break_import(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            invalid = Path(directory) / "not-a-library"
            invalid.write_bytes(b"not a dynamic library")
            environment = os.environ.copy()
            environment.update(
                {
                    "COMPRESSION_LAB_NATIVE_LIB": str(invalid),
                    "COMPRESSION_LAB_DENSE_NATIVE_LIB": str(invalid),
                    "COMPRESSION_LAB_ZSTD_LIB": str(invalid),
                }
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "from compresslab.native import native_available, "
                        "zstd_available, zstd_engine; "
                        "from compresslab.dense_native import "
                        "dense_adaptive_native_available; "
                        "assert not native_available(); "
                        "assert not dense_adaptive_native_available(); "
                        "assert zstd_available(); "
                        "assert zstd_engine() in "
                        "{'libzstd-ffi', 'python-zstandard'}"
                    ),
                ],
                check=False,
                capture_output=True,
                env=environment,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_real_library_with_stale_symbols_falls_back(self) -> None:
        import _ctypes

        location = getattr(_ctypes, "__file__", None)
        if location is None:
            self.skipTest("_ctypes is statically linked")
        stale_library = Path(location)
        self.assertTrue(stale_library.is_file())
        environment = os.environ.copy()
        environment.update(
            {
                "COMPRESSION_LAB_NATIVE_LIB": str(stale_library),
                "COMPRESSION_LAB_DENSE_NATIVE_LIB": str(stale_library),
                "COMPRESSION_LAB_ZSTD_LIB": str(stale_library),
            }
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from compresslab.native import native_available, "
                    "zstd_available, zstd_engine; "
                    "from compresslab.dense_native import "
                    "dense_adaptive_native_available; "
                    "assert not native_available(); "
                    "assert not dense_adaptive_native_available(); "
                    "assert zstd_available(); "
                    "assert zstd_engine() in "
                    "{'libzstd-ffi', 'python-zstandard'}"
                ),
            ],
            check=False,
            capture_output=True,
            env=environment,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
