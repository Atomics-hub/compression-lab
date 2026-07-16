import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
BENCHMARK = REPOSITORY / "scripts" / "benchmark-pbc-competitor.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PBCBenchmarkTests(unittest.TestCase):
    def test_complete_archive_accounting_and_roundtrip(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            pbc_repository = root / "pbc"
            pbc_repository.mkdir()
            license_path = pbc_repository / "LICENSE"
            license_path.write_text("test license\n", encoding="utf-8")
            binary = pbc_repository / "pbc"
            binary.write_text(
                textwrap.dedent(
                    f"""\
                    #!{sys.executable}
                    import shutil
                    import sys
                    from pathlib import Path

                    args = sys.argv[1:]
                    operation = args[0]
                    source = Path(args[args.index("-i") + 1])
                    pattern = Path(args[args.index("-p") + 1])
                    method = args[args.index("--compress-method") + 1]
                    if operation == "--train-pattern":
                        pattern.write_bytes(("pattern:" + method).encode())
                    else:
                        destination = Path(args[args.index("-o") + 1])
                        shutil.copyfile(source, destination)
                    """
                ),
                encoding="utf-8",
            )
            binary.chmod(0o755)

            subprocess.run(
                ["git", "init", "-q"],
                cwd=pbc_repository,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"],
                cwd=pbc_repository,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=pbc_repository,
                check=True,
            )
            subprocess.run(
                ["git", "remote", "add", "origin", "https://example.invalid/pbc"],
                cwd=pbc_repository,
                check=True,
            )
            subprocess.run(
                ["git", "add", "LICENSE", "pbc"],
                cwd=pbc_repository,
                check=True,
            )
            subprocess.run(
                ["git", "commit", "-q", "-m", "fixture"],
                cwd=pbc_repository,
                check=True,
            )
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=pbc_repository,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()

            source = root / "source.json"
            source.write_bytes(b'{"message":"one"}\n{"message":"two"}\n')
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "family": "fixture",
                                "path": str(source),
                                "size_bytes": source.stat().st_size,
                                "sha256": sha256(source),
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            accepted = root / "accepted.json"
            accepted.write_text(
                json.dumps(
                    {
                        "rows": [
                            {
                                "family": "fixture",
                                "encoded_bytes": 20,
                                "zstd9_bytes": 30,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            gates = root / "gates.json"
            gates.write_text(
                json.dumps(
                    {
                        "source": {
                            "commit": commit,
                            "license_sha256": sha256(license_path),
                        },
                        "settings": {
                            "methods": ["pbc_only"],
                            "pattern_size": 100,
                            "train_data_number": 2000,
                            "train_thread_num": 64,
                        },
                        "requirements": {
                            "expected_families": ["fixture"],
                            "minimum_repetitions": 1,
                            "minimum_training_repetitions": 1,
                            "maximum_record_bytes": 1048576,
                            "max_normalized_preflight_load_1m": 1000.0,
                            "require_clean_tracked_source": True,
                            "require_exact_source_commit": True,
                            "require_exact_license": True,
                            "require_deterministic_payload_for_fixed_pattern": True,
                            "require_byte_exact_roundtrip": True,
                            "require_complete_archive_accounting": True,
                        },
                        "claim_ceiling": "test only",
                    }
                ),
                encoding="utf-8",
            )
            output = root / "result.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(BENCHMARK),
                    "--pbc-binary",
                    str(binary),
                    "--pbc-repository",
                    str(pbc_repository),
                    "--manifest",
                    str(manifest),
                    "--accepted",
                    str(accepted),
                    "--gates",
                    str(gates),
                    "--output",
                    str(output),
                    "--repetitions",
                    "1",
                    "--training-repetitions",
                    "1",
                ],
                cwd=REPOSITORY,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            result = json.loads(output.read_text(encoding="utf-8"))
            row = result["rows"][0]
            self.assertTrue(result["passed"])
            self.assertTrue(row["roundtrip_verified"])
            self.assertEqual(
                row["archive_bytes"],
                row["pattern_bytes"] + row["payload_bytes"],
            )
            self.assertEqual(
                result["decision"]["primary"]["archive_bytes"],
                row["archive_bytes"],
            )


if __name__ == "__main__":
    unittest.main()
