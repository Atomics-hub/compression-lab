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

### Development acquisition receipt

The first authorized acquisition completed on 2026-07-17. All six publisher
members were complete, totaling 18,635,606 bytes. No public-validation archive
was requested, downloaded, listed, or inspected.

| Family | Exact bytes | Archive SHA-256 | Selected-item SHA-256 |
| --- | ---: | --- | --- |
| Bike Sharing | 1,156,736 | `b70182d0d0508e9abbb79306ce5c0cec34869000f8220175ac83d11dbe845401` | `e03de4ee4ef4dc376ac6e04bf829673c6269e8eba5c60fa121640fa2f829504f` |
| Appliances Energy | 11,979,363 | `2fccf354445d886e7917620b0195db1f3e3e34d5a067a93b844694a4c561255a` | `2820bf712ad0275cb18b85a05250926100d8e65ebb9f4d2d016ca91ea152a25d` |
| Seoul Bike | 604,166 | `139e9908f0a3544bb222386855c9ce107e96467306bb8e4ce936aab59e7baac4` | `373339b71a8935d69e9af0abf26a70744632119862eeb3919efb389a7b749c60` |
| Semeion digits | 2,889,702 | `6fb091394714cddda5751d4e1c2781ab094e7cf15de07917fb40e581f19efc75` | `f43228ae3da5ea6a3c95069d53450b86166770e3b719dcc333182128fe08d4b1` |
| Optical Digits | 563,639 | `0d7b054fea010270e9b3f06411c654c5e59547732ad626381980baffe0a23fb0` | `e1b683cc211604fe8fd8c4417e6a69f31380e0c61d4af22e93cc21e9257ffedd` |
| Multiple Features pixels | 1,442,000 | `898a50a7637f1ed5a8cee2493aaa0e7f4d52795c412f59b0969ec7c3046ee7bd` | `70a1cd033add46614464a8740ddc23c3693765985bde52ccb6b702bff23b64f1` |

The machine-enforced pins live in
`config/tabular-successor-corpus-v1.json`; the fetcher refuses a future
archive or selected stream that differs from them.

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
