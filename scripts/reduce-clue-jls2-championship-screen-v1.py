#!/usr/bin/env python3
"""Frozen one-shot decision reducer for the CLUE-LDS JLS2 championship screen.

This module answers exactly one prospective question with integer arithmetic:
"On two fresh, previously unopened CLUE-LDS temporal ranges, is JLS2 a public
championship contender against Kanzi-max and ZPAQ -method 54 (and the standard
roster)?" It reads no corpus data; it is a pure function of a score bundle that
the benchmark runner produces at execution time.

Contender rule (frozen NOW, never re-tuned after acquisition):

  (a) JLS2 aggregate complete bytes * 100 <= 95 * strongest, where `strongest`
      is the smallest aggregate complete bytes among the frozen eligible codecs
      that produced a VALID execution. The operator is `<=`: byte-ratio equality
      (candidate exactly 95% of strongest, i.e. exactly 5% smaller) SATISFIES the
      condition and is therefore a contender. See `meets_contender_margin`.
  (b) Per family and per item, JLS2 is the smallest eligible complete archive AND
      clears the same integer 5% margin (the #109 frozen regression rules).
  (c) Every JLS2 gate passes (exactness, determinism, corruption rejection,
      512 MiB standalone decode RSS, accounting, identity, and the v2 speed
      gates).

Tool-failure discipline: a codec that crashes, times out, or mis-restores is
classified `invalid-tool-failure`. It is excluded from `strongest` and is never
counted as a JLS2 win or as beating JLS2. Kanzi-max and ZPAQ -m54 may never be
silently omitted: if either is invalid, the screen cannot be a clean contender
and the reducer records the failure explicitly. -method 510 is contextual only
and never enters the eligible comparison.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


# Integer contender margin: candidate must be at least 5% smaller than the
# strongest eligible valid opponent. Frozen as 95/100; equality passes the <=.
CONTENDER_NUMERATOR = 95
CONTENDER_DENOMINATOR = 100

# Frozen eligible byte-comparison roster (codec_ids match the #109 roster).
# Kanzi-max and ZPAQ -m54 are eligible byte opponents regardless of their own
# decode RSS or speed; those are reported transparently. Only JLS2 carries the
# 512 MiB product decode-RSS cap. -method 510 and zstd --long=31 are contextual.
ELIGIBLE_OPPONENT_CODEC_IDS = (
    "kanzi-max",
    "zpaq-5-m54",
    "brotli-11",
    "zstd-22",
    "xz-lzma2-9e",
    "7zip-9",
    "pbc-only",
)

# Research opponents that answer the championship question by name; neither may
# be quietly omitted from a contender claim.
REQUIRED_RESEARCH_OPPONENT_CODEC_IDS = ("kanzi-max", "zpaq-5-m54")

CONTEXTUAL_CODEC_IDS = ("zpaq-5-m510", "zstd-22-long31")

# An execution is valid only when every one of these flags is true.
EXECUTION_VALIDITY_FLAGS = (
    "finished_within_wall",
    "exact_roundtrip",
    "order_preserved",
    "timezone_preserved",
    "deterministic_output",
)

EQUALITY_SEMANTICS = (
    "Integer rule candidate_bytes * 100 <= 95 * strongest_bytes. The operator is "
    "<=, so byte-ratio equality (candidate exactly 95% of strongest, i.e. exactly "
    "5% smaller) PASSES and is a contender. One byte above the line is not."
)


def meets_contender_margin(candidate_bytes: int, reference_bytes: int) -> bool:
    """Return True iff candidate is at least 5% smaller than reference.

    Integer-only. Equality (candidate_bytes * 100 == 95 * reference_bytes)
    satisfies the `<=` and is a contender.
    """
    candidate_bytes = int(candidate_bytes)
    reference_bytes = int(reference_bytes)
    if reference_bytes <= 0:
        raise ValueError("reference byte count must be positive")
    if candidate_bytes < 0:
        raise ValueError("candidate byte count must be non-negative")
    return candidate_bytes * CONTENDER_DENOMINATOR <= CONTENDER_NUMERATOR * reference_bytes


def classify_execution(execution: dict[str, Any] | None) -> str:
    """Classify a codec execution as 'valid' or 'invalid-tool-failure'.

    A missing execution (an unavailable tool that never ran) is an
    'invalid-tool-failure' for comparison purposes: it is excluded from the
    eligible minimum and is never a win or a loss.
    """
    if not execution:
        return "invalid-tool-failure"
    for flag in EXECUTION_VALIDITY_FLAGS:
        if not bool(execution.get(flag)):
            return "invalid-tool-failure"
    return "valid"


def _strongest(rows: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    candidates = [row for row in rows if row.get(key) is not None]
    if not candidates:
        return None
    return min(candidates, key=lambda row: int(row[key]))


def reduce_championship(bundle: dict[str, Any]) -> dict[str, Any]:
    """Apply the frozen contender rule to a score bundle and return a decision."""
    candidate = bundle["candidate"]
    candidate_aggregate = int(candidate["aggregate_complete_bytes"])
    candidate_family_bytes = {
        family: int(value)
        for family, value in candidate["family_complete_bytes"].items()
    }
    families = list(bundle["families"])
    gates = dict(candidate["gates"])
    candidate_gates_all_pass = bool(gates) and all(bool(v) for v in gates.values())

    opponent_rows: list[dict[str, Any]] = []
    for opponent in bundle["opponents"]:
        codec_id = opponent["codec_id"]
        eligibility_class = opponent["eligibility_class"]
        classification = classify_execution(opponent.get("execution"))
        opponent_rows.append(
            {
                "codec_id": codec_id,
                "eligibility_class": eligibility_class,
                "classification": classification,
                "aggregate_complete_bytes": opponent.get("aggregate_complete_bytes"),
                "family_complete_bytes": opponent.get("family_complete_bytes") or {},
            }
        )

    valid_eligible = [
        row
        for row in opponent_rows
        if row["eligibility_class"] == "eligible" and row["classification"] == "valid"
    ]

    required_valid = {
        codec_id: any(
            row["codec_id"] == codec_id and row["classification"] == "valid"
            for row in opponent_rows
        )
        for codec_id in REQUIRED_RESEARCH_OPPONENT_CODEC_IDS
    }
    required_research_opponents_valid = all(required_valid.values())

    strongest_aggregate = _strongest(valid_eligible, "aggregate_complete_bytes")
    if strongest_aggregate is not None:
        aggregate_reference = int(strongest_aggregate["aggregate_complete_bytes"])
        aggregate_smaller = candidate_aggregate < aggregate_reference
        aggregate_margin_ok = meets_contender_margin(
            candidate_aggregate, aggregate_reference
        )
        strongest_aggregate_codec = strongest_aggregate["codec_id"]
    else:
        aggregate_reference = None
        aggregate_smaller = False
        aggregate_margin_ok = False
        strongest_aggregate_codec = None

    family_decisions = []
    for family in families:
        family_rows = [
            {
                "codec_id": row["codec_id"],
                "family_complete_bytes": row["family_complete_bytes"].get(family),
            }
            for row in valid_eligible
        ]
        strongest_family = _strongest(family_rows, "family_complete_bytes")
        candidate_bytes = candidate_family_bytes.get(family)
        if strongest_family is None or candidate_bytes is None:
            family_decisions.append(
                {
                    "family": family,
                    "candidate_complete_bytes": candidate_bytes,
                    "strongest_eligible_codec": None,
                    "strongest_eligible_bytes": None,
                    "candidate_smaller": False,
                    "margin_ok": False,
                }
            )
            continue
        reference_bytes = int(strongest_family["family_complete_bytes"])
        family_decisions.append(
            {
                "family": family,
                "candidate_complete_bytes": int(candidate_bytes),
                "strongest_eligible_codec": strongest_family["codec_id"],
                "strongest_eligible_bytes": reference_bytes,
                "candidate_smaller": int(candidate_bytes) < reference_bytes,
                "margin_ok": meets_contender_margin(candidate_bytes, reference_bytes),
            }
        )

    all_families_smaller = bool(family_decisions) and all(
        row["candidate_smaller"] for row in family_decisions
    )
    all_families_margin_ok = bool(family_decisions) and all(
        row["margin_ok"] for row in family_decisions
    )

    contender = bool(
        candidate_gates_all_pass
        and required_research_opponents_valid
        and strongest_aggregate is not None
        and aggregate_smaller
        and aggregate_margin_ok
        and all_families_smaller
        and all_families_margin_ok
    )

    contextual = [
        row for row in opponent_rows if row["eligibility_class"] == "contextual"
    ]
    unavailable = [
        row for row in opponent_rows if row["eligibility_class"] == "unavailable"
    ]

    return {
        "schema_version": 1,
        "name": "clue-jls2-championship-screen-v1-decision",
        "result": "contender" if contender else "not_contender",
        "contender": contender,
        "equality_semantics": EQUALITY_SEMANTICS,
        "contender_margin": {
            "numerator": CONTENDER_NUMERATOR,
            "denominator": CONTENDER_DENOMINATOR,
        },
        "candidate_aggregate_complete_bytes": candidate_aggregate,
        "strongest_eligible_aggregate_codec": strongest_aggregate_codec,
        "strongest_eligible_aggregate_bytes": aggregate_reference,
        "aggregate_candidate_smaller": aggregate_smaller,
        "aggregate_margin_ok": aggregate_margin_ok,
        "candidate_gates_all_pass": candidate_gates_all_pass,
        "family_decisions": family_decisions,
        "required_research_opponents_valid": required_research_opponents_valid,
        "required_research_opponent_status": required_valid,
        "opponent_classifications": [
            {
                "codec_id": row["codec_id"],
                "eligibility_class": row["eligibility_class"],
                "classification": row["classification"],
            }
            for row in opponent_rows
        ],
        "contextual_codecs": [row["codec_id"] for row in contextual],
        "unavailable_codecs": [row["codec_id"] for row in unavailable],
        "claim_note": (
            "Best possible outcome is a public championship contender on the two "
            "named previously unopened CLUE-LDS temporal ranges. Not world-best, "
            "not a private holdout, not independently reproduced. Contextual and "
            "unavailable tools are never counted as beaten or as beating JLS2."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    decision = reduce_championship(bundle)
    encoded = json.dumps(decision, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        if args.output.exists():
            raise SystemExit("refusing to replace an existing championship decision")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if decision["contender"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
