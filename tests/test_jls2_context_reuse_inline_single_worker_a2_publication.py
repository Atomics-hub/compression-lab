from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT
    / "scripts"
    / "publish-jls2-context-reuse-inline-single-worker-a2.py"
)
SPEC = importlib.util.spec_from_file_location("jls2_a2_publication", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
PUBLICATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PUBLICATION)

BASELINE_BINARY_SHA256 = "a" * 64
CANDIDATE_BINARY_SHA256 = "b" * 64
CANDIDATE_COMMIT = "c" * 40
HOST_PLATFORM = "Linux-fixture-x86_64"
RUN_ID = PUBLICATION.EXPECTED_WORKFLOW_RUN_ID


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def fixture_results(*, passing: bool = True) -> dict[str, object]:
    a2 = PUBLICATION.A2
    binaries = {
        "baseline": {
            "path": "/opt/fixture/exact-a1/clab-jls2",
            "sha256": BASELINE_BINARY_SHA256,
        },
        "candidate": {
            "path": "/opt/fixture/combined-a1-a2/clab-jls2",
            "sha256": CANDIDATE_BINARY_SHA256,
        },
    }
    metadata = {
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
            item = metadata[item_id]
            source_bytes = int(item["source_bytes"])
            target_mbps = 300.0 if variant == "baseline" else 297.0
            wall_ns = round(source_bytes / target_mbps * 1000.0) + sequence
            if item_id == a2.STRESS_ID:
                baseline_rss = 200 * 1024 * 1024
                candidate_rss = (190 if passing else 191) * 1024 * 1024
            else:
                baseline_rss = 200 * 1024 * 1024
                candidate_rss = 195 * 1024 * 1024
            trials.append(
                {
                    "variant": variant,
                    "item_id": item_id,
                    "source_bytes": source_bytes,
                    "source_sha256": item["source_sha256"],
                    "encoded_bytes": item["encoded_bytes"],
                    "encoded_sha256": item["encoded_sha256"],
                    "command": [
                        binaries[variant]["path"],
                        "decompress",
                        item["frame"],
                        "-o",
                        f"/tmp/{round_number}-{sequence}-{item_id}-{variant}.restored",
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
            for variant in a2.VARIANTS
        ],
        warmup=True,
    )
    for round_number, rows in enumerate(
        a2.schedule(item_ids, a2.ROUNDS), start=1
    ):
        append_round(round_number, rows, warmup=False)
    support = {
        path.relative_to(ROOT).as_posix(): checksum
        for path, checksum in a2.FROZEN_SUPPORT_FILES.items()
    }
    summary = a2.summarize(trials, a2.ROUNDS)
    return {
        "schema_version": 1,
        "name": a2.RESULT_NAME,
        "ablation": "A1 reusable contexts plus inline execution when workers == 1",
        "claim_scope": a2.CLAIM_SCOPE,
        "baseline_commit": a2.BASELINE_COMMIT,
        "candidate": {"commit": CANDIDATE_COMMIT, "dirty": False},
        "created_at_epoch_seconds": 1_750_000_000,
        "host": {
            "platform": HOST_PLATFORM,
            "python": "3.12.9",
            "rustc": "rustc 1.96.0",
            "logical_cpus": 4,
            "load_average_after": [0.1, 0.2, 0.3],
        },
        "binaries": binaries,
        "settings": {
            "rounds": a2.ROUNDS,
            "warmups": 1,
            "stress_id": a2.STRESS_ID,
            "stress_records": a2.STRESS_RECORDS,
            "stress_rss_reduction_min_percent": a2.STRESS_RSS_REDUCTION_MIN_PERCENT,
            "a1_runner_sha256": a2.A1_RUNNER_SHA256,
            "frozen_support_sha256": support,
        },
        "trials": trials,
        "summary": summary,
        "claim_ceiling": a2.CLAIM_CEILING,
    }


class JLS2InlineSingleWorkerA2PublicationTests(unittest.TestCase):
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
        provenance_path.write_text("synthetic A2 provenance\n", encoding="utf-8")
        log_path.write_text("synthetic A2 benchmark log\n", encoding="utf-8")
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
            workflow_run_attempt=1,
            workflow_run_url=(
                "https://github.com/Atomics-hub/compression-lab/actions/runs/"
                f"{RUN_ID}"
            ),
            workflow_run_conclusion=conclusion,
            artifact_id=987654321,
            artifact_name=(
                f"jls2-context-reuse-inline-single-worker-a2-{RUN_ID}"
            ),
            artifact_digest=f"sha256:{'d' * 64}",
        )
        return output, receipt

    def test_publishes_strict_pass_bundle(self) -> None:
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
        self.assertEqual(
            comparison["product_decision"],
            "combined_a1_a2_candidate_retained_for_fresh_validation_only",
        )
        self.assertEqual(comparison["a1_baseline_commit"], PUBLICATION.A2.BASELINE_COMMIT)
        self.assertEqual(comparison["schedule"]["total_trials"], 64)
        self.assertTrue(
            all(
                row["same_frame_for_both_variants"]
                for row in comparison["frame_identities"]
            )
        )
        readme = (output / "README.md").read_text(encoding="utf-8")
        self.assertIn("retained only", readme)
        self.assertIn("separately frozen fresh validation gate", readme)
        self.assertIn("625.2 MiB", readme)
        self.assertIn("621.3 MiB", readme)
        self.assertIn("512 MiB", readme)
        self.assertEqual(receipt["decision"], "passed")
        for name, expected in receipt["artifacts"].items():
            self.assertEqual(PUBLICATION.COMMON.sha256_file(output / name), expected)

    def test_publishes_rejection_and_retains_pre_a1_product(self) -> None:
        output, receipt = self.publish(
            fixture_results(passing=False), conclusion="failure"
        )

        comparison = json.loads(
            (output / "comparison.json").read_text(encoding="utf-8")
        )
        self.assertEqual(comparison["decision"], "rejected")
        self.assertEqual(
            comparison["retained_product_commit"],
            PUBLICATION.PRE_A1_PRODUCT_BASELINE_COMMIT,
        )
        self.assertEqual(
            comparison["product_decision"], "pre_a1_product_baseline_retained"
        )
        readme = (output / "README.md").read_text(encoding="utf-8")
        self.assertIn("neither A1 nor A2 replaces", readme)
        self.assertIn(PUBLICATION.PRE_A1_PRODUCT_BASELINE_COMMIT, readme)
        self.assertEqual(receipt["decision"], "rejected")

    def test_rejects_summary_tampering(self) -> None:
        results = fixture_results()
        results["summary"]["passed"] = False

        with self.assertRaisesRegex(ValueError, "frozen recomputation"):
            self.publish(results, conclusion="success")

    def test_rejects_schedule_reordering(self) -> None:
        results = fixture_results()
        results["trials"][0], results["trials"][1] = (
            results["trials"][1],
            results["trials"][0],
        )

        with self.assertRaisesRegex(ValueError, "frozen 64-trial schedule"):
            self.publish(results, conclusion="success")

    def test_rejects_frame_identity_drift(self) -> None:
        results = fixture_results()
        candidate = next(
            row
            for row in results["trials"]
            if row["variant"] == "candidate" and not row["warmup"]
        )
        candidate["encoded_sha256"] = digest("different frame")

        with self.assertRaisesRegex(ValueError, "same-frame identity drift"):
            self.publish(results, conclusion="success")

    def test_rejects_schema_or_hosted_run_drift(self) -> None:
        results = fixture_results()
        results["unreviewed_extension"] = True
        with self.assertRaisesRegex(ValueError, "unexpected fields"):
            self.publish(results, conclusion="success")

        results = fixture_results()
        paths = self.write_inputs(results)
        with self.assertRaisesRegex(ValueError, "frozen hosted A2 run"):
            PUBLICATION.publish(
                results_path=paths[0],
                provenance_path=paths[1],
                benchmark_log_path=paths[2],
                output=self.work / "wrong-run",
                candidate_commit=CANDIDATE_COMMIT,
                baseline_binary_sha256=BASELINE_BINARY_SHA256,
                candidate_binary_sha256=CANDIDATE_BINARY_SHA256,
                host_platform=HOST_PLATFORM,
                workflow_run_id=RUN_ID + 1,
                workflow_run_attempt=1,
                workflow_run_url="https://github.com/Atomics-hub/compression-lab/actions/runs/1",
                workflow_run_conclusion="success",
                artifact_id=1,
                artifact_name="wrong",
                artifact_digest=f"sha256:{'d' * 64}",
            )


if __name__ == "__main__":
    unittest.main()
