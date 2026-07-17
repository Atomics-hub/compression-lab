# CLUE-LDS JLS2 decode-scheduling protocol

## Purpose

Identify whether JLS2's fresh CLUE-LDS decode variance comes from nested
parallel scheduling rather than the byte format or reconstruction kernel. The
experiment may change only decode scheduling. It must not change compressed
bytes, the JLS2/JLF2/JCT1 formats, selector decisions, integrity checks, or
output bytes.

This is a development experiment. The two frozen CLUE-LDS public-validation
ranges remain unmaterialized and unopened.

## Fixed inputs

Use the three licensed development ranges pinned in
`config/clue-json-log-corpus-v1.json`:

- `clue-early-development`;
- `clue-middle-development`; and
- `clue-late-development`.

Regenerate one JLS2 frame per range with the accepted 16 MiB segment contract.
The complete frame sizes must match the first CLUE census exactly: 1,382,653,
738,259, and 1,402,809 bytes respectively. Record their SHA-256 values and
reject any drift between scheduling variants.

## Predeclared variants

| Variant | Segment workers | Per-segment channel workers | Purpose |
| --- | ---: | ---: | --- |
| `outer2-innerauto` | 2 | host auto | Current product baseline |
| `outer1-innerauto` | 1 | host auto | Remove simultaneous nested pools |
| `outer2-inner1` | 2 | 1 | Parallelize segments only |
| `outer2-inner2` | 2 | 2 | Bound total nested fan-out |

No other topology is eligible for selection from this run.

## Timing and schedule

- one discarded cold-process warmup for every family and variant;
- seven measured rounds;
- one fresh worker process per family, variant, and round;
- deterministic rotating variant order per family and alternating family order;
- primary timing: parent wall clock including interpreter and worker startup,
  complete file decode, integrity verification inside JLS2, and atomic output;
- secondary timing: worker wall clock around the same product decode;
- throughput uses decimal MB/s;
- record worker CPU time, high-water RSS, host, runtime, source hashes, frame
  hashes, source-code hashes, native-library hash, and load averages.

The parent rechecks restored size and SHA-256 outside the timed interval. Every
trial must be exact.

## Selection gates

A non-baseline topology qualifies only if all of these are true:

1. compressed sizes and SHA-256 values are identical across every variant;
2. all 21 measured family round trips are exact;
3. all seven aggregate parent-wall rounds are at least 250 MB/s;
4. every family's median parent-wall decode rate is at least 250 MB/s;
5. aggregate round-rate coefficient of variation is at most 20%;
6. peak worker RSS is at most 512 MiB; and
7. median paired aggregate improvement over `outer2-innerauto` is at least 5%.

If more than one topology qualifies, select the topology with the highest
minimum aggregate round rate, then the highest median aggregate rate. If none
qualify, retain the current product and use the raw trial evidence to define the
next experiment.

## Claim ceiling

The result can support only a development claim about scheduling on the three
fresh CLUE-LDS development ranges. It cannot advance JLS2 to public validation,
rewrite the retained public-validation result, or support a market-leading,
world-best, universal, or state-of-the-art claim.
