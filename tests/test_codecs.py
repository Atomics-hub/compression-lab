import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from compresslab.codecs import codec_by_id, probe_codec_versions
from compresslab.worker import run


class CodecProbeTests(unittest.TestCase):
    def test_jls2_worker_is_registered_streaming_and_exact(self):
        codec = codec_by_id("jls2")
        self.assertEqual(codec.implementation, "jls2")
        self.assertEqual(codec.version, "stream-jls2-v1-16m-c2")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.jsonl"
            encoded = root / "encoded.jls2"
            restored = root / "restored.jsonl"
            source.write_bytes(
                b'{"id":1,"kind":"alpha","params":{"value":100}}\n' * 1000
            )
            compression = run("jls2", "compress", source, encoded)
            decompression = run("jls2", "decompress", encoded, restored)
            self.assertEqual(restored.read_bytes(), source.read_bytes())
            self.assertEqual(compression["selected_backend"], "jls2")
            self.assertEqual(compression["segment_count"], 1)
            self.assertEqual(compression["direct_fallback_compared_segments"], 1)
            self.assertEqual(decompression["selected_backend"], "jls2-decode")

    def test_tabular_modes_are_registered(self):
        for level in (3, 9, 19):
            codec = codec_by_id(f"tbl1-{level}")
            self.assertEqual(codec.implementation, "tbl1")
            self.assertEqual(codec.level, level)
        dense = codec_by_id("tbl1-dense")
        self.assertEqual(dense.implementation, "tbl1-dense")
        stream = codec_by_id("tbl1-stream-dense")
        self.assertEqual(stream.implementation, "tbl1-stream-dense")

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

    def test_tabular_stream_worker_roundtrips_without_whole_file_api(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv"
            encoded = root / "encoded.tbs1"
            restored = root / "restored.csv"
            source.write_bytes(b"kind,value\n" + b"alpha,100\n" * 10000)
            compression = run("tbl1-stream-dense", "compress", source, encoded)
            decompression = run("tbl1-stream-dense", "decompress", encoded, restored)
            self.assertEqual(restored.read_bytes(), source.read_bytes())
            self.assertEqual(compression["segment_count"], 1)
            self.assertEqual(compression["stream_segment_size"], 16 * 1024 * 1024)
            self.assertEqual(compression["stream_concurrency"], 2)
            self.assertEqual(decompression["selected_backend"], "tbl1-stream-decode")

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
