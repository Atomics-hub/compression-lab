from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


def run_import_assertion(source: str) -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    subprocess.run(
        [sys.executable, "-c", source],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


class LazyImportTests(unittest.TestCase):
    def test_package_root_defers_product_implementation(self) -> None:
        run_import_assertion(
            "import sys, compresslab; "
            "assert compresslab.__version__ == '0.1.0'; "
            "assert 'compresslab.api' not in sys.modules; "
            "assert 'compresslab.worker' not in sys.modules; "
            "assert 'compresslab.adaptive_v3' not in sys.modules"
        )

    def test_cli_parser_defers_command_implementations(self) -> None:
        run_import_assertion(
            "import sys, compresslab.cli; "
            "assert 'compresslab.api' not in sys.modules; "
            "assert 'compresslab.codecs' not in sys.modules; "
            "assert 'compresslab.experimental' not in sys.modules; "
            "assert 'compresslab.benchmark_runner' not in sys.modules"
        )

    def test_worker_parser_defers_codec_families(self) -> None:
        run_import_assertion(
            "import sys, compresslab.worker; "
            "assert 'compresslab.codecs' not in sys.modules; "
            "assert 'compresslab.native' not in sys.modules; "
            "assert 'compresslab.json_log_codec' not in sys.modules; "
            "assert 'compresslab.adaptive_v3' not in sys.modules; "
            "assert 'compresslab.tabular_transform' not in sys.modules"
        )

    def test_experimental_json_api_does_not_load_general_codec(self) -> None:
        run_import_assertion(
            "import sys, compresslab.experimental; "
            "assert 'compresslab.api' not in sys.modules; "
            "assert 'compresslab.worker' not in sys.modules; "
            "assert 'compresslab.adaptive_v3' not in sys.modules; "
            "assert 'compresslab.tabular_transform' not in sys.modules"
        )


if __name__ == "__main__":
    unittest.main()
