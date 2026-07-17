# CLUE-LDS JLS2 public-validation result status

## Verified workflow outcome

The single authorized acquisition and score completed in
[GitHub Actions run 29606109504](https://github.com/Atomics-hub/compression-lab/actions/runs/29606109504)
at merge commit `b9cdc9e797b36709ba4c17c23a4c6585670254e3`.

The final workflow state proves that the exact standards/candidate benchmark,
pinned PBC specialist benchmark, frozen evaluator, publication renderer,
checksum sealer, and artifact upload all completed. The final enforcement step
returned exit code 2, which the frozen workflow reserves for a complete valid
`not_passed` decision. This was not an infrastructure failure.

Both CLUE validation ranges are consumed. They will never be reused as fresh
evidence, and this first score will not be tuned or rerun.

## Checksum-verified imported result

The exact artifact was retrieved after explicit approval and imported without
mutation. GitHub reports artifact ID `8418445259`, name
`clue-jls2-public-validation-v1-29606109504`, and digest
`sha256:03d39e93c037b25397fa6750d2d4d30da08eedafcc9ef7b8f0c66b140b6047a3`.
The importer verified all 42 retained files against `SHA256SUMS`, the frozen
gates byte-for-byte, publication source bindings, workflow identity, head
commit, result, and artifact provenance before its atomic copy.

The first score is a decisive ratio result and an overall product-gate
no-pass:

- 96,934,483 source bytes became 489,591 complete JLS2 bytes;
- Brotli-11 was the strongest eligible standard at 1,040,990 bytes, making JLS2
  52.97% smaller;
- the two family gains were 48.31% against Brotli-11 and 54.50% against
  7-Zip-9;
- aggregate compression was 109.58 MB/s and standalone decompression was
  431.36 MB/s;
- compression peak RSS was 322,994,176 bytes;
- standalone decompression peak RSS was 651,517,952 bytes (621.3 MiB); and
- every frozen gate passed except the 512 MiB decompression-memory gate.

The authoritative full result is
[`runs/clue-jls2-public-validation-v1/publication/README.md`](../../runs/clue-jls2-public-validation-v1/publication/README.md),
and the adjacent
[`runs/clue-jls2-public-validation-v1-import.json`](../../runs/clue-jls2-public-validation-v1-import.json)
is the immutable import receipt.

## Evidence boundary

This supports a category-scoped public-validation **ratio** result on two
previously unopened CC-BY-4.0 CLUE-LDS temporal ranges. It does not support a
complete category win because the frozen memory gate failed. The private
holdout remains sealed, and independent reproduction has not occurred.

Unavailable or ineligible specialists remain visible in the publication chart
and are not Atompress/Axiom wins. Therefore no universal, market-leading,
world-best, strongest-ratio, or state-of-the-art claim is permitted.

The immutable protocol used the earlier public brand Atompress. The checked-in
artifact is not rewritten during the transition to the Axiom product name;
JLS2 remains the technical format identifier.

## Next decision

Preserve this no-pass and both consumed ranges. Diagnose the decoder RSS miss
only on fresh licensed development families. A successor must keep the ratio,
speed, exactness, integrity, and fallback wins while reducing peak decode
memory below the frozen product boundary, then face different untouched public
validation families.
