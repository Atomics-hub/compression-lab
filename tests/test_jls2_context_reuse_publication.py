from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "publish-jls2-context-reuse.py"
SPEC = importlib.util.spec_from_file_location("jls2_context_publication", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
PUBLICATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PUBLICATION)

BASELINE_BINARY_SHA256 = "a" * 64
CANDIDATE_BINARY_SHA256 = "b" * 64
CANDIDATE_COMMIT = "c" * 40
HOST_PLATFORM = "Linux-fixture-x86_64"
RUN_ID = 123456789


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def fixture_results(*, passing: bool = True) -> dict[str, object]:
    binaries = {
        "baseline": {
            "path": "/opt/fixture/baseline/compression-lab",
            "sha256": BASELINE_BINARY_SHA256,
        },
        "candidate": {
            "path": "/opt/fixture/candidate/compression-lab",
            "sha256": CANDIDATE_BINARY_SHA256,
        },
    }
    item_metadata = {
        item_id: {
            "source_bytes": 1_000_000 + index * 10_000,
            "source_sha256": digest(f"source:{item_id}"),
            "encoded_bytes": 10_000 + index * 100,
            "encoded_sha256": digest(f"frame:{item_id}"),
            "frame": f"/fixtures/{item_id}.jls2",
        }
        for index, item_id in enumerate(PUBLICATION.EXPECTED_ITEM_IDS)
    }
    trials: list[dict[str, object]] = []

    def append_round(
        round_number: int, rows: list[tuple[str, str]], *, warmup: bool
    ) -> None:
        for sequence, (item_id, variant) in enumerate(rows):
            metadata = item_metadata[item_id]
            source_bytes = int(metadata["source_bytes"])
            target_mbps = 300.0 if variant == "baseline" else 297.0
            wall_ns = round(source_bytes / target_mbps * 1000.0) + sequence
            if item_id == PUBLICATION.FROZEN_BENCHMARK.STRESS_ID:
                baseline_rss = 200 * 1024 * 1024
                candidate_rss = (150 if passing else 170) * 1024 * 1024
            else:
                baseline_rss = 180 * 1024 * 1024
                candidate_rss = 175 * 1024 * 1024
            destination = (
                f"/tmp/{round_number}-{sequence}-{item_id}-{variant}.restored"
            )
            trials.append(
                {
                    "variant": variant,
                    "item_id": item_id,
                    "source_bytes": source_bytes,
                    "source_sha256": metadata["source_sha256"],
                    "encoded_bytes": metadata["encoded_bytes"],
                    "encoded_sha256": metadata["encoded_sha256"],
                    "command": [
                        binaries[variant]["path"],
                        "decompress",
                        metadata["frame"],
                        "-o",
                        destination,
                        "--force",
                    ],
                    "wall_ns": wall_ns,
                    "mbps": source_bytes / wall_ns * 1000.0,
                    "peak_rss_bytes": (
                        baseline_rss if variant == "baseline" else candidate_rss
                    ),
                    "returncode": 0,
                    "stdout": "",
                    "stderr": "",
                    "exact": True,
                    "round": round_number,
                    "warmup": warmup,
                }
            )

    item_ids = list(PUBLICATION.EXPECTED_ITEM_IDS)
    append_round(
        0,
        [
            (item_id, variant)
            for item_id in item_ids
            for variant in PUBLICATION.FROZEN_BENCHMARK.VARIANTS
        ],
        warmup=True,
    )
    measured_schedule = PUBLICATION.FROZEN_BENCHMARK.schedule(
        item_ids, PUBLICATION.FROZEN_BENCHMARK.ROUNDS
    )
    for round_number, rows in enumerate(measured_schedule, start=1):
        append_round(round_number, rows, warmup=False)
    summary = PUBLICATION.FROZEN_BENCHMARK.summarize(
        trials, PUBLICATION.FROZEN_BENCHMARK.ROUNDS
    )
    return {
        "schema_version": 1,
        "name": PUBLICATION.EXPECTED_RESULT_NAME,
        "claim_scope": PUBLICATION.EXPECTED_CLAIM_SCOPE,
        "baseline_commit": PUBLICATION.FROZEN_BENCHMARK.BASELINE_COMMIT,
        "candidate": {"commit": CANDIDATE_COMMIT, "dirty": False},
        "created_at_epoch_seconds": 1_750_000_000,
        "host": {
            "platform": HOST_PLATFORM,
            "python": "3.12.9",
            "logical_cpus": 4,
            "load_average_after": [0.1, 0.2, 0.3],
        },
        "binaries": binaries,
        "settings": {
            "rounds": PUBLICATION.FROZEN_BENCHMARK.ROUNDS,
            "warmups": 1,
            "stress_id": PUBLICATION.FROZEN_BENCHMARK.STRESS_ID,
            "stress_records": PUBLICATION.FROZEN_BENCHMARK.STRESS_RECORDS,
        },
        "trials": trials,
        "summary": summary,
        "claim_ceiling": PUBLICATION.EXPECTED_RESULT_CLAIM_CEILING,
    }


class JLS2ContextReusePublicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)

    def write_inputs(
        self, results: dict[str, object]
    ) -> tuple[Path, Path, Path]:
        results_path = self.work / "results.json"
        provenance_path = self.work / "provenance.txt"
        log_path = self.work / "benchmark.log"
        results_path.write_text(json.dumps(results), encoding="utf-8")
        provenance_path.write_text("synthetic runner provenance\n", encoding="utf-8")
        log_path.write_text("synthetic benchmark log\n", encoding="utf-8")
        return results_path, provenance_path, log_path

    def publish(
        self, results: dict[str, object], *, conclusion: str
    ) -> tuple[Path, dict[str, object]]:
        results_path, provenance_path, log_path = self.write_inputs(results)
        output = self.work / "publication"
        receipt = PUBLICATION.publish(
            results_path=results_path,
            provenance_path=provenance_path,
            benchmark_log_path=log_path,
            output=output,
            candidate_commit=CANDIDATE_COMMIT,
            baseline_binary_sha256=BASELINE_BINARY_SHA256,
            candidate_binary_sha256=CANDIDATE_BINARY_SHA256,
            host_platform=HOST_PLATFORM,
            workflow_run_id=RUN_ID,
            workflow_run_attempt=2,
            workflow_run_url=(
                "https://github.com/Atomics-hub/compression-lab/actions/runs/"
                f"{RUN_ID}"
            ),
            workflow_run_conclusion=conclusion,
            artifact_id=987654321,
            artifact_name=f"jls2-context-reuse-{RUN_ID}",
            artifact_digest=f"sha256:{'d' * 64}",
        )
        return output, receipt

    def test_publishes_verified_pass_bundle(self) -> None:
        output, receipt = self.publish(fixture_results(), conclusion="success")

        self.assertEqual(
            {path.name for path in output.iterdir()},
            {
                "README.md",
                "benchmark.log",
                "comparison.json",
                "comparison.svg",
                "provenance.txt",
                "receipt.json",
                "results.json",
            },
        )
        comparison = json.loads(
            (output / "comparison.json").read_text(encoding="utf-8")
        )
        self.assertEqual(comparison["decision"], "passed")
        self.assertEqual(comparison["selected_variant"], "candidate")
        self.assertEqual(comparison["schedule"]["total_trials"], 64)
        self.assertTrue(
            all(
                row["same_frame_for_both_variants"]
                for row in comparison["frame_identities"]
            )
        )
        readme = (output / "README.md").read_text(encoding="utf-8")
        self.assertIn("3,523,721 bytes", readme)
        self.assertIn("immutable **no-pass**", readme)
        self.assertIn("621.3 MiB", readme)
        self.assertIn("512 MiB", readme)
        self.assertEqual(receipt["decision"], "passed")
        for name, expected in receipt["artifacts"].items():
            self.assertEqual(PUBLICATION.sha256_file(output / name), expected)

    def test_publishes_rejection_and_retains_baseline(self) -> None:
        output, receipt = self.publish(
            fixture_results(passing=False), conclusion="failure"
        )

        comparison = json.loads(
            (output / "comparison.json").read_text(encoding="utf-8")
        )
        self.assertEqual(comparison["decision"], "rejected")
        self.assertIsNone(comparison["selected_variant"])
        self.assertEqual(comparison["retained_variant"], "baseline")
        self.assertFalse(
            comparison["summary"]["gates"][
                "stress_peak_rss_reduction_at_least_20_percent"
            ]
        )
        self.assertIn(
            "baseline remains unchanged",
            (output / "README.md").read_text(encoding="utf-8"),
        )
        self.assertEqual(receipt["decision"], "rejected")

    def test_rejects_stored_summary_drift(self) -> None:
        results = fixture_results()
        results["summary"]["variants"][0]["peak_rss_bytes"] += 1

        with self.assertRaisesRegex(ValueError, "frozen benchmark recomputation"):
            self.publish(results, conclusion="success")

    def test_rejects_frame_identity_drift(self) -> None:
        results = fixture_results()
        trials = results["trials"]
        candidate = next(
            row
            for row in trials
            if row["variant"] == "candidate" and not row["warmup"]
        )
        candidate["encoded_sha256"] = digest("different frame")

        with self.assertRaisesRegex(ValueError, "same-frame identity drift"):
            self.publish(results, conclusion="success")

    def test_rejects_reordered_schedule(self) -> None:
        results = fixture_results()
        results["trials"][0], results["trials"][1] = (
            results["trials"][1],
            results["trials"][0],
        )

        with self.assertRaisesRegex(ValueError, "frozen schedule"):
            self.publish(results, conclusion="success")

    def test_rejects_raw_schema_extensions(self) -> None:
        results = fixture_results()
        results["unreviewed_extension"] = True

        with self.assertRaisesRegex(ValueError, "unexpected fields"):
            self.publish(results, conclusion="success")

    def test_metadata_must_match_raw_result_and_decision(self) -> None:
        results = copy.deepcopy(fixture_results())
        results["candidate"]["commit"] = "e" * 40
        with self.assertRaisesRegex(ValueError, "candidate commit"):
            self.publish(results, conclusion="success")

        with self.assertRaisesRegex(ValueError, "conclusion must be success"):
            self.publish(fixture_results(), conclusion="failure")


if __name__ == "__main__":
    unittest.main()
