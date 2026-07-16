import unittest
from types import SimpleNamespace
from unittest.mock import patch

from compresslab.worker import _cpu_time_ns, resource


class WorkerTelemetryTests(unittest.TestCase):
    def test_cpu_time_includes_worker_and_completed_children(self):
        if resource is None:
            self.skipTest("resource module is unavailable on this platform")
        own = SimpleNamespace(ru_utime=1.0, ru_stime=2.0)
        children = SimpleNamespace(ru_utime=3.0, ru_stime=4.0)

        def usage(scope):
            return own if scope == 0 else children

        with patch("compresslab.worker.resource.getrusage", side_effect=usage):
            self.assertEqual(_cpu_time_ns(), 10_000_000_000)


if __name__ == "__main__":
    unittest.main()
