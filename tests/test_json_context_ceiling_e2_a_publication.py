from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile


ROOT = Path(__file__).resolve().parents[1]
PUBLISHER = ROOT / "scripts" / "publish-json-context-ceiling-e2-a.py"
VERIFIER = ROOT / "scripts" / "verify-json-context-ceiling-e2-a-publication.py"
RENDERER = ROOT / "scripts" / "render-json-context-ceiling-e2-a.py"
COMMIT = "45ca664d77e1a8a2f7ac057914e3ee034d683a30"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(root: Path) -> dict:
    artifact = root / "artifact"
    measurement = artifact / "measurement"
    publication = artifact / "publication"
    measurement.mkdir(parents=True)
    containers = measurement / "containers"
    containers.mkdir()
    config = json.loads(
        (ROOT / "config" / "json-context-ceiling-e2-a-v1.json").read_bytes()
    )
    item_ids = [row["id"] for row in config["items"]]
    container_payloads = {
        method["id"]: method["id"].encode() + bytes([index]) * (100 + index)
        for index, method in enumerate(config["methods"])
    }
    complete_bytes = {
        method: len(payload) for method, payload in container_payloads.items()
    }
    container_digests = {
        method: hashlib.sha256(payload).hexdigest()
        for method, payload in container_payloads.items()
    }
    for method, payload in container_payloads.items():
        (containers / f"{method}-r1.axe2o").write_bytes(payload)
    archive_rows = {
        (method["id"], item): {
            "bytes": 100000 + index,
            "sha256": hashlib.sha256(f"{method['id']}:{item}".encode()).hexdigest(),
        }
        for method in config["methods"]
        for index, item in enumerate(item_ids)
    }
    trial_rss = 300 * 1024 * 1024
    stage_one = [
        {
            "method_id": method["id"],
            "method": method["method"],
            "item_id": item,
            "repetition": 1,
            "stage": "stage_one",
            "source_bytes": next(
                row["bytes"] for row in config["items"] if row["id"] == item
            ),
            "source_sha256": next(
                row["sha256"] for row in config["items"] if row["id"] == item
            ),
            "archive": archive_rows[(method["id"], item)],
            "compress": {"peak_rss_bytes": trial_rss},
            "decompress": {"peak_rss_bytes": trial_rss},
            "restored_bytes": next(
                row["bytes"] for row in config["items"] if row["id"] == item
            ),
            "restored_sha256": next(
                row["sha256"] for row in config["items"] if row["id"] == item
            ),
            "exact": True,
        }
        for method in config["methods"]
        for item in item_ids
    ]
    selected = ["zpaq-5-m54", "zpaq-5-m510"]
    for method in selected:
        (containers / f"{method}-r2.axe2o").write_bytes(container_payloads[method])
    confirmation = [
        {
            "method_id": method,
            "method": next(
                row["method"] for row in config["methods"] if row["id"] == method
            ),
            "item_id": item,
            "repetition": 2,
            "stage": "confirmation",
            "source_bytes": next(
                row["bytes"] for row in config["items"] if row["id"] == item
            ),
            "source_sha256": next(
                row["sha256"] for row in config["items"] if row["id"] == item
            ),
            "archive": archive_rows[(method, item)],
            "compress": {"peak_rss_bytes": trial_rss},
            "decompress": {"peak_rss_bytes": trial_rss},
            "restored_bytes": next(
                row["bytes"] for row in config["items"] if row["id"] == item
            ),
            "restored_sha256": next(
                row["sha256"] for row in config["items"] if row["id"] == item
            ),
            "exact": True,
        }
        for method in selected
        for item in item_ids
    ]
    method_summaries = [
        {
            "method_id": method["id"],
            "maximum_block_mib": method["maximum_block_mib"],
            "complete_container": {
                "path": f"containers/{method['id']}-r1.axe2o",
                "bytes": complete_bytes[method["id"]],
                "sha256": container_digests[method["id"]],
            },
            "gain_vs_e1_kanzi_basis_points": (
                config["e1_fixed_reference"]["kanzi_complete_bytes"]
                - complete_bytes[method["id"]]
            )
            * 10000
            // config["e1_fixed_reference"]["kanzi_complete_bytes"],
            "maximum_compression_peak_rss_bytes": trial_rss,
            "maximum_decompression_peak_rss_bytes": trial_rss,
            "eligible": True,
            "fragile": False,
            "exact": True,
        }
        for method in config["methods"]
    ]
    result = {
        "schema_version": 1,
        "name": config["name"],
        "completed": True,
        "repository_commit": COMMIT,
        "config_sha256": digest(ROOT / "config" / "json-context-ceiling-e2-a-v1.json"),
        "protocol_sha256": digest(
            ROOT
            / "docs"
            / "benchmarks"
            / "2026-07-21-json-context-ceiling-e2-a-protocol.md"
        ),
        "runner_sha256": digest(
            ROOT / "scripts" / "benchmark-json-context-ceiling-e2-a.py"
        ),
        "verifier_sha256": digest(
            ROOT / "scripts" / "verify-json-context-ceiling-e2-a.py"
        ),
        "source_bindings": config["source_run"],
        "e1_reference": {
            "anchor_matched": True,
            "zpaq_510_per_item": [
                {
                    "item_id": item,
                    "artifact_bytes": archive_rows[("zpaq-5-m510", item)]["bytes"],
                    "artifact_sha256": archive_rows[("zpaq-5-m510", item)]["sha256"],
                }
                for item in item_ids
            ],
        },
        "host": {},
        "item_verification": config["items"],
        "stage_one_trials": stage_one,
        "confirmation_trials": confirmation,
        "method_summaries": method_summaries,
        "selected_methods": selected,
        "confirmation_containers": {
            method: {
                "path": f"containers/{method}-r2.axe2o",
                "bytes": complete_bytes[method],
                "sha256": container_digests[method],
            }
            for method in selected
        },
        "decision": {
            "outcome": "advance_component_attribution",
            "best_eligible_method": "zpaq-5-m54",
            "best_eligible_complete_bytes": complete_bytes["zpaq-5-m54"],
            "best_eligible_gain_basis_points": (
                config["e1_fixed_reference"]["kanzi_complete_bytes"]
                - complete_bytes["zpaq-5-m54"]
            )
            * 10000
            // config["e1_fixed_reference"]["kanzi_complete_bytes"],
            "confirmation_passed": True,
        },
        "file_manifest": [
            {
                "path": path.relative_to(measurement).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": digest(path),
            }
            for path in sorted(containers.iterdir())
        ],
        "information_boundary": config["information_boundary"],
        "claim_ceiling": config["claim_ceiling"],
    }
    result_path = measurement / "result.json"
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    subprocess.run(
        [
            sys.executable,
            str(RENDERER),
            "--result",
            str(result_path),
            "--output",
            str(publication),
        ],
        check=True,
    )
    (artifact / "run.log").write_text("run\n")
    (artifact / "verification.log").write_text(
        json.dumps({"decision": result["decision"], "verified": True}, sort_keys=True)
        + "\n"
    )
    members = sorted(
        path
        for path in artifact.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    )
    (artifact / "SHA256SUMS").write_text(
        "".join(
            f"{digest(path)}  ./{path.relative_to(artifact).as_posix()}\n"
            for path in members
        )
    )
    artifact_zip = root / "artifact.zip"
    with zipfile.ZipFile(artifact_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(path for path in artifact.rglob("*") if path.is_file()):
            archive.write(path, path.relative_to(artifact).as_posix())
    artifact_digest = "sha256:" + digest(artifact_zip)
    artifact_size = artifact_zip.stat().st_size
    run_metadata = root / "github-run.json"
    run_metadata.write_text(
        json.dumps(
            {
                "id": 29867575535,
                "head_sha": COMMIT,
                "html_url": "https://github.com/Atomics-hub/compression-lab/actions/runs/29867575535",
                "conclusion": "success",
                "status": "completed",
                "event": "workflow_dispatch",
                "head_branch": "main",
                "name": "E2-A JSON context ceiling",
                "path": ".github/workflows/json-context-ceiling-e2-a.yml",
                "repository": {"full_name": "Atomics-hub/compression-lab"},
                "workflow_id": 317724122,
                "run_attempt": 1,
            }
        )
    )
    artifacts_metadata = root / "github-artifacts.json"
    artifacts_metadata.write_text(
        json.dumps(
            {
                "artifacts": [
                    {
                        "id": 456,
                        "name": "json-context-ceiling-e2-a-29867575535",
                        "size_in_bytes": artifact_size,
                        "digest": artifact_digest,
                        "expired": False,
                        "workflow_run": {"id": 29867575535},
                    }
                ]
            }
        )
    )
    return {
        "root": artifact,
        "zip": artifact_zip,
        "run_metadata": run_metadata,
        "artifacts_metadata": artifacts_metadata,
        "size": artifact_size,
        "digest": artifact_digest,
    }


def publish_fixture(publisher, source: dict, output: Path):
    with mock.patch.object(
        publisher,
        "fetch_github_metadata",
        return_value=(
            source["run_metadata"].read_bytes(),
            source["artifacts_metadata"].read_bytes(),
        ),
    ):
        return publisher.publish(
            artifact_root=source["root"],
            artifact_zip=source["zip"],
            output=output,
            run_id=29867575535,
            run_url="https://github.com/Atomics-hub/compression-lab/actions/runs/29867575535",
            run_head_sha=COMMIT,
            artifact_id=456,
            artifact_name="json-context-ceiling-e2-a-29867575535",
            artifact_size=source["size"],
            artifact_digest=source["digest"],
        )


class JsonContextCeilingE2APublicationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.publisher = load(PUBLISHER, "e2a_publisher")
        cls.verifier = load(VERIFIER, "e2a_publication_verifier")

    def test_publish_and_verify_roundtrip(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = fixture(root)
            output = root / "published"
            receipt = publish_fixture(self.publisher, source, output)
            self.assertEqual(
                receipt,
                self.verifier.verify(output, digest(output / "receipt.json")),
            )
            self.assertEqual(
                receipt["decision"]["outcome"], "advance_component_attribution"
            )

    def test_checksum_tampering_fails(self):
        with tempfile.TemporaryDirectory() as raw:
            source = fixture(Path(raw))
            (source["root"] / "run.log").write_text("tampered\n")
            with self.assertRaisesRegex(ValueError, "member digest differs"):
                self.publisher.verify_checksum_manifest(source["root"])

    def test_publication_tampering_fails(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = fixture(root)
            output = root / "published"
            publish_fixture(self.publisher, source, output)
            (output / "comparison.svg").write_text("tampered")
            with self.assertRaisesRegex(ValueError, "digest differs"):
                self.verifier.verify(output, digest(output / "receipt.json"))

    def test_coordinated_boundary_tampering_fails(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = fixture(root)
            output = root / "published"
            publish_fixture(self.publisher, source, output)
            evidence_path = output / "evidence.json"
            evidence = json.loads(evidence_path.read_bytes())
            evidence["information_boundary"]["fresh_public_validation_status"] = (
                "claimed_unseen"
            )
            evidence_path.write_text(
                json.dumps(evidence, indent=2, sort_keys=True) + "\n"
            )
            receipt_path = output / "receipt.json"
            receipt = json.loads(receipt_path.read_bytes())
            receipt["information_boundary"] = evidence["information_boundary"]
            receipt["published_members"]["evidence.json"] = digest(evidence_path)
            receipt_path.write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n"
            )
            with self.assertRaisesRegex(ValueError, "identity differs"):
                self.verifier.verify(output, digest(receipt_path))

    def test_render_tampering_with_updated_receipt_fails(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = fixture(root)
            output = root / "published"
            publish_fixture(self.publisher, source, output)
            svg = output / "comparison.svg"
            svg.write_text("<svg/>\n")
            receipt_path = output / "receipt.json"
            receipt = json.loads(receipt_path.read_bytes())
            receipt["published_members"]["comparison.svg"] = digest(svg)
            receipt_path.write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n"
            )
            with self.assertRaisesRegex(ValueError, "does not reconstruct"):
                self.verifier.verify(output, digest(receipt_path))

    def test_nested_checksum_manifest_is_not_silently_ignored(self):
        with tempfile.TemporaryDirectory() as raw:
            source = fixture(Path(raw))
            nested = source["root"] / "measurement" / "SHA256SUMS"
            nested.write_text("unbound\n")
            with self.assertRaisesRegex(ValueError, "roster differs"):
                self.publisher.verify_checksum_manifest(source["root"])

    def test_zip_tampering_fails(self):
        with tempfile.TemporaryDirectory() as raw:
            source = fixture(Path(raw))
            with source["zip"].open("ab") as stream:
                stream.write(b"tampered")
            with self.assertRaisesRegex(ValueError, "ZIP size or digest differs"):
                publish_fixture(self.publisher, source, Path(raw) / "published")

    def test_zip_symlink_member_fails_before_roster_comparison(self):
        with tempfile.TemporaryDirectory() as raw:
            source = fixture(Path(raw))
            symlink = zipfile.ZipInfo("unsafe-link")
            symlink.create_system = 3
            symlink.external_attr = 0o120777 << 16
            with zipfile.ZipFile(source["zip"], "a") as archive:
                archive.writestr(symlink, "../../outside")
            with self.assertRaisesRegex(ValueError, "unsafe member"):
                self.publisher.verify_zip_matches_tree(
                    source["zip"],
                    source["root"],
                    source["zip"].stat().st_size,
                    "sha256:" + digest(source["zip"]),
                )

    def test_live_github_metadata_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = fixture(root)
            metadata = json.loads(source["run_metadata"].read_bytes())
            metadata["conclusion"] = "failure"
            source["run_metadata"].write_text(json.dumps(metadata))
            with self.assertRaisesRegex(ValueError, "run metadata differs"):
                publish_fixture(self.publisher, source, root / "published")

    def test_retained_github_metadata_tampering_fails(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = fixture(root)
            output = root / "published"
            publish_fixture(self.publisher, source, output)
            metadata_path = output / "github-run.json"
            metadata = json.loads(metadata_path.read_bytes())
            metadata["conclusion"] = "failure"
            metadata_path.write_text(json.dumps(metadata))
            receipt_path = output / "receipt.json"
            receipt = json.loads(receipt_path.read_bytes())
            receipt["published_members"]["github-run.json"] = digest(metadata_path)
            receipt_path.write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n"
            )
            with self.assertRaisesRegex(ValueError, "run metadata differs"):
                self.verifier.verify(output, digest(receipt_path))

    def test_invalid_external_receipt_digest_fails(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = fixture(root)
            output = root / "published"
            publish_fixture(self.publisher, source, output)
            with self.assertRaisesRegex(ValueError, "digest is invalid"):
                self.verifier.verify(output, "not-a-sha256")

    def test_decision_is_rederived_instead_of_transcribed(self):
        with tempfile.TemporaryDirectory() as raw:
            source = fixture(Path(raw))
            result = json.loads(
                (source["root"] / "measurement" / "result.json").read_bytes()
            )
            result["decision"]["outcome"] = "kill_bounded_level5_lane"
            with self.assertRaisesRegex(ValueError, "decision does not rederive"):
                self.publisher.verify_result_identity(result, COMMIT)

    def test_nonexact_confirmation_is_rejected_by_both_derivations(self):
        with tempfile.TemporaryDirectory() as raw:
            source = fixture(Path(raw))
            result = json.loads(
                (source["root"] / "measurement" / "result.json").read_bytes()
            )
            result["confirmation_trials"][0]["exact"] = False
            config = json.loads(
                (ROOT / "config" / "json-context-ceiling-e2-a-v1.json").read_bytes()
            )
            with self.assertRaisesRegex(ValueError, "exactness differs"):
                self.publisher.derive_decision(result, config)
            with self.assertRaisesRegex(ValueError, "exactness differs"):
                self.verifier.derive_decision(result, config)

    def test_missing_result_section_fails(self):
        with tempfile.TemporaryDirectory() as raw:
            source = fixture(Path(raw))
            result = json.loads(
                (source["root"] / "measurement" / "result.json").read_bytes()
            )
            del result["confirmation_trials"]
            with self.assertRaisesRegex(ValueError, "section roster differs"):
                self.publisher.verify_result_identity(result, COMMIT)

    def test_retained_container_tampering_fails_even_with_updated_receipt(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = fixture(root)
            output = root / "published"
            publish_fixture(self.publisher, source, output)
            container = output / "containers" / "zpaq-5-m54-r1.axe2o"
            container.write_bytes(b"tampered")
            receipt_path = output / "receipt.json"
            receipt = json.loads(receipt_path.read_bytes())
            receipt["published_members"]["containers/zpaq-5-m54-r1.axe2o"] = digest(
                container
            )
            receipt_path.write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n"
            )
            with self.assertRaisesRegex(ValueError, "retained container differs"):
                self.verifier.verify(output, digest(receipt_path))


if __name__ == "__main__":
    unittest.main()
