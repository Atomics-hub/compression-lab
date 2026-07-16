# Multi-order probability-model decision

## Purpose and gate

The dual-context XOR experiment showed that a correct top prediction is not a
complete probability distribution. This experiment tested the next seam: a
bounded adaptive model whose prequential log-loss estimates the smallest
payload an ideal entropy coder could approach before any new frame or decoder
surface was added.

The integration gate was declared before implementation. After conservative
coder allowance, the model had to beat direct Zstandard level 3 on every
intended file, beat incumbent STX1 in aggregate on structured text, scan at
least 50 MB/s, and remain below 128 MB peak RSS. Arithmetic or ANS integration
was allowed only if all conditions passed. The private holdout remained sealed.

The model draws on four primary lines of work without claiming that their
individual techniques are new:

- Cleary and Witten, “Data Compression Using Adaptive Coding and Partial
  String Matching,” IEEE Transactions on Communications, 1984,
  https://doi.org/10.1109/TCOM.1984.1096090
- Krichevsky and Trofimov, “The Performance of Universal Encoding,” IEEE
  Transactions on Information Theory, 1981,
  https://doi.org/10.1109/TIT.1981.1056331
- Willems, Shtarkov, and Tjalkens, “The Context-Tree Weighting Method: Basic
  Properties,” IEEE Transactions on Information Theory, 1995,
  https://doi.org/10.1109/18.382012
- Duda, “Asymmetric Numeral Systems,” 2009,
  https://arxiv.org/abs/0902.0271

## Candidate

The temporary optimized Rust prototype was a hierarchical sparse byte model:

- order zero used a 256-symbol Krichevsky-Trofimov-style half-count prior;
- byte contexts were evaluated from low to high order, with the final sweep
  using orders one through eight;
- every context mixed its retained observations with the complete lower-order
  distribution, so every step remained normalized instead of emitting only a
  top prediction;
- fixed hashed tables retained up to eight frequent symbols per context, used
  deterministic collision replacement, and rescaled saturating counts;
- all state reset every 1 MiB to preserve adaptive-v3 block locality;
- the best configuration used eight 131,072-entry tables and a hierarchical
  smoothing strength of 32.

The model emitted no bytes. It accumulated `-log2(p(actual))` for every source
byte. Projected payload was deliberately conservative:

    ceil(log_loss_bits / 8)
    + ceil(0.5% coder allowance)
    + 32 bytes per 1 MiB block
    + 24 bytes of stream metadata

This is a decision estimate, not an implemented codec result. The prototype's
three tests verified normalized distributions, deterministic finite scores,
and exact block-reset behavior.

## Bounded ablation

Eight configurations were evaluated on the five public structured files. No
private data or open-ended parameter search was used.

| Context orders | Table bits | Strength | Projected structured bytes |
| --- | ---: | ---: | ---: |
| 1,2,4,8 | 16 | 4 | 3,555,525 |
| 1,2,4,8 | 16 | 16 | 3,423,173 |
| 1,2,4,8 | 17 | 16 | 3,366,334 |
| 1,2,3,4,6,8 | 16 | 16 | 3,174,581 |
| 1,2,3,4,6,8 | 17 | 16 | 3,162,772 |
| 1,2,3,4,6,8 | 17 | 32 | 3,146,548 |
| 1 through 8 | 17 | 32 | **3,075,074** |
| 1 through 8 | 18 | 32 | 3,079,556 |

Intermediate orders mattered more than another doubling of table capacity.
The 18-bit tables slightly regressed, so the sweep stopped at the declared
capacity boundary.

## Best model result

| File | Input | Direct zstd-3 | STX1 | Entropy bytes | Projected bytes | Scan MB/s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| SQLite ZIP | 2,945,929 | 2,946,008 | — | 2,978,122 | 2,993,133 | 1.497 |
| Chinook SQLite | 1,067,008 | 379,634 | — | 462,150 | 464,549 | 1.684 |
| NOAA PDF | 452,715 | 437,216 | — | 445,480 | 447,764 | 0.878 |
| sqlite3.h | 690,838 | 179,736 | 169,199 | 144,999 | 145,780 | 1.032 |
| sqlite3.c | 9,514,279 | 2,434,606 | 2,349,087 | 2,374,229 | 2,386,445 | 1.453 |
| sqlite3ext.h | 39,175 | 7,358 | 7,811 | 6,749 | 6,839 | 1.804 |
| shell.c | 1,184,651 | 306,310 | 294,717 | 323,663 | 325,370 | 1.466 |
| Chinook JSON | 1,897,482 | 175,491 | 170,943 | 209,504 | 210,640 | 2.860 |
| **Total** | **17,792,077** | **6,866,359** | — | **6,944,896** | **6,980,520** | **1.497 aggregate** |

On only the five structured files, idealized entropy was 3,059,144 bytes and
the projected payload was 3,075,074 bytes. That projection is 28,427 bytes, or
0.92%, smaller than their 3,103,501-byte direct zstd-3 total. It is still
83,317 bytes, or 2.78%, larger than STX1's 2,991,757 bytes.

Across the complete public corpus, projected output was 114,161 bytes, or
1.66%, larger than direct zstd-3. Peak RSS was 59,326,464 bytes, within the
memory gate, but the complete 17.8 MB pass took 11.88 seconds. Aggregate scan
throughput was about 1.50 MB/s, more than 30 times below the integration gate.

The candidate beat direct zstd-3 on `sqlite3.h`, `sqlite3.c`, and
`sqlite3ext.h`, but lost on JSON, `shell.c`, and all three binary/document
families. A perfect candidate-versus-zstd selector would produce 6,783,723
bytes, but the existing adaptive-v3 result is already smaller at 6,753,811
bytes. Combining this model with the incumbent could expose roughly 24 KB of
additional structured-file oracle gain, far too little to fund its speed cost.

## Decision

Reject this multi-order model for entropy-coder and frame integration. The
model passed its mathematical invariants and memory limit but failed the
incumbent-ratio, per-file, complete-corpus, and throughput gates. No arithmetic
or ANS implementation was added, no private holdout was opened, and the
temporary probe was removed.

The useful evidence is narrower. Full distributions recover substantially more
information than the rejected top-one residual encodings, and intermediate
orders are valuable. But a generic byte-context hierarchy duplicates mature
LZ modelling at prohibitive cost and still loses to the structured token
transform. The next candidate should not simply add more context depth or
larger hash tables. It needs a cheaper representation-specific probability
seam or a materially different source model with a gate based on incremental
gain over STX1, not merely over direct zstd-3.

After removing the experimental binary, the production tree matched its prior
state. All 30 Python tests passed with `ResourceWarning` promoted to an error,
and all three optimized Rust tests passed, including the existing frame and
stream corruption checks.
