#!/usr/bin/env python3
"""Evaluate the frozen CLUE-LDS JLS2 championship screen by applying the reducer.

This evaluator makes no compression measurements. It loads the score bundle the
benchmark produced, applies the frozen integer reducer
(scripts/reduce-clue-jls2-championship-screen-v1.py) mechanically, verifies the
bundle roster against the frozen gates (every eligible opponent attempted; the
required research opponents Kanzi-max and ZPAQ -m54 present; contextual and
unavailable tools recorded, never scored as wins or losses), and writes the
immutable decision. It never re-tunes a threshold or setting.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
REDUCER = REPOSITORY / "scripts" / "reduce-clue-jls2-championship-screen-v1.py"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".partial", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(payload, output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def load_reducer() -> Any:
    specification = importlib.util.spec_from_file_location(
        "reduce_clue_jls2_championship_screen_v1", REDUCER
    )
    if specification is None or specification.loader is None:
        raise ValueError("unable to load the championship reducer")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def verify_roster(bundle: dict[str, Any], gates: dict[str, Any], reducer: Any) -> None:
    roster = gates["roster"]
    attempted = {opponent["codec_id"] for opponent in bundle["opponents"]}
    for codec_id in roster["eligible_opponent_codec_ids"]:
        if codec_id not in attempted:
            raise ValueError(f"eligible opponent was not attempted: {codec_id}")
    for codec_id in roster["required_research_opponent_codec_ids"]:
        if codec_id not in attempted:
            raise ValueError(f"required research opponent missing from bundle: {codec_id}")
    eligible_ids = tuple(roster["eligible_opponent_codec_ids"])
    if set(eligible_ids) != set(reducer.ELIGIBLE_OPPONENT_CODEC_IDS):
        raise ValueError("gates eligible roster differs from the frozen reducer roster")
    if tuple(roster["required_research_opponent_codec_ids"]) != tuple(
        reducer.REQUIRED_RESEARCH_OPPONENT_CODEC_IDS
    ):
        raise ValueError("gates required research roster differs from the reducer")
    if (
        reducer.CONTENDER_NUMERATOR != gates["reducer"]["contender_numerator"]
        or reducer.CONTENDER_DENOMINATOR != gates["reducer"]["contender_denominator"]
    ):
        raise ValueError("gates contender constants differ from the reducer")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--gates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.output.exists():
        raise SystemExit("refusing to replace the championship decision")
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    gates = json.loads(args.gates.read_text(encoding="utf-8"))
    reducer = load_reducer()
    verify_roster(bundle, gates, reducer)
    decision = reducer.reduce_championship(bundle)
    decision["claim_ceiling"] = gates["claim_ceiling"]
    decision["prior_scores"] = gates["prior_scores"]
    decision["sources"] = {
        "bundle_sha256": sha256_file(args.bundle),
        "gates_sha256": sha256_file(args.gates),
    }
    write_json_atomic(args.output, decision)
    print(json.dumps({"result": decision["result"], "contender": decision["contender"]}, indent=2))
    return 0 if decision["contender"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
