from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT
    / "scripts"
    / "benchmark-jls2-context-reuse-inline-single-worker-a2.py"
)
PROTOCOL = (
    ROOT
    / "docs"
    / "benchmarks"
    / "2026-07-18-jls2-context-reuse-inline-single-worker-a2-protocol.md"
)
WORKFLOW = (
    ROOT
    / ".github"
    / "workflows"
    / "jls2-context-reuse-inline-single-worker-a2.yml"
)


def load_module():
    spec = importlib.util.spec_from_file_location("jls2_inline_worker_a2", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load inline-single-worker A2 benchmark")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def trial(
    variant: str,
    item_id: str,
    round_number: int,
    rate: float,
    rss: int,
) -> dict[str, object]:
    size = 1_000_000
    wall_ns = int(size / rate * 1000)
    return {
        "variant": variant,
        "item_id": item_id,
        "source_bytes": size,
        "wall_ns": wall_ns,
        "mbps": size / wall_ns * 1000.0,
        "peak_rss_bytes": rss,
        "round": round_number,
        "warmup": False,
        "exact": True,
    }


def paired_trials(
    module,
    *,
    stress_candidate_rss: int,
    clue_candidate_rss: int = 200,
) -> list[dict[str, object]]:
    items = ("clue-a", "clue-b", "clue-c", module.STRESS_ID)
    rows = []
    for round_number in range(1, module.ROUNDS + 1):
        for item_id in items:
            rows.append(trial("baseline", item_id, round_number, 300.0, 200))
            candidate_rss = (
                stress_candidate_rss
                if item_id == module.STRESS_ID
                else clue_candidate_rss
            )
            rows.append(
                trial("candidate", item_id, round_number, 295.0, candidate_rss)
            )
    return rows


class JLS2InlineSingleWorkerA2BenchmarkTests(unittest.TestCase):
    def test_frozen_a2_identity_and_exact_a1_baseline(self) -> None:
        module = load_module()
        self.assertEqual(
            module.BASELINE_COMMIT,
            "131547f35747cc0ff9dedbdef66d8a9516a7464f",
        )
        self.assertEqual(
            module.RESULT_NAME,
            "jls2-context-reuse-inline-single-worker-a2-development-v1",
        )
        self.assertEqual(module.ROUNDS, 7)
        self.assertEqual(module.STRESS_RECORDS, 21_800)
        self.assertEqual(module.STRESS_RSS_REDUCTION_MIN_PERCENT, 5.0)

    def test_a1_runner_and_schedule_contract_are_pinned(self) -> None:
        module = load_module()
        self.assertEqual(
            module.sha256_file(module.A1_RUNNER), module.A1_RUNNER_SHA256
        )
        for path, expected in module.FROZEN_SUPPORT_FILES.items():
            self.assertEqual(module.sha256_file(path), expected)
        item_ids = ["early", "middle", "late", module.STRESS_ID]
        self.assertEqual(
            module.schedule(item_ids, module.ROUNDS),
            module.A1.schedule(item_ids, module.A1.ROUNDS),
        )

    def test_summary_accepts_material_a2_memory_win(self) -> None:
        module = load_module()
        rows = paired_trials(module, stress_candidate_rss=190)

        summary = module.summarize(rows, module.ROUNDS)

        self.assertTrue(summary["passed"])
        self.assertTrue(
            summary["gates"]["stress_peak_rss_reduction_at_least_5_percent"]
        )
        self.assertNotIn(
            "stress_peak_rss_reduction_at_least_20_percent", summary["gates"]
        )
        self.assertEqual(
            set(summary["gates"]),
            {
                "all_exact",
                "candidate_peak_rss_at_or_below_448_mib",
                "stress_peak_rss_reduction_at_least_5_percent",
                "no_clue_family_peak_rss_regression",
                "candidate_median_throughput_at_least_95_percent_of_baseline",
                "all_candidate_item_medians_at_or_above_250_mbps",
                "all_candidate_rounds_at_or_above_225_mbps",
                "candidate_cv_at_or_below_20_percent",
            },
        )

    def test_summary_rejects_immaterial_stress_reduction(self) -> None:
        module = load_module()
        rows = paired_trials(module, stress_candidate_rss=191)

        summary = module.summarize(rows, module.ROUNDS)

        self.assertFalse(summary["passed"])
        self.assertFalse(
            summary["gates"]["stress_peak_rss_reduction_at_least_5_percent"]
        )

    def test_summary_rejects_any_clue_memory_regression(self) -> None:
        module = load_module()
        rows = paired_trials(
            module,
            stress_candidate_rss=190,
            clue_candidate_rss=201,
        )

        summary = module.summarize(rows, module.ROUNDS)

        self.assertFalse(summary["passed"])
        self.assertFalse(summary["gates"]["no_clue_family_peak_rss_regression"])

    def test_protocol_and_workflow_keep_the_a2_boundary_unambiguous(self) -> None:
        protocol = PROTOCOL.read_text(encoding="utf-8")
        workflow = WORKFLOW.read_text(encoding="utf-8")
        baseline = "131547f35747cc0ff9dedbdef66d8a9516a7464f"

        self.assertIn(baseline, protocol)
        self.assertIn(baseline, workflow)
        self.assertIn("when `workers == 1`", protocol)
        self.assertIn("outer segment workers", protocol)
        self.assertIn("private holdout remains sealed", protocol)
        self.assertIn(
            "neither experimental change replaces the pre-A1 product",
            protocol,
        )
        self.assertIn(
            "jls2-context-reuse-inline-single-worker-a2-${{ github.run_id }}",
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
