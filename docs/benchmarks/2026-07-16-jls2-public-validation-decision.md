# JLS2 JSON/log one-time public validation

## Decision

**Overall frozen gate: ❌ FAIL**

Strong unseen ratio win over zstd-9 and PBC-only, but the frozen overall gate failed Brotli family coverage and decompression speed.

## Aggregate standards comparison

| Standard | Complete bytes | Ratio | JLS2 size result | Compress MB/s | JLS2 compress result | Decompress MB/s | JLS2 decompress result | Peak memory MiB | Exact |
| --- | ---: | ---: | --- | ---: | --- | ---: | --- | ---: | --- |
| JLS2 frozen 16 MiB JSON-columnar selector | 3,999,168 | 53.60x | — candidate | 155.83 | — candidate | 165.88 | — candidate | — | ✅ |
| zstd level 9 | 5,614,733 | 38.18x | ✅ win: 28.77% smaller | 222.03 | ❌ loss: 29.82% slower | 1,547.88 | ❌ loss: 89.28% slower | — | ✅ |
| Brotli quality 11 | 4,191,238 | 51.15x | ⚠️ mixed: 4.58% smaller in aggregate but smaller on only 1 of 3 families | 0.49 | ✅ win: 317.71x faster | 1,168.58 | ❌ loss: 85.80% slower | — | ✅ |
| PBC official pbc_only; pattern plus payload | 24,718,693 | 8.67x | ✅ win: 83.82% smaller | 0.56 | ✅ win: 277.72x faster than complete training plus online rate; 1.76x faster than online-only rate | 94.63 | ✅ win: 1.75x faster | — | ✅ |

Speed cells are host-scoped. Measurement basis and comparability:

- **JLS2:** five complete trials; aggregate source bytes divided by sum of family medians; five complete trials; aggregate source bytes divided by sum of family medians. candidate reference. Memory: not measured in this validation; development worst-case RSS was 386.4 MB compression and 171.4 MB decompression.
- **zstd:** one complete baseline trial per family; one complete baseline trial per family. same host and bytes, but baseline timing is single-trial context rather than a repeated speed gate. Memory: not measured.
- **Brotli:** one complete baseline trial per family; one complete baseline trial per family. same host and bytes, but baseline timing is single-trial context rather than a repeated speed gate. Memory: not measured.
- **PBC:** two pattern-training trials plus five online trials; complete rate includes median training and median online time; five complete trials per family. same hosted runner and bytes in a separate quiet-host stage; PBC training deliberately uses 64 threads on 4 logical CPUs. Memory: not measured.

## Family ratio results

| Family | Source bytes | JLS2 bytes | vs zstd-9 | vs Brotli-11 | vs PBC-only |
| --- | ---: | ---: | ---: | ---: | ---: |
| hadoop | 33,908,970 | 755,784 | +28.78% | -2.05% | +88.18% |
| openssh | 132,211,920 | 1,869,933 | +34.85% | +12.99% | +84.26% |
| openstack | 48,251,996 | 1,373,451 | +18.41% | -5.54% | +78.70% |

Positive values mean JLS2 is smaller.

## Frozen gates

| Gate | Result |
| --- | --- |
| frozen candidate | ✅ pass |
| first score completed | ✅ pass |
| exact roundtrip | ✅ pass |
| deterministic jls2 | ✅ pass |
| no expansion | ✅ pass |
| zstd9 per family at least 5 percent | ✅ pass |
| zstd9 aggregate at least 10 percent | ✅ pass |
| brotli11 at least 2 of 3 families | ❌ fail |
| brotli11 aggregate | ✅ pass |
| compression at least 100 mbps | ✅ pass |
| decompression at least 250 mbps | ❌ fail |
| pbc per family | ✅ pass |
| pbc aggregate | ✅ pass |
| all provenance and accounting | ✅ pass |

## Evidence boundary

- Category: newline-delimited flat JSON logs
- Stage: public-validation
- Families: hadoop, openssh, openstack
- Source bytes: 214,372,886
- License: CC-BY-4.0
- Runner: Ubuntu 22.04, Linux 6.8.0-1062-azure x86_64, 4 logical CPUs
- Run: https://github.com/Atomics-hub/compression-lab/actions/runs/29542804015
- Workflow commit: `2a268f69a2672ab2cc37c640f085bcc5cbf167e5`
- Decision SHA-256: `1e9ea7932f40d30b85b820d31f8389434ddeef0375e974e166ed7baaefb18900`
- Private holdout: sealed

Claim ceiling: One-time unseen public LogTrie family evidence only; not independent-corpus, market-leading, world-best, or state-of-the-art evidence.

## Next decision

Retain the failed first score. Do not tune or rerun JLS2 on these validation families. Preserve the ratio representation as validated evidence, profile Linux decode using development data only, and require a fresh independently sourced corpus for any successor claim.
