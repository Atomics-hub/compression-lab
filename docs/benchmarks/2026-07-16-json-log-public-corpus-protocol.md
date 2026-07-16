# JSON-log public corpus protocol

## Purpose and claim ceiling

LWX2 showed a material opportunity on previously exposed synthetic JSONL.
This phase asks whether the frozen, source-agnostic representation transfers
to real JSON log families. It is not a state-of-the-art or market claim.

The source selection, family split, candidate, baselines, and gates below were
frozen before any compression score was inspected. The Apache file was
downloaded only to verify its publisher checksum, line-oriented JSON format,
and byte-level suitability; its first compression score is development data.

## Source and license

Use version 1 of the **LogTrie datasets**, published February 8, 2026:

- DOI: `10.5281/zenodo.18522101`
- record: `https://zenodo.org/records/18522101`
- creator/data manager: Ying Chu
- license: CC BY 4.0
- format: standardized JSON representing real-world semi-structured logs

Every downloaded file must match the MD5 published by Zenodo. The fetcher also
records SHA-256, exact byte size, config digest, and family identity in a local
manifest. Corpus bytes remain outside version control.

## Frozen family split

No family may cross splits.

### Development

| Family | File | Published size | Published MD5 |
| --- | --- | ---: | --- |
| Apache | `apache-full.json` | 9.0 MB | `dd4c4b9732f978a54fd73f5b621f86c5` |
| HealthApp | `healthapp-full.json` | 31.8 MB | `04b634e64d74ae8f26a3f4448cb6747a` |
| HPC | `hpc-full.json` | 49.3 MB | `fef9e45add36630fe0314a3f16ce9c8d` |
| Mac | `mac-full.json` | 23.2 MB | `7f0e4edc0f85e752ededd9e2b1104d38` |
| ZooKeeper | `zookeeper-full.json` | 11.3 MB | `af1edb620544c1c08d6a3fd296bd8c8e` |

These five families may be inspected, scored, profiled, and used to reject or
revise future hypotheses.

### Blind public validation

| Family | File | Published size | Published MD5 |
| --- | --- | ---: | --- |
| Hadoop | `hadoop-full.json` | 33.9 MB | `4d29af5742a7fda1dad5a01f1b864a48` |
| OpenSSH | `openssh-full.json` | 132.2 MB | `66741ad3419cd17d14bd476270148a96` |
| OpenStack | `openstack-full.json` | 48.3 MB | `d582423a5aca8b68e0c61b0f54bf8a78` |

The validation config is versioned now, but the files must not be downloaded
or scored until the development decision freezes the exact candidate and
thresholds. The fetch script rejects validation configs unless the caller
passes `--allow-blind-validation`.

The project's private holdout remains unopened and outside this public split.

## Frozen candidate

Evaluate the byte-identical native LWX2 representation already frozen in
`2026-07-16-json-log-native-protocol.md`:

- most recent exact-length reference;
- 1,024 deterministic length slots;
- maximum referenced record size of 32 KiB;
- byte-aligned zero/literal residual runs;
- raw-record fallback;
- Zstandard level 9 backend;
- complete direct-Zstandard frame fallback;
- a fixed 56-byte `CLG1` header containing version, mode, original size,
  transformed size, and SHA-256 of the original bytes.

No JSON parser, source name, event template, corpus identity, learned
dictionary, source-specific exception, or validation-driven rule is allowed.

## Required baselines and accounting

At minimum report complete bytes and exact round trip for:

- direct Zstandard levels 3, 9, and 19;
- Brotli levels 6 and 11;
- gzip level 9;
- LZMA level 9;
- 7-Zip level 9 where installed;
- LWX2 plus Zstandard 9 with the complete direct fallback;
- CLP for JSON logs;
- LogLite and PBC if their public artifacts can be run reproducibly without
  copying unlicensed source.

All candidate sizes include mode and size metadata. Speed measurements must
include transform and backend work. Absolute speed claims require a quiet-host
run; noisy runs may establish only sizes, correctness, and within-run choices.

## Development gates

Freeze the blind-validation candidate only if all five development families:

1. round-trip exactly through native encode and decode;
2. select the transformed route without direct-fallback expansion;
3. are at least 5% smaller than direct Zstandard 9;
4. have aggregate bytes no larger than Brotli 11;
5. sustain at least 100 MB/s complete compression and 250 MB/s complete
   decompression in a quiet-host repeated run.

Also require:

- at least four of five families beat Brotli 11;
- no corruption, malformed-input, or existing suite regression;
- bounded retained reference history and deterministic output;
- no rule change after inspecting validation.

If a development gate fails, retain the evidence and revise only on the
development families. Do not open validation.

## Blind validation gates

The frozen candidate advances to integration only if:

- every validation family round-trips exactly;
- every family is at least 5% smaller than direct Zstandard 9;
- aggregate bytes are at least 10% smaller than direct Zstandard 9;
- at least two of three families beat Brotli 11;
- aggregate bytes are smaller than Brotli 11;
- complete fallback never exceeds the equally framed direct route;
- quiet-host aggregate compression is at least 100 MB/s and decompression is
  at least 250 MB/s;
- no candidate, threshold, slot count, record limit, backend level, or corpus
  slice changes after the first validation score.

A pass supports only the bounded statement that this version wins on the
specified unseen LogTrie JSON-log families. Broader or world-best language
still requires independent corpora and competitive log-specific baselines.
