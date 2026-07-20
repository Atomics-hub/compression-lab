from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from tests.test_text_source_baseline_publication import (
    MODULE as BASELINE_PUBLICATION,
    fixture as baseline_fixture,
    write_trial_receipts,
)


REPOSITORY = Path(__file__).resolve().parents[1]
PUBLISH_SCRIPT = REPOSITORY / "scripts" / "publish-text-source-research-ceiling.py"
VERIFY_SCRIPT = (
    REPOSITORY / "scripts" / "verify-text-source-research-ceiling-publication.py"
)
CONFIG = REPOSITORY / "config" / "text-source-gates-v1.json"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PUBLISH = load("research_ceiling_publication", PUBLISH_SCRIPT)
VERIFY = load("research_ceiling_publication_verifier", VERIFY_SCRIPT)


class TextSourceResearchCeilingPublicationTests(unittest.TestCase):
    def test_failed_nncp_portability_is_not_labeled_merely_pending(self) -> None:
        row = {
            "profile_id": PUBLISH.AGGREGATE.NNCP_PROFILE,
            "execution_status": "measured_exact_deterministic",
            "complete": True,
            "deterministic": True,
            "formal_ceiling_admitted": False,
            "second_host_decode_status": "failed",
        }
        self.assertEqual(
            PUBLISH.research_status([row]), "failed_second_host_decode"
        )
        row["second_host_decode_status"] = "pending"
        self.assertEqual(
            PUBLISH.research_status([row]), "pending_second_host_decode"
        )

    def prepare(self, root: Path):
        baseline_results = baseline_fixture()
        baseline_results_path = root / "baseline-private" / "results.json"
        baseline_results_path.parent.mkdir()
        baseline_results_path.write_bytes(BASELINE_PUBLICATION.json_bytes(baseline_results))
        write_trial_receipts(baseline_results_path.parent, baseline_results)
        baseline_publication = root / "baseline-publication"
        BASELINE_PUBLICATION.publish(baseline_results_path, baseline_publication)
        baseline_comparison = PUBLISH.read_canonical_json(
            baseline_publication / "comparison.json"
        )

        config_raw = CONFIG.read_bytes()
        plan = PUBLISH.AGGREGATE.RUNNER.PLANNER.build_plan(
            json.loads(config_raw),
            baseline_results,
            config_sha256=hashlib.sha256(config_raw).hexdigest(),
            baseline_sha256=baseline_comparison["results_sha256"],
            repository_commit="c" * 40,
        )
        plan_path = root / "plan.json"
        plan_path.write_bytes(PUBLISH.json_bytes(plan))
        tasks = []
        for index, task in enumerate(plan["tasks"]):
            formal = task["formal_ceiling_eligible"]
            tasks.append(
                {
                    "task_id": task["task_id"],
                    "profile_id": task["profile_id"],
                    "codec_id": task["codec_id"],
                    "item_id": task["item_id"],
                    "track": task["track"],
                    "formal_ceiling_eligible": formal,
                    "source_bytes": task["source_bytes"],
                    "measured_repetitions": 2,
                    "complete": True,
                    "deterministic": True,
                    "complete_artifact_bytes": task["source_bytes"] // 3 + index,
                    "payload_sha256": f"{index + 1:064x}",
                    "exact_roundtrip": True,
                    "portability_status": (
                        "verified_second_host_decode"
                        if task["profile_id"] == PUBLISH.AGGREGATE.NNCP_PROFILE
                        else "not_required_by_research_protocol"
                    ),
                    "formal_ceiling_admitted": formal,
                    "execution_status": "measured_exact_deterministic",
                    "axiom_outcome": "baseline_measurement_only",
                    "compression_wall_ns_median": 1_000_000 + index,
                    "decompression_wall_ns_median": 500_000 + index,
                    "compression_cpu_ns_median": 900_000 + index,
                    "decompression_cpu_ns_median": 450_000 + index,
                    "compression_peak_rss_bytes": (100 + index) * 1024**2,
                    "decompression_peak_rss_bytes": (80 + index) * 1024**2,
                    "host_id": f"fixture-{task['host_class']}",
                    "host_class": task["host_class"],
                    "runner_comparability": (
                        "size is cross-host comparable; speed and RSS are host-scoped"
                    ),
                    "second_host_decode_status": (
                        "exact"
                        if task["profile_id"] == PUBLISH.AGGREGATE.NNCP_PROFILE
                        else "not_required"
                    ),
                    "second_host_decode_wall_ns": (
                        300_000
                        if task["profile_id"] == PUBLISH.AGGREGATE.NNCP_PROFILE
                        else None
                    ),
                    "second_host_decode_cpu_ns": (
                        250_000
                        if task["profile_id"] == PUBLISH.AGGREGATE.NNCP_PROFILE
                        else None
                    ),
                    "second_host_decode_peak_rss_bytes": (
                        120 * 1024**2
                        if task["profile_id"] == PUBLISH.AGGREGATE.NNCP_PROFILE
                        else None
                    ),
                }
            )
        aggregate = {
            "schema_version": 1,
            "name": "text-source-research-ceiling-aggregate-v1",
            "completed": True,
            "bindings": {
                "plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
                "baseline_results_sha256": baseline_comparison["results_sha256"],
                "corpus_manifest_sha256": plan["bindings"][
                    "corpus_manifest_sha256"
                ],
                "repository_commit": plan["bindings"]["repository_commit"],
            },
            "host_runs": [],
            "second_host_decode": {
                "all_nncp_second_host_decodes_exact": True,
                "formal_nncp_ceiling_admitted": True,
                "axiom_wins": 0,
            },
            "trial_count": 105,
            "task_count": 35,
            "formal_task_count": 28,
            "tasks": tasks,
            "all_formal_ceiling_tasks_admitted": True,
            "research_ceiling_status": "formal_complete",
            "validation_status": "sealed and unaccessed",
            "private_holdout_status": "sealed and unaccessed",
            "axiom_wins": 0,
            "claim_ceiling": "fixture raw aggregate",
        }
        aggregate_path = root / "aggregate.json"
        aggregate_path.write_bytes(PUBLISH.json_bytes(aggregate))
        return plan_path, aggregate_path, baseline_publication

    def test_bundle_reconstructs_every_row_and_keeps_axiom_untested(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            plan, aggregate, baseline = self.prepare(root)
            output = root / "publication"
            PUBLISH.publish(
                plan_path=plan,
                aggregate_path=aggregate,
                baseline_publication=baseline,
                output=output,
            )
            verified = VERIFY.verify(output, baseline)
            self.assertTrue(verified["verified"])
            self.assertTrue(verified["research_ceiling_complete"])
            self.assertEqual(verified["axiom_wins"], 0)
            comparison = PUBLISH.read_canonical_json(output / "comparison.json")
            self.assertEqual(len(comparison["tracks"]), 2)
            for track in comparison["tracks"]:
                self.assertEqual(len(track["rows"]), 21)
                axiom = track["rows"][-1]
                self.assertEqual(axiom["execution_status"], "untested")
                self.assertEqual(axiom["axiom_beats_this_row"], "untested")
                screen = next(
                    row
                    for row in track["rows"]
                    if row["row_id"] == "paq8px-11L-local-screen"
                )
                self.assertFalse(screen["formal_ratio_eligible"])
                self.assertEqual(screen["execution_status"], "measured_context_only")

            comparison["integrity"]["axiom_wins"] = 1
            (output / "comparison.json").write_bytes(PUBLISH.json_bytes(comparison))
            with self.assertRaisesRegex(ValueError, "artifact digest differs"):
                VERIFY.verify(output, baseline)

    def test_publication_destination_is_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            plan, aggregate, baseline = self.prepare(root)
            output = root / "publication"
            PUBLISH.publish(
                plan_path=plan,
                aggregate_path=aggregate,
                baseline_publication=baseline,
                output=output,
            )
            PUBLISH.publish(
                plan_path=plan,
                aggregate_path=aggregate,
                baseline_publication=baseline,
                output=output,
            )
            (output / "README.md").write_text("tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "differing artifact"):
                PUBLISH.publish(
                    plan_path=plan,
                    aggregate_path=aggregate,
                    baseline_publication=baseline,
                    output=output,
                )

    def test_verifier_rejects_a_rewritten_receipt_schema(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            plan, aggregate, baseline = self.prepare(root)
            output = root / "publication"
            PUBLISH.publish(
                plan_path=plan,
                aggregate_path=aggregate,
                baseline_publication=baseline,
                output=output,
            )
            receipt_path = output / "receipt.json"
            receipt = json.loads(receipt_path.read_bytes())
            receipt["unbound_note"] = "not part of the frozen receipt"
            receipt_path.write_bytes(PUBLISH.json_bytes(receipt))
            with self.assertRaisesRegex(ValueError, "receipt does not reconstruct"):
                VERIFY.verify(output, baseline)


if __name__ == "__main__":
    unittest.main()
