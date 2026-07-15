import subprocess
import unittest
from unittest.mock import patch

from compresslab.codecs import codec_by_id, probe_codec_versions


class CodecProbeTests(unittest.TestCase):
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
