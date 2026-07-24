#!/usr/bin/env python3
"""Frozen one-shot decision reducer for the CLUE-LDS JLS2 championship screen.

This module answers exactly one prospective question with integer arithmetic:
"On two fresh, previously unopened CLUE-LDS temporal ranges, is JLS2 a public
championship contender against Kanzi-max and ZPAQ -method 54 (and the standard
roster)?" It reads no corpus data; it is a pure function of a score bundle that
the benchmark runner produces at execution time.

Decision rule (governed by Tom's 2026-07-25 owner dispatch, which supersedes the
#109 prospective roster for THIS screen; #109 is not modified). Frozen NOW, never
re-tuned after acquisition:

  (a) AGGREGATE margin. `JLS2 aggregate complete bytes * 100 <= 95 * strongest`,
      where `strongest` is the smallest aggregate complete bytes among the frozen
      eligible codecs that produced a VALID execution on EVERY family. The
      operator is `<=`: byte-ratio equality (candidate exactly 95% of strongest,
      i.e. exactly 5% smaller) SATISFIES the condition and is a contender. See
      `meets_contender_margin`.
  (b) PER FAMILY and PER ITEM: JLS2 must WIN OUTRIGHT. On each family JLS2's
      complete bytes must be STRICTLY smaller than every eligible codec that
      produced a valid execution on that family. Allowed regression is zero bytes;
      equality is NOT a win. There is NO separate per-family 5% margin (Tom's
      dispatch reassigns the #109 5% margin to the aggregate only).
  (c) Every JLS2 gate passes (exactness, determinism, corruption rejection,
      512 MiB standalone decode RSS, accounting, identity, and the v2 speed
      gates).
  (d) Kanzi-max and ZPAQ -m54 both produced a valid execution on every family.

Tool-failure discipline (per item): a codec that crashes, times out, or
mis-restores on an item is `invalid-tool-failure` for THAT item. It is excluded
from the strongest computation on that family (and from the aggregate, which
requires validity on every family) and is never counted as a JLS2 win or as
beating JLS2; a valid result on another item still stands. Kanzi-max and ZPAQ -m54
may never be silently omitted: if either is not valid on every family, the screen
cannot be a clean contender and the reducer records the failure. -method 510 is
contextual only and never enters the eligible comparison.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


# Integer contender margin for the AGGREGATE: JLS2 must be at least 5% smaller
# than the strongest eligible valid opponent aggregate. Frozen as 95/100; equality
# passes the <=.
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

# A per-item execution is valid only when every one of these flags is true.
EXECUTION_VALIDITY_FLAGS = (
    "finished_within_wall",
    "exact_roundtrip",
    "order_preserved",
    "timezone_preserved",
    "deterministic_output",
)

EQUALITY_SEMANTICS = (
    "Aggregate rule candidate_bytes * 100 <= 95 * strongest_bytes. The operator is "
    "<=, so aggregate byte-ratio equality (candidate exactly 95% of strongest, i.e. "
    "exactly 5% smaller) PASSES and is a contender. Per family and per item JLS2 "
    "must WIN OUTRIGHT: strictly smaller than every eligible valid opponent, "
    "allowed regression zero bytes, equality is NOT a win."
)


def meets_contender_margin(candidate_bytes: int, reference_bytes: int) -> bool:
    """Return True iff candidate is at least 5% smaller than reference (aggregate).

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
    """Classify a per-item codec execution as 'valid' or 'invalid-tool-failure'.

    A missing execution (an item that never ran or produced no output) is an
    'invalid-tool-failure' for that item: excluded from the eligible minimum,
    never a win or a loss.
    """
    if not execution:
        return "invalid-tool-failure"
    for flag in EXECUTION_VALIDITY_FLAGS:
        if not bool(execution.get(flag)):
            return "invalid-tool-failure"
    return "valid"


def _item_valid(item: dict[str, Any] | None) -> bool:
    if not item:
        return False
    if item.get("complete_bytes") is None:
        return False
    return classify_execution(item.get("execution")) == "valid"


def _strongest(rows: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    candidates = [row for row in rows if row.get(key) is not None]
    if not candidates:
        return None
    return min(candidates, key=lambda row: int(row[key]))


def reduce_championship(bundle: dict[str, Any]) -> dict[str, Any]:
    """Apply the frozen decision rule to a score bundle and return a decision."""
    candidate = bundle["candidate"]
    candidate_aggregate = int(candidate["aggregate_complete_bytes"])
    candidate_family_bytes = {
        family: int(value)
        for family, value in candidate["family_complete_bytes"].items()
    }
    families = list(bundle["families"])
    gates = dict(candidate["gates"])
    candidate_gates_all_pass = bool(gates) and all(bool(v) for v in gates.values())

    # Resolve every opponent to per-family validity and an aggregate that is only
    # valid when the opponent is valid on every family.
    opponent_rows: list[dict[str, Any]] = []
    for opponent in bundle["opponents"]:
        items = opponent.get("items", {}) or {}
        per_family = {}
        for family in families:
            item = items.get(family)
            valid = _item_valid(item)
            per_family[family] = {
                "complete_bytes": (
                    int(item["complete_bytes"])
                    if item and item.get("complete_bytes") is not None
                    else None
                ),
                "valid": valid,
                "classification": "valid" if valid else "invalid-tool-failure",
            }
        aggregate_valid = all(per_family[family]["valid"] for family in families)
        aggregate_bytes = (
            sum(per_family[family]["complete_bytes"] for family in families)
            if aggregate_valid
            else None
        )
        opponent_rows.append(
            {
                "codec_id": opponent["codec_id"],
                "eligibility_class": opponent["eligibility_class"],
                "per_family": per_family,
                "aggregate_valid": aggregate_valid,
                "aggregate_complete_bytes": aggregate_bytes,
            }
        )

    required_valid = {
        codec_id: any(
            row["codec_id"] == codec_id and row["aggregate_valid"]
            for row in opponent_rows
        )
        for codec_id in REQUIRED_RESEARCH_OPPONENT_CODEC_IDS
    }
    required_research_opponents_valid = all(required_valid.values())

    # AGGREGATE: strongest among eligible opponents valid on every family.
    aggregate_pool = [
        {"codec_id": row["codec_id"], "bytes": row["aggregate_complete_bytes"]}
        for row in opponent_rows
        if row["eligibility_class"] == "eligible" and row["aggregate_valid"]
    ]
    strongest_aggregate = _strongest(aggregate_pool, "bytes")
    if strongest_aggregate is not None:
        aggregate_reference = int(strongest_aggregate["bytes"])
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

    # PER FAMILY / PER ITEM: JLS2 must strictly win against every eligible opponent
    # valid on that family. Equality is not a win; allowed regression is zero.
    family_decisions = []
    for family in families:
        pool = [
            {
                "codec_id": row["codec_id"],
                "bytes": row["per_family"][family]["complete_bytes"],
            }
            for row in opponent_rows
            if row["eligibility_class"] == "eligible"
            and row["per_family"][family]["valid"]
        ]
        candidate_bytes = candidate_family_bytes.get(family)
        strongest_family = _strongest(pool, "bytes")
        if strongest_family is None or candidate_bytes is None:
            family_decisions.append(
                {
                    "family": family,
                    "candidate_complete_bytes": candidate_bytes,
                    "strongest_eligible_codec": None,
                    "strongest_eligible_bytes": None,
                    "candidate_won": False,
                }
            )
            continue
        reference_bytes = int(strongest_family["bytes"])
        family_decisions.append(
            {
                "family": family,
                "candidate_complete_bytes": int(candidate_bytes),
                "strongest_eligible_codec": strongest_family["codec_id"],
                "strongest_eligible_bytes": reference_bytes,
                "candidate_won": int(candidate_bytes) < reference_bytes,
            }
        )

    all_families_won = bool(family_decisions) and all(
        row["candidate_won"] for row in family_decisions
    )

    contender = bool(
        candidate_gates_all_pass
        and required_research_opponents_valid
        and strongest_aggregate is not None
        and aggregate_margin_ok
        and all_families_won
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
        "decision_authority": (
            "Tom's 2026-07-25 owner dispatch governs this screen and supersedes the "
            "#109 prospective roster for this screen only; #109 is unchanged. The "
            "label here is 'public championship contender', distinct from #109's "
            "stricter 'championship candidate' bar."
        ),
        "equality_semantics": EQUALITY_SEMANTICS,
        "contender_margin": {
            "numerator": CONTENDER_NUMERATOR,
            "denominator": CONTENDER_DENOMINATOR,
            "applies_to": "aggregate only; per family/item requires an outright win",
        },
        "candidate_aggregate_complete_bytes": candidate_aggregate,
        "strongest_eligible_aggregate_codec": strongest_aggregate_codec,
        "strongest_eligible_aggregate_bytes": aggregate_reference,
        "aggregate_candidate_smaller": aggregate_smaller,
        "aggregate_margin_ok": aggregate_margin_ok,
        "candidate_gates_all_pass": candidate_gates_all_pass,
        "family_decisions": family_decisions,
        "all_families_won": all_families_won,
        "required_research_opponents_valid": required_research_opponents_valid,
        "required_research_opponent_status": required_valid,
        "opponent_classifications": [
            {
                "codec_id": row["codec_id"],
                "eligibility_class": row["eligibility_class"],
                "aggregate_valid": row["aggregate_valid"],
                "per_family_classification": {
                    family: row["per_family"][family]["classification"]
                    for family in families
                },
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
