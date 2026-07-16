# STX1 token side-channel decision

## Purpose and gate

STX1 wins by leaving literals and two-byte token references interleaved before
Zstandard. STX2 showed that replacing that layout with explicit literal runs
destroyed too much context. This experiment asks a narrower question: can the
varying byte after each STX1 marker be compressed in its own channel while the
remaining stream keeps its original order?

The gate charged complete reversible payload bytes, including a second
Zstandard frame and all boundary metadata. A representation could be
integrated only if it:

- beat STX1 and direct zstd-3 materially on at least one declared public
  structured family;
- retained exact comparison fallback, so no selected file could regress;
- reached at least 50 MB/s encode and 100 MB/s decode in the focused native
  representation probe;
- passed malformed-stream, full-frame integrity, and complete public-corpus
  round trips;
- retained a within-run Pareto position after adaptive-v3 integration.

The private holdout remained sealed.

The design is informed by existing separation and transform work rather than
presented as an isolated invention. RFC 8878 specifies separate literal and
sequence sections inside Zstandard blocks. Microsoft's JSZap source-code work
compresses syntax productions, identifiers, and literals in separate streams.
Burrows and Wheeler established the broader pattern of using a reversible
transform to expose a distribution that a following coder can exploit.

Primary references:

- RFC 8878, “Zstandard Compression and the `application/zstd` Media Type,”
  https://www.rfc-editor.org/rfc/rfc8878.html
- Meyerovich and Livshits, “JSZap: Compressing JavaScript Code,” OOPSLA 2010,
  https://www.microsoft.com/en-us/research/publication/jszap-compressing-javascript-code/
- Burrows and Wheeler, “A Block-sorting Lossless Data Compression Algorithm,”
  Digital SRC Research Report 124, 1994,
  https://www.cs.jhu.edu/~langmea/resources/burrows_wheeler.pdf

## Representation

The retained raw-channel representation starts from the unchanged STX1
dictionary and body:

- the skeleton keeps the dictionary and every body byte except the byte after
  each `0xff` marker;
- the side channel stores those removed bytes in order, including both token
  IDs and the `0xfe` escaped-marker code;
- skeleton and side channels are compressed independently with Zstandard level
  3;
- a 16-byte header stores transformed size, skeleton size, and the compressed
  skeleton boundary;
- the decoder consumes one side byte for every skeleton marker and expands the
  referenced token directly into final output, without rebuilding STX1;
- the adaptive selector tries this representation only for a JSON-looking
  document and retains it only when its complete payload is smaller than the
  interleaved STX1 payload.

The native parser validates dictionary structure, duplicate tokens, marker and
side-channel counts, token-code bounds, declared sizes, output bounds, and
complete side consumption. The outer adaptive-v3 frame retains per-segment
CRC32 and whole-file SHA-256 verification.

## Bounded representation sweep

The reproducible probe is `scripts/probe-token-channels.py`. It tested three
reversible, same-length side representations on all five public structured
files: raw token IDs, byte deltas, and move-to-front ranks.

| File | STX1 bytes | Raw channel | Delta channel | MTF channel | Raw minus STX1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| sqlite3.h | 169,203 | 174,183 | 179,975 | 176,098 | +4,980 |
| sqlite3.c | 2,349,091 | 2,409,273 | 2,460,320 | 2,419,826 | +60,182 |
| sqlite3ext.h | 7,083 | 7,107 | 7,218 | 7,193 | +24 |
| shell.c | 294,721 | 306,022 | 310,712 | 306,315 | +11,301 |
| Chinook JSON | 170,430 | **164,515** | 165,145 | 165,694 | **-5,915** |
| **Total** | **2,990,528** | **3,061,100** | **3,123,370** | **3,075,126** | **+70,572** |

Raw IDs won the bounded sweep. Channelization is not a general STX1 successor:
it loses on every C/source file. On the declared JSON family, however, it is
5,915 bytes or 3.47% smaller than STX1 and 10,976 bytes or 6.26% smaller than
direct zstd-3 after all channel metadata and both Zstandard frames.

The final focused native probe measured the JSON path at 97.49 MB/s encode and
495.63 MB/s decode. The interleaved STX1 encode in the same probe measured
114.63 MB/s; the new representation still cleared the absolute gate. These are
focused local measurements, not isolated product claims.

## Integrated public result

The clean tested implementation revision was
`12b7ebffe685e966d3a183971b92da94aad86147`. The calibrated persistent-worker
run used one warmup, two measured repetitions, a 250 ms operation target, and
four codecs. It completed all 64 measured round trips without a failure.

Canonical local evidence:

- `runs/adaptive-v3-token-channel-public-clean/results.json`

| Codec | Compressed bytes | Compressed % | Compress MB/s | Decompress MB/s | Pareto |
| --- | ---: | ---: | ---: | ---: | --- |
| zstd-9 | 6,386,970 | 35.8978 | 18.69 | 254.81 | yes |
| adaptive-v3 | **6,747,896** | **37.9264** | **32.84** | **170.72** | **yes** |
| zstd-3 | 6,866,359 | 38.5922 | 83.22 | 245.61 | yes |
| adaptive-v2 | 6,866,648 | 38.5939 | 85.51 | 225.77 | yes |

Only Chinook JSON selected the new recipe. Its complete adaptive frame was
164,578 bytes. The four source files retained interleaved STX1, while the
database, PDF, and ZIP retained their previous routes.

The new aggregate is exactly 5,915 bytes smaller than the prior 6,753,811-byte
adaptive-v3 milestone. It is 118,463 bytes or 1.73% smaller than direct zstd-3,
up from the prior 1.64% advantage. It remains 360,926 bytes or 5.65% larger than
zstd-9.

The run began at load averages 4.89, 39.33, and 55.23 on ten logical CPUs.
Adaptive-v3 compression and decompression CVs were 12.19% and 12.63%.
Therefore sizes, round trips, routing, and within-run Pareto classification are
accepted, while absolute throughput is retained only as local evidence.

## Decision

Keep the raw token side channel as JSON-qualified adaptive-v3 recipe 4. It
passes its complete-size, focused speed, corruption, round-trip, and integrated
Pareto gates. Keep exact payload comparison as the final selector: a JSON prefix
authorizes the extra candidate encode but never forces the recipe.

Do not generalize the channel to C/source files, open the private holdout, or
claim a general market lead. The evidence comes from one licensed JSON file and
one generated regression fixture. The next ratio milestone should expand
licensed JSON diversity and determine whether the 5,915-byte gain survives
unseen schemas before any holdout or promotion decision.
