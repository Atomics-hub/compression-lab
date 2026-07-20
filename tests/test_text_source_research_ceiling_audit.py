import json
from pathlib import Path
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
AUDIT = (
    REPOSITORY
    / "docs"
    / "benchmarks"
    / "2026-07-17-text-source-research-ceiling-audit.md"
)
GATES = REPOSITORY / "config" / "text-source-gates-v1.json"


class TextSourceResearchCeilingAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = AUDIT.read_text(encoding="utf-8")
        cls.lower = cls.text.lower()
        cls.gates = json.loads(GATES.read_text(encoding="utf-8"))

    def test_every_declared_ceiling_candidate_has_an_exact_admission_state(
        self,
    ) -> None:
        for name in ("zpaq", "paq8px", "cmix", "nncp"):
            self.assertIn(f"| {name}", self.lower)
        self.assertIn("bf7b658fdcfc045a892920d01e830e6c6a790c21", self.text)
        self.assertIn("c443679c0773b8ae5b05423827804063d82ae7a8", self.text)
        self.assertIn("nncp-2024-06-05.tar.gz", self.text)
        self.assertIn("requires a larger isolated host", self.lower)

    def test_resource_reduced_runs_cannot_be_mislabeled_as_absolute_ceiling(
        self,
    ) -> None:
        self.assertIn("cannot stand in for `-12L`", self.text)
        self.assertIn("exactly 32 GiB", self.text)
        self.assertIn("18 GiB peak RSS", self.text)
        self.assertIn("unavailable—not as Axiom wins", self.text)

    def test_complete_accounting_and_evidence_boundaries_are_mandatory(self) -> None:
        for phrase in (
            "count every output byte",
            "exact restoration",
            "byte-identical",
            "public validation and private holdout remain sealed",
            "same-host speed rows",
            "dictionary, tokenizer, weights, or model state",
            "pending_second_host_decode",
            "path/size/SHA-256 manifest",
        ):
            self.assertIn(phrase, self.text)

    def test_execution_plan_keeps_pending_rows_from_becoming_wins(self) -> None:
        self.assertIn("prepare-text-source-research-ceiling-execution.py", self.text)
        self.assertIn("immutable 35-task execution plan", self.text)
        self.assertIn("28 formal tasks", self.text)
        self.assertIn("Axiom outcome: untested", self.text)
        self.assertIn("pre-execution lock, not a benchmark result", self.text)
        self.assertIn("verify-text-source-research-ceiling-plan.py", self.text)
        self.assertIn("recomputes all 35 tasks byte-for-byte", self.text)
        self.assertIn("validate-text-source-research-ceiling-toolchain.py", self.text)
        self.assertIn("benchmark-text-source-research-ceiling.py", self.text)
        self.assertIn("verify-text-source-research-ceiling-run.py", self.text)
        self.assertIn("verify-text-source-research-second-host-decode.py", self.text)
        self.assertIn("aggregate-text-source-research-ceiling.py", self.text)
        self.assertIn("verify-text-source-research-ceiling-aggregate.py", self.text)
        self.assertIn("publish-text-source-research-ceiling.py", self.text)
        self.assertIn("verify-text-source-research-ceiling-publication.py", self.text)
        self.assertIn("prepare-local-text-source-research-toolchain.py", self.text)
        self.assertIn("prepare-external-text-source-research-toolchain.py", self.text)
        self.assertIn("cumulative for each profile and track family", self.text)
        self.assertIn("all four declared host classes and all 35 planned tasks", self.text)
        self.assertIn("speed and RSS explicitly host-scoped", self.text)
        self.assertIn("all 15 practical rows, all five", self.text)
        self.assertIn("`Axiom beats?`", self.text)
        self.assertIn("tool availability alone", self.text)
        self.assertIn("zero Axiom wins", self.text)

    def test_kanzi_leader_is_understood_as_transform_plus_context_mixing(self) -> None:
        self.assertIn("EXE+RLT+TEXT+UTF+DNA", self.text)
        self.assertIn("TPAQX", self.text)
        self.assertIn("more than wrapping a mainstream LZ codec", self.text)

    def test_machine_readable_ceiling_matches_the_resource_audit(self) -> None:
        candidates = {
            row["codec_id"]: row
            for row in self.gates["baseline_tiers"]["research_ceiling"]
        }
        zpaq = candidates["zpaq-5"]
        self.assertEqual(zpaq["source_archive_bytes"], 1_000_646)
        self.assertEqual(
            zpaq["source_archive_sha256"],
            "e85ec2529eb0ba22ceaeabd461e55357ef099b80f61c14f377b429ea3d49d418",
        )
        self.assertEqual(
            zpaq["build_policy"]["commands"],
            [["make", "zpaq", "CXX=$CXX", "CXXFLAGS=-O3"]],
        )
        command = zpaq["deterministic_command_policy"]
        self.assertEqual(command["staged_input_name"], "input.bin")
        self.assertEqual(command["staged_input_mtime_utc"], "2000-01-01T00:00:00Z")
        self.assertIn("510", command["compression_arguments"])
        self.assertIn("20000101000000", command["compression_arguments"])
        self.assertIn("byte-identical", self.lower)
        self.assertEqual(candidates["paq8px-forcetext"]["version"], "v216")
        self.assertEqual(
            candidates["paq8px-forcetext"]["tag_commit"],
            "bf7b658fdcfc045a892920d01e830e6c6a790c21",
        )
        self.assertIn("-12L", candidates["paq8px-forcetext"]["resource_policy"])
        paq8px = candidates["paq8px-forcetext"]
        self.assertIn("-12L", paq8px["absolute_ceiling_commands"]["compress"])
        self.assertIn("-forcetext", paq8px["absolute_ceiling_commands"]["compress"])
        self.assertIn("-11L", paq8px["local_resource_screen_commands"]["compress"])
        self.assertEqual(paq8px["external_asset_policy"]["allowed"], [])
        self.assertEqual(
            paq8px["build_policy"]["commands"][0][0:6],
            ["cmake", "-S", ".", "-B", "build", "-DCMAKE_BUILD_TYPE=Release"],
        )
        self.assertIn("-DNATIVECPU=OFF", paq8px["build_policy"]["commands"][0])
        self.assertEqual(
            set(paq8px["external_asset_policy"]["prohibited_repository_assets"]),
            {"build/english.dic", "build/english.emb", "build/english.exp"},
        )
        self.assertEqual(candidates["cmix"]["version"], "v21")
        self.assertEqual(
            candidates["cmix"]["tag_commit"],
            "c443679c0773b8ae5b05423827804063d82ae7a8",
        )
        cmix = candidates["cmix"]
        self.assertIn("-O3", cmix["portable_build_policy"])
        self.assertIn("incompatible", cmix["portable_build_policy"])
        self.assertEqual(
            cmix["build_policy"]["commands"],
            [["make", "cmix", "CC=$CXX", "LFLAGS=-std=c++14 -Wall -O3"]],
        )
        dictionary = cmix["required_decoder_assets"][0]
        self.assertEqual(dictionary["bytes"], 411_996)
        self.assertEqual(
            dictionary["sha256"],
            "4c8568cca9343b9a6212477880f56f8efd162f8784224a25edd043097d36215a",
        )
        self.assertEqual(
            {row["path"] for row in cmix["prohibited_assets"]},
            {"dictionary/new_article_order", "external precomp-cpp output"},
        )
        nncp = candidates["nncp"]
        self.assertEqual(nncp["version"], "3.3")
        self.assertEqual(nncp["source_archive_bytes"], 1_180_969)
        self.assertEqual(
            nncp["source_archive_sha256"],
            "7b4be2a5871186b82cd5f1c6137a8f6fed0d0c6b2bb281793db1f0be65831119",
        )
        self.assertEqual(
            nncp["build_policy"]["commands"],
            [["make", "nncp", "CC=$CC"]],
        )
        self.assertEqual(
            nncp["bundled_runtime_identity"]["cpu_library"]["sha256"],
            "1836cdfde987885e542cb88847cc58c9abefb0ef59a511ea9540dcbe46ac6d3e",
        )
        self.assertEqual(
            nncp["bundled_runtime_identity"]["cuda_library"]["sha256"],
            "ea9ee53d217a673e8547dddbfe8253b9c9ea4ec18ad86c7bd939ac2572f7999e",
        )
        wikimedia_command = nncp["absolute_ceiling_commands"]["wikimedia"][
            "compress"
        ]
        source_command = nncp["absolute_ceiling_commands"]["source"]["compress"]
        self.assertIn("enwik9", wikimedia_command)
        self.assertIn("16384,512", wikimedia_command)
        self.assertNotIn("--preprocess", source_command)
        self.assertIn("123", source_command)
        self.assertEqual(
            set(nncp["self_contained_archive_policy"]["prohibited_options"]),
            {"--dict", "--load_coefs", "--encode_only", "--max_size"},
        )
        self.assertIn("second-host exact decode", nncp["determinism_and_portability_gate"])
        self.assertIn("2.8 days", nncp["resource_policy"])
        budget = self.gates["research_budget"]
        self.assertEqual(budget["maximum_local_peak_rss_gib"], 18.0)
        self.assertEqual(budget["installed_local_memory_gib"], 32.0)
        self.assertEqual(len(budget["full_ceiling_external_host_required_for"]), 3)


if __name__ == "__main__":
    unittest.main()
