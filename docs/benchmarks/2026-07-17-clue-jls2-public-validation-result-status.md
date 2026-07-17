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

## Interim evidence boundary

The retained artifact has not yet been downloaded into the repository because
the current execution environment denied the read-only GitHub artifact
download after reaching its approval-usage limit. Therefore this interim
status records no compressed-byte, speed, memory, family, or individual-gate
numbers from the inaccessible bundle.

Until the exact artifact is checksum-verified and imported:

- the public result is only **complete frozen no-pass, exact numbers pending**;
- the existing 18.08% ratio lead remains development evidence only;
- unavailable specialists remain unavailable, not Atompress wins;
- the private holdout remains sealed; and
- no category-win, universal, market-leading, world-best, or state-of-the-art
  claim is permitted.

## Immutable import procedure

The importer at `scripts/import-clue-jls2-public-validation.py` is pinned to the
repository, workflow run, head commit, artifact name, and expected no-pass
result. It verifies every retained file against `SHA256SUMS`, rejects unlisted
files and symlinks, verifies the publication bundle and decision source
bindings, compares the frozen gates byte-for-byte, refuses replacement, and
copies through a verified staging directory before an atomic rename.

After read-only artifact access is explicitly approved, retrieve GitHub's
artifact ID and digest, download the artifact, then run:

```bash
python scripts/import-clue-jls2-public-validation.py \
  --evidence /tmp/clue-score-29606109504/clue-jls2-public-validation-v1-29606109504 \
  --artifact-id ARTIFACT_ID \
  --artifact-digest sha256:ARTIFACT_DIGEST
```

The imported publication report and SVG—not the workflow badge—will become the
authoritative numeric result. The README, category matrix, and standardized
comparison chart must then be synchronized to that bundle without changing any
frozen score input or consumed-range policy.
