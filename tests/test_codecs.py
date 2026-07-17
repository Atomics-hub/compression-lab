import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from compresslab.codecs import codec_by_id, probe_codec_versions
from compresslab.worker import run


class CodecProbeTests(unittest.TestCase):
    def test_tabular_modes_are_registered(self):
        for level in (3, 9, 19):
            codec = codec_by_id(f"tbl1-{level}")
            self.assertEqual(codec.implementation, "tbl1")
            self.assertEqual(codec.level, level)
        dense = codec_by_id("tbl1-dense")
        self.assertEqual(dense.implementation, "tbl1-dense")

    def test_tabular_worker_roundtrips_automatic_delimiter(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.table"
            encoded = root / "encoded.tbl1"
            restored = root / "restored.table"
            source.write_bytes(b"time;value\n" + b"1;2\n" * 1000)
            compression = run("tbl1-3", "compress", source, encoded)
            decompression = run("tbl1-3", "decompress", encoded, restored)
            self.assertEqual(restored.read_bytes(), source.read_bytes())
            self.assertIn(
                compression["selected_backend"],
                {"column-transpose+zstd", "direct-zstd"},
            )
            self.assertEqual(compression["delimiter"], ord(";"))
            self.assertEqual(compression["transform_engine"], "rust")
            self.assertEqual(decompression["selected_backend"], "tbl1-decode")

    def test_external_versions_are_probed_once_per_executable(self):
        codecs = [codec_by_id("zstd-1"), codec_by_id("zstd-3")]
        completed = subprocess.CompletedProcess(
            [codecs[0].executable, "--version"], 0, "zstd test version\n", ""
        )
        with patch("compresslab.codecs.subprocess.run", return_value=completed) as run:
            probed = probe_codec_versions(codecs)
        self.assertEqual(run.call_count, 1)
        self.assertEqual([codec.version for codec in probed], ["zstd test version"] * 2)


if __name__ == "__main__":
    unittest.main()
