# Fresh tabular-successor corpus protocol

## Decision

Freeze a new licensed corpus before successor development. The consumed TBL1
public-validation families define only two evaluation strata:

1. **record tables**: rows represent events, entities, measurements, or time
   points with semantically heterogeneous fields;
2. **dense feature matrices**: rows are fixed-width feature vectors, often
   image-derived, with tens to thousands of mostly numeric dimensions.

These labels are never production-selector inputs. A shippable selector must
use only bounded bytes from the current file and complete framed candidate
sizes where practical. No source ID, filename, DOI, track label, or frozen
family exception is eligible.

## Contamination boundary

MetroPT, electricity load, OULAD, and OCRB have been consumed. Their source
bytes, headers, feature counts, sampled statistics, codec deltas, and family
identities cannot train a successor or set a threshold. The retained result may
motivate evaluating record tables and dense feature matrices separately; it may
not contribute a training row.

All ten families below were absent from the previous tabular corpus. This file
and `config/tabular-successor-corpus-v1.json` must merge before the six
development archives are acquired. The four validation archives remain
unopened until a successor candidate, selector, gates, runner, and evaluator
are merged and locked.

## Fresh development families

| Track | Family | Frozen publisher member | License | Page |
| --- | --- | --- | --- | --- |
| Record table | Bike Sharing | `hour.csv` | CC BY 4.0 | [UCI 275](https://archive.ics.uci.edu/dataset/275/bike%2Bsharing%2Bdataset) |
| Record table | Appliances Energy | `energydata_complete.csv` | CC BY 4.0 | [UCI 374](https://archive.ics.uci.edu/dataset/374/appliances%2Benergy%2Bprediction) |
| Record table | Seoul Bike | `SeoulBikeData.csv` | CC BY 4.0 | [UCI 560](https://archive.ics.uci.edu/dataset/560/seoul%2Bbike%2Bsharing%2Bdemand) |
| Dense feature matrix | Semeion digits | `semeion.data` | CC BY 4.0 | [UCI 178](https://archive.ics.uci.edu/dataset/178/semeion%2Bhandwritten%2Bdigit) |
| Dense feature matrix | Optical Digits | `optdigits.tra` | CC BY 4.0 | [UCI 80](https://archive.ics.uci.edu/dataset/80/optical%2Brecognition%2Bof%2Bhandwritten%2Bdigits) |
| Dense feature matrix | Multiple Features pixels | `mfeat-pix` | CC BY 4.0 | [UCI 72](https://archive.ics.uci.edu/dataset/72/multiple%2Bfeatures) |

The first authorized development acquisition records archive and exact item
SHA-256 values before any codec is run. Files are preserved byte-for-byte;
space-delimited matrices are not converted to CSV and repeated whitespace is
not collapsed.

## Unopened public-validation families

| Track | Family | Frozen publisher member | License | Page |
| --- | --- | --- | --- | --- |
| Record table | Student academic success | `data.csv` | CC BY 4.0 | [UCI 697](https://archive.ics.uci.edu/dataset/697/predict%2Bstudents%2Bdropout%2Band%2Bacademic%2Bsuccess) |
| Record table | Room occupancy | `Occupancy_Estimation.csv` | CC BY 4.0 | [UCI 864](https://archive.ics.uci.edu/dataset/864/room%2Boccupancy%2Bestimation) |
| Dense feature matrix | Gisette | `GISETTE/gisette_train.data` | CC BY 4.0 | [UCI 170](https://archive.ics.uci.edu/dataset/170/gisette) |
| Dense feature matrix | Madelon | `MADELON/madelon_train.data` | CC BY 4.0 | [UCI 171](https://archive.ics.uci.edu/dataset/171/madelon) |

“Train” in two publisher filenames describes the original machine-learning
split. Those bytes are unopened public validation for this compression project.

## Development sequence

1. Acquire and hash only the six development members.
2. Run an exact baseline census with store, LZ4-1, gzip-9, bzip2-9, zstd
   3/9/19, Brotli-11, LZMA-9, and 7-Zip-9.
3. Measure frozen TBS1 unchanged. This is diagnostic context, not a rerun of the
   consumed score.
4. Test materially distinct successor hypotheses on development only:
   whitespace-aware exact transposition, a dense numeric representation, and a
   bounded sampled comparison against a strong direct fallback.
5. Use family-level leave-one-out selection tests. Reject any selector that
   needs source identity, semantic header exceptions, or a consumed-family
   feature.
6. Promote only a deterministic, bounded, no-expansion candidate that beats the
   strongest complete exact-byte baseline by at least 5% on both tracks while
   meeting its frozen speed, memory, corruption, streaming, and portability
   gates.
7. Merge and lock the complete one-shot validation package before any of the
   four validation archives is acquired.

## Claim ceiling

This protocol is corpus provenance and contamination control, not compression
evidence. No ratio, speed, market, category-win, world-best, or state-of-the-art
claim follows from freezing it.
