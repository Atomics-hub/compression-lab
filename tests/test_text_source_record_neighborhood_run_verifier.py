import copy
import importlib.util
import json
from pathlib import Path
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts" / "verify-text-source-record-neighborhood-run.py"
PUBLIC_EVIDENCE = (
    REPOSITORY
    / "runs"
    / "text-source-record-neighborhood-screen-v1"
    / "publication"
    / "evidence.json"
)
SPEC = importlib.util.spec_from_file_location("record_neighborhood_run_verifier", SCRIPT)
if SPEC is None or SPEC.loader is None:  # pragma: no cover
    raise RuntimeError(f"cannot import {SCRIPT}")
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)


class RecordNeighborhoodRunVerifierTests(unittest.TestCase):
    def test_public_receipt_has_the_exact_frozen_process_chain(self) -> None:
        evidence = json.loads(PUBLIC_EVIDENCE.read_bytes())
        receipt = evidence["trials"][0]["receipt"]
        item = {
            "baseline_bytes": receipt["baseline_bytes"],
            "id": receipt["item_id"],
            "path": str(
                REPOSITORY
                / "corpora"
                / "text-source-development-v1"
                / next(
                    value.split("$REPOSITORY/", 1)[1]
                    for value in receipt["processes"]["compression"][0]["command"]
                    if value.startswith("$REPOSITORY/") and "corpora/" in value
                ).split("corpora/text-source-development-v1/", 1)[1]
            ),
            "source_bytes": receipt["source_bytes"],
            "source_sha256": receipt["source_sha256"],
            "structural_control_bytes": receipt["structural_control_bytes"],
            "track": receipt["track"],
        }
        verifier.validate_receipt(
            receipt,
            bindings=receipt["bindings"],
            item=item,
            repetition=receipt["repetition"],
            kanzi=verifier.RUNNER.DEFAULT_KANZI,
            transform=verifier.RUNNER.DEFAULT_TRANSFORM,
        )

        edited = copy.deepcopy(receipt)
        edited["processes"]["compression"][1]["command"].append("--level=8")
        with self.assertRaisesRegex(ValueError, "process receipt differs"):
            verifier.validate_receipt(
                edited,
                bindings=edited["bindings"],
                item=item,
                repetition=edited["repetition"],
                kanzi=verifier.RUNNER.DEFAULT_KANZI,
                transform=verifier.RUNNER.DEFAULT_TRANSFORM,
            )


if __name__ == "__main__":
    unittest.main()
