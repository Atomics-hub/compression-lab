# JLS2 A3 hosted attribution — rejected

![JLS2 A3 attribution gate](comparison.svg)

The immutable development-only hosted preflight rejected A3 before any product candidate or product A/B. The minimum decoded-concurrency potential and credited attribution were 83,722,100 bytes; the minimum observed phase-correlated RSS reduction was 99,414,016 bytes. Each was required to reach 105,202,484 bytes.

| Frozen gate | Observed | Required | Shortfall | Passed? |
|---|---:|---:|---:|:---:|
| decoded concurrency potential | 83,722,100 B | 105,202,484 B | 21,480,384 B | no |
| phase correlated rss reduction | 99,414,016 B | 105,202,484 B | 5,788,468 B | no |
| credited attribution | 83,722,100 B | 105,202,484 B | 21,480,384 B | no |

All eight diagnostic decodes were exact, both generated topologies matched, and encoded lifetime received zero authorization credit. Those integrity passes do not override the failed attribution gates.

## Decision and claim ceiling

A3 is killed at preflight. No A3 implementation, product A/B, validation run, holdout run, product replacement, market-leading claim, world-best claim, or state-of-the-art claim is authorized. The pre-A1 product remains retained; exact A2 remains attribution-only.

This evidence is development-only. No validation or private-holdout bytes were accessed.

## Immutable hosted identity

- Run `29765080842`, job `88429200694`, attempt `1`, conclusion `failure`.
- Artifact `8470661511` / `jls2-declared-size-lifetime-a3-attribution-29765080842` / `sha256:42ae14e5a0cdd63f8673fe5f4256e0f1dda16f4cc86e80acb3570e66407d3a05`.
- GitHub workflow head `41d2aaea12e5126bb83106792bfd575dc12e7440`; embedded PR merge-workflow commit `3cfd54e798056bd419dbbd3daec4359be873a87b`.
- Exact A2 commit `0f3377dff647e8a6d99b65d8f8a269687faa8ec6` and product binary `c67e9c9b1902414c2b2e67991631d4cd065041242e6dd39392d673da2ca752fd`.
- The raw result, detached result digest, log, provenance, comparison, chart, and receipt are retained together here.
