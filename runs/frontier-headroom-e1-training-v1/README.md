# E1 frozen training frontier census

> Training-only diagnostic; not an Axiom candidate, validation result,
> private-holdout result, independent reproduction, or state-of-the-art claim.

E1 completed exact, deterministic whole-item, sample, and conditional segment
measurements across 17 licensed development items. All numbers below count the
complete Axiom census frames, not codec payloads alone.

| Category | Best single practical | Practical per-item oracle | Full oracle including ZPAQ | Routing gain | Total headroom |
|---|---:|---:|---:|---:|---:|
| JSON/logs | 1,712,149 | 1,712,149 | 1,347,064 | 0.00% | **21.32%** |
| Numeric/time-series | 10,517,508 | 9,806,996 | 9,602,609 | **6.75%** | **8.69%** |
| Tabular records | 3,129,252 | 3,129,252 | 3,030,379 | 0.00% | 3.15% |
| English Wikimedia | 24,157,083 | 24,157,083 | 24,109,058 | 0.00% | 0.19% |
| Source-code bundles | 6,221,779 | 6,221,779 | 6,221,779 | 0.00% | 0.00% |

The portfolio decision is therefore JSON/log modeling first and bounded
numeric routing second. JSON's measured gap is entirely between the strongest
practical codec and the ZPAQ research ceiling on these training items; practical
per-item routing contributes nothing. Numeric routing exposes substantial
training headroom before a new numeric codec is attempted. This is a research
allocation decision, not proof that Axiom can capture the full oracle gap.

The original measurement run completed all 20 measurement shards and five
segment jobs, but its publisher rejected unreceipted warmup logs. Recovery run
[`29863867135`](https://github.com/Atomics-hub/compression-lab/actions/runs/29863867135)
reused those retained artifacts without rerunning compression. It first matched
the live GitHub metadata against a pinned receipt containing all 28 artifact IDs
and archive digests, then inventoried and hashed the exact historical warmup-log
roster while preserving the strict no-unbound-files invariant.

Speed and memory remain same-hosted-runner contextual measurements. The full
downloadable artifact contains per-codec compression/decompression throughput,
peak RSS, exactness, complete reconstructed containers, raw-shard commitments,
and separate measurement-versus-publication verifier provenance. See
[`receipt.json`](receipt.json) for its immutable identity and hashes.
