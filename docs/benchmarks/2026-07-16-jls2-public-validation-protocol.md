# JLS2 one-time public validation protocol

## Status

This protocol is frozen before any Hadoop, OpenSSH, or OpenStack validation
byte is downloaded or scored. The first valid score is final. The private
holdout remains sealed.

Passing supports only a bounded statement about these three previously unseen
public LogTrie families. It is not independent-corpus, market-leading,
world-best, or state-of-the-art evidence.

## Frozen candidate

JLS2 is pinned to merged base commit
`6fbb672fb2d7fbb116b58bcf83418a8cce5f227d` and the exact implementation paths
listed in `config/jls2-public-validation-gates.json`. The workflow fails if any
candidate path differs from that commit.

The candidate uses:

- record-aligned segments targeting 16 MiB;
- the byte-exact native JSON-columnar representation;
- direct Zstandard level 6 as the per-segment fallback;
- complete per-segment candidate comparison;
- at most two compression and decompression segment workers;
- the existing JLS2 stream and JLF2 segment integrity framing.

No source name, validation identity, learned validation dictionary, new
selector rule, source-specific exception, or post-score change is allowed.

## Frozen validation data

Use version 1 of the CC-BY-4.0 LogTrie dataset publication:

| Family | File | Publisher MD5 |
| --- | --- | --- |
| Hadoop | `hadoop-full.json` | `4d29af5742a7fda1dad5a01f1b864a48` |
| OpenSSH | `openssh-full.json` | `66741ad3419cd17d14bd476270148a96` |
| OpenStack | `openstack-full.json` | `d582423a5aca8b68e0c61b0f54bf8a78` |

The fetcher must receive `--allow-blind-validation`, verify every publisher
digest, and record SHA-256 and byte size in the run manifest. No family or
slice may be added, removed, shortened, or retried after a score.

## Frozen comparators and accounting

For the identical source bytes report:

- JLS2 with a warmup and five complete file compression/decompression trials;
- direct Zstandard level 9;
- Brotli level 11;
- official PBC `pbc_only` at pinned commit
  `bac1f86d29624cb585bb4475235d22a28e60ffea`.

PBC remains fixed to pattern size 100, 2,000 training records, 64 training
threads, two training repetitions, and five online compression/decompression
repetitions. Complete PBC bytes are pattern plus payload. Complete PBC
compression time is median pattern training plus median online compression.
Named outputs are pre-created with mode `0600` to avoid the pinned CLI's
missing `open` mode argument; PBC source is not modified.

All decoded outputs must match source size and SHA-256. JLS2 output must be
deterministic and every selected segment must be no larger than its equally
framed direct fallback.

## Frozen pass gates

All gates must pass:

1. every JLS2 family round-trips exactly;
2. every family is at least 5% smaller than zstd-9;
3. aggregate JLS2 bytes are at least 10% smaller than zstd-9;
4. at least two of three families beat Brotli-11;
5. aggregate JLS2 bytes are smaller than Brotli-11;
6. complete JLS2 fallback never expands against its equally framed direct
   route;
7. quiet-host aggregate JLS2 compression is at least 100 MB/s;
8. quiet-host aggregate JLS2 decompression is at least 250 MB/s;
9. JLS2 is smaller than fixed PBC-only on every family and in aggregate;
10. every repetition, provenance, source, license, determinism, and complete
    archive-accounting check passes.

A failure is retained as the result. Validation may not be tuned or rerun with
a changed candidate, threshold, method, setting, or corpus slice.
