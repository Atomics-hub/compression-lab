# JSON-log LWX1 discovery decision

## Decision

Reject LWX1 as specified. The candidate passed every ratio and correctness gate
but failed the frozen pure-Python transform-speed gate by roughly 18–20×. Do
not integrate LWX1 into the file format or describe the synthetic size result
as product or market evidence.

The ratio result is strong enough to motivate a materially different native,
single-reference candidate under a new protocol.

## Discovery setup

- Inputs: three deterministic 4 MiB JSONL families.
- Claim ceiling: synthetic and previously exposed discovery only.
- History policy: up to eight most-recent same-length records.
- Residual: bytewise XOR followed by byte-aligned zero/literal runs.
- Backends: gzip-9, LZMA-9, zstd-3/9, Brotli-11, and LWX1+zstd-3/9.
- Integrity: transform round trip plus backend and transform round trip for
  every LWX1 candidate.

The exact result artifacts are:

- `runs/json-log-length-xor-discovery-v1.json`
- `runs/json-log-length-xor-discovery-v1.csv`

## Size result

| Discovery family | LWX1+zstd-9 | zstd-9 | Gain vs zstd-9 | Brotli-11 | Referenced records |
| --- | ---: | ---: | ---: | ---: | ---: |
| Existing JSON-log smoke | 8,341 | 65,960 | 87.35% | 43,815 | 29,298 / 29,309 |
| Access JSONL | 143,644 | 286,166 | 49.80% | 146,326 | 22,709 / 22,720 |
| Event JSONL | 81,058 | 311,644 | 73.99% | 164,254 | 39,691 / 39,694 |

LWX1+zstd-9 beat both zstd-9 and Brotli-11 on every discovery family. The
access-log result was only 1.83% smaller than Brotli-11, so broader
log-specific baselines remain essential.

The transform reduced each 4 MiB source to 568–688 KiB before Zstandard,
confirming that same-length alignment exposed substantial residual structure
rather than relying on a backend-level parameter change.

## Speed result

The pure-Python transform alone measured:

| Discovery family | Transform seconds | Transform MB/s |
| --- | ---: | ---: |
| Existing JSON-log smoke | 8.049 | 0.521 |
| Access JSONL | 8.606 | 0.487 |
| Event JSONL | 7.435 | 0.564 |

The frozen gate required at least 10 MB/s. Backend-only timing in the JSON
artifact is not complete candidate throughput and must not be quoted as such.

## Learning

The eight-way Python search is not a viable implementation seam, but the size
signal is too large to dismiss as selector noise. The next experiment changes
both policy and execution:

- one most-recent same-length reference rather than an eight-reference search;
- a bounded native slot table rather than Python deques and byte generators;
- an O(n) transform with fixed maximum history memory;
- complete timing that includes transform, backend, and frame overhead.

This is a new LWX2 hypothesis, not a post-hoc relaxation of the LWX1 gate.
