# Expanded JSON external-validity protocol

## Question

The retained STX1 raw token side channel won on one licensed JSON file. This
experiment asks whether that result survives four previously unseen JSON
families with materially different structure. The private holdout remains
sealed; this is still public engineering evidence, not a market-lead claim.

The source identities, decision gates, and analysis rules below are frozen
before any compression result is measured.

## Frozen public families

One file is drawn from each independent upstream project and pinned to an
upstream commit:

| Family | File | Upstream commit | License | Structural role |
| --- | --- | --- | --- | --- |
| Kubernetes API | `swagger.json` | `1b4e48f52199bcfb28ef6efd60522a082c3e78d0` | Apache-2.0 | deeply nested API schema |
| Unicode CLDR | `likelySubtags.json` | `a79b499916d486dca4b0f74fe423ea457705fdd9` | Unicode-3.0 | localization lookup maps |
| Vega datasets | `movies.json` | `cad85578e232704bb0453544742440038038c6a2` | BSD-3-Clause | row-oriented record array |
| Natural Earth | `ne_110m_admin_0_countries.geojson` | `ca96624a56bd078437bca8184e78163e5039ad19` | public domain | numeric and property-heavy GeoJSON |

The reconstruction config must record immutable raw URLs, SHA-256 digests,
source URLs, categories, and licenses. Corpus import must independently record
each file's byte size and SHA-256 digest.

## Compared representations

For every file, charge complete reversible bytes for:

1. direct Zstandard level 3;
2. interleaved STX1 followed by Zstandard level 3, including its adaptive
   recipe metadata;
3. raw STX1 token side channels, including both Zstandard frames and all
   channel and adaptive metadata;
4. the integrated adaptive-v3 selector;
5. relevant installed market baselines in the calibrated runner: Zstandard
   levels 3 and 9, Brotli levels 5 and 11, gzip level 9, and XZ/LZMA level 9.

The focused representation table is authoritative for the STX1-versus-channel
decision. The calibrated runner is authoritative for integrated routing,
round trips, market comparisons, and within-run Pareto classification.

## Predeclared decision gates

Keep generic JSON qualification only if all of these hold on the four-family
set:

- the raw channel is at least 0.50% smaller than interleaved STX1 in aggregate;
- it is smaller on at least three of four independent families;
- no family is more than 2.00% larger than interleaved STX1;
- focused aggregate encode is at least 50 MB/s and decode is at least
  100 MB/s;
- every focused and integrated round trip passes, corruption checks remain
  active, and adaptive-v3 retains a within-run Pareto position.

If aggregate size wins but the prevalence or worst-family gate fails, restrict
qualification using a cheap, deterministic pre-encode feature only if that
feature is declared from training evidence and then validated without changing
the frozen files. Exact complete-payload comparison remains mandatory after
qualification.

Reject the generic JSON attempt if the aggregate channel is not smaller, fewer
than two families win, or no defensible cheap restriction separates wins from
losses. A rejected or restricted result does not remove the already verified
exact Chinook JSON route unless production correctness regresses.

Throughput is accepted only from a quiet-host run meeting the repository's
load and coefficient-of-variation policy. A noisy run may establish byte sizes,
routing, correctness, and within-run Pareto status, but not a product-speed
claim.

## Analysis discipline

- Do not tune token-channel representation, dictionary limits, or Zstandard
  levels on these files.
- Report aggregate and every family, including losses.
- Do not open or score the private holdout.
- If a qualification rule is explored, report the original generic result
  first and treat any rule as a separately validated selector change.
- Run the full Python, Rust, malformed-stream, corruption, and corpus
  round-trip suites before a keep, restrict, or reject decision is merged.
