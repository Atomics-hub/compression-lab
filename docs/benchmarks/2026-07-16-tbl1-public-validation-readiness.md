# TBL1 public-validation readiness decision

## Decision

**Ready to freeze; validation remains unopened.** The bounded `TBS1` candidate,
all ten exact-byte comparators, corpus identities and slicing, one-shot runner,
evaluator, pass thresholds, timing basis, cold-memory measurement, deterministic
frame proof, and equally framed per-segment fallback audit are now explicit.

This document does not report a validation result. No public-validation archive
was downloaded, inspected, sampled, or scored while preparing it.

## Provenance audit

The four declared UCI pages were checked before acquisition. Each page names the
frozen selected member and declares CC BY 4.0:

| Family | Frozen member | Publisher size | License page |
| --- | --- | ---: | --- |
| MetroPT-3 | `MetroPT3(AirCompressor).csv` | 208.2 MB | [UCI 791](https://archive.ics.uci.edu/dataset/791/metropt%2B3%2B) |
| Electricity load | `LD2011_2014.txt` | 678.1 MB | [UCI 321](https://archive.ics.uci.edu/dataset/321/electricity) |
| OULAD events | `studentVle.csv` | 432.8 MB | [UCI 349](https://archive.ics.uci.edu/dataset/349/open%2Buniversity%2Blearning%2Banalytics%2Bdataset) |
| Character Font OCRB | `OCRB.csv` | 117.1 MB | [UCI 417](https://archive.ics.uci.edu/dataset/417/character%2Bfont%2Bimages) |

The audit corrected one pre-acquisition metadata defect: the OULAD entry's page
URL pointed to an unrelated UCI tennis page even though its ID, DOI, title,
archive URL, and member were already OULAD. The corrected corpus configuration
SHA-256 is
`a72f6faee6b638bfe481d225766c77f3ef6bd54b419d7e676e66f15d8dc5741e`.

UCI does not publish archive digests on these pages. The first authorized
acquisition must therefore record each received archive SHA-256, exact selected
item SHA-256, byte count, member, slice rule, license, DOI, and source URL in the
generated manifest. Each selected byte stream is the frozen complete file or
the longest LF-terminated prefix no larger than 64 MiB; no parsing,
normalization, transcoding, or reserialization is allowed.

## Frozen candidate and execution

The candidate is `tbl1-stream-dense` at public merge commit
`80b9f5f89f9ef3cf81fb4d6878ea65b6f8a9199e`. The gate file pins SHA-256 values
for the Python candidate, Rust transform, native bridge, benchmark plumbing,
package dependency declaration, and portable reference-decoder test. The
scored runner refuses a dirty tracked tree or any candidate path that differs
from both its declared digest and that base commit.

The first eligible score uses:

- one warmup and five deterministically shuffled repetitions;
- one persistent worker for comparable point throughput;
- a separate one-repetition cold-process run for peak encode/decode RSS;
- 16 MiB target segments, 1 MiB record-boundary slack, and two workers;
- an eligible preflight load no greater than 0.75 per logical CPU;
- a 1,200-second per-operation timeout;
- a new output directory that can never be replaced or resumed.

Before any timed score starts, all candidate digests, corpus items, licenses,
splits, byte counts, source hashes, codec availability, native transform
availability, repository cleanliness, and host load are checked. Once the
output directory is created, `attempt.json` permanently marks the score. A
failed or interrupted attempt is retained rather than rerun.

## Frozen comparators and accounting

The same exact bytes are scored with `store`, LZ4-1, gzip-9, bzip2-9, zstd
3/9/19, Brotli-11, xz/LZMA2-9, and 7-Zip/LZMA2-9. Tool versions are recorded by
the runner. The aggregate primary reference is the smallest complete fixed
baseline. Each family reference is that family's smallest complete baseline.
Every archive byte counts; every trial must restore the source SHA-256.

After timing, each source is compressed twice outside the timed measurements.
The frames must be byte-identical and decode exactly. The proof parser walks
every `TBS1` segment, reconstructs the exact equally framed direct/store
fallback selected by the frozen policy, and requires the chosen inner frame to
be no larger. Source, segment, payload, and outer-frame byte accounting must all
close exactly.

## Frozen pass gates

Every gate must pass on the first score:

1. at least 5% smaller in aggregate than the smallest complete fixed baseline;
2. at least 5% smaller than the best family baseline on at least three of four
   families;
3. at least 50 MB/s aggregate compression and 250 MB/s decompression;
4. every one of the five repetition aggregates also clears 50/250 MB/s;
5. cold encode and decode peak RSS are each at most 512 MiB;
6. every candidate and comparator trial round-trips exactly;
7. both candidate frames per family are byte-identical;
8. every selected segment is no larger than its equally framed fallback;
9. candidate, corpus, codec roster, execution settings, and result digests are
   frozen and complete;
10. the private holdout remains sealed.

## Readiness scorecard

The last permitted evidence before opening validation is the merged development
result:

| Measure | Compression Lab | Strongest tested standard / gate | Status |
| --- | ---: | ---: | --- |
| Complete bytes | 12,134,137 | Brotli-11: 13,425,698 | 9.62% smaller |
| Compression | 60.92 MB/s | gate: 50 MB/s | Pass |
| Decompression | 356.76 MB/s | gate: 250 MB/s | Pass |
| Cold encode RSS | 409.72 MiB | gate: 512 MiB | Pass |
| Cold decode RSS | 120.22 MiB | gate: 512 MiB | Pass |
| Family ratio wins | 3 / 4 | gate: 3 / 4 | Pass |
| Public unseen validation | unopened | required | Pending |
| Independent reproduction | no | required for state-of-the-art | Pending |

These development numbers are context, not a prediction of the unseen result.
The first public-validation decision must publish the same complete standard
chart even if Compression Lab loses.

## Claim ceiling and next action

Readiness supports no new compression-performance claim. Once the runner and
evaluator are merged, a final lock commit must pin that exact readiness commit.
Only then may the four archives be acquired and the one-time score run. A pass
would support a category-scoped public-validation statement; private-holdout
success and independent reproduction remain mandatory before any
state-of-the-art language.
