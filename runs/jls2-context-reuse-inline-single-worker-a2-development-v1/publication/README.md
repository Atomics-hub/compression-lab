# JLS2 A2 inline-single-worker development result

**Outcome: A2 was rejected.** A1 had already failed its product gate; neither A1 nor A2 replaces the pre-A1 product baseline at `7b081f6f11c2561c36289cfc57f7d3715ab8c594`. Failed A2 gates: `candidate_peak_rss_at_or_below_448_mib`, `stress_peak_rss_reduction_at_least_5_percent`.

![A1 versus A2 comparison](comparison.svg)

## Frozen paired result

Both binaries decoded the exact same complete Linux-generated JLS2 frame for every input. Timing is cold-process parent wall time; restored output was verified by complete size and SHA-256.

| Variant | Median aggregate | Minimum aggregate | CV | Peak RSS | Exact | Selected for fresh validation |
| --- | ---: | ---: | ---: | ---: | :---: | :---: |
| exact A1 | 427.55 MB/s | 425.16 MB/s | 0.36% | 627.2 MiB | yes | no |
| combined A1+A2 | 439.47 MB/s | 436.74 MB/s | 0.41% | 627.2 MiB | yes | no |

## Per-input memory

| Input | Exact A1 peak | Combined A1+A2 peak | Change | A2 median |
| --- | ---: | ---: | ---: | ---: |
| `clue-early-development` | 627.2 MiB | 627.2 MiB | +0.00% | 473.54 MB/s |
| `clue-middle-development` | 627.2 MiB | 627.2 MiB | +0.00% | 484.03 MB/s |
| `clue-late-development` | 627.2 MiB | 627.2 MiB | +0.00% | 464.59 MB/s |
| `jls2-context-stress-256` | 627.2 MiB | 627.2 MiB | +0.00% | 340.10 MB/s |

## Frozen A2 gates

- ✅ `all_exact`
- ❌ `candidate_peak_rss_at_or_below_448_mib`
- ✅ `no_clue_family_peak_rss_regression`
- ✅ `candidate_median_throughput_at_least_95_percent_of_baseline`
- ✅ `all_candidate_item_medians_at_or_above_250_mbps`
- ✅ `all_candidate_rounds_at_or_above_225_mbps`
- ✅ `candidate_cv_at_or_below_20_percent`
- ❌ `stress_peak_rss_reduction_at_least_5_percent`

## Prior product boundaries

A1 reusable contexts recorded **625.2 MiB** development peak RSS against its **448 MiB** frozen development limit, so A1 did not replace the pre-A1 product baseline. A2 uses exact A1 only as its attribution baseline.

The first public-validation result remains an immutable **no-pass** at **621.3 MiB** versus the frozen **512 MiB** product cap. Its ranges are consumed and can never be tuned on or rerun.

## Unchanged compression context

This decoder-only A2 experiment changed no compression evidence. Immutable development JLS2 remains 3,523,721 bytes (57.77x), 18.08% smaller than brotli-11.

## Provenance

- Pre-A1 product baseline: `7b081f6f11c2561c36289cfc57f7d3715ab8c594`
- Exact A1 attribution baseline: `131547f35747cc0ff9dedbdef66d8a9516a7464f`
- A2 candidate: `0f3377dff647e8a6d99b65d8f8a269687faa8ec6`
- Host: `Linux-6.8.0-1062-azure-x86_64-with-glibc2.35`; Python `3.12.13`; `rustc 1.97.0 (2d8144b78 2026-07-07)`
- Workflow: [run 29676674924, attempt 1](https://github.com/Atomics-hub/compression-lab/actions/runs/29676674924) (`failure`)
- Measurement job: [job 88165232780](https://github.com/Atomics-hub/compression-lab/actions/runs/29676674924/job/88165232780)
- Uploaded artifact: ID `8439147016`, `jls2-context-reuse-inline-single-worker-a2-29676674924`, `sha256:b6930b7b9739a2e8768733096ba534406e1b87afa49a40b950e79bb6d72ec83d`
- Schedule: 8 discarded warmups + 56 measured trials = 64 exact decodes

## Evidence boundary

Claim ceiling: **development-only A2 decoder-memory evidence.** This is not public validation, private-holdout evidence, independent reproduction, or a universal, market-leading, world-best, or state-of-the-art result.
