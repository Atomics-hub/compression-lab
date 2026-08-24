from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
ACTIVE_WORKFLOWS = (
    ".github/workflows/ci.yml",
    ".github/workflows/fuzz.yml",
    ".github/workflows/release.yml",
)
ACTION_PINS = {
    "actions/checkout": "d23441a48e516b6c34aea4fa41551a30e30af803",
    "actions/setup-python": "ece7cb06caefa5fff74198d8649806c4678c61a1",
    "actions/upload-artifact": "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
    "actions/download-artifact": "3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c",
    "docker/setup-qemu-action": "96fe6ef7f33517b61c61be40b68a1882f3264fb8",
    "pypa/gh-action-pypi-publish": "dc37677b2e1c63e2034f94d8a5b11f265b73ba33",
}


class ProductionSecurityGateTests(unittest.TestCase):
    def setUp(self) -> None:
        if not (ROOT / ".github/workflows").is_dir():
            self.skipTest("GitHub workflows are not included in the sdist")

    def test_active_workflows_pin_every_external_action(self) -> None:
        pattern = re.compile(r"(?m)^\s*-?\s*uses:\s+([^@\s]+)@([^\s#]+)")
        for relative in ACTIVE_WORKFLOWS:
            workflow = (ROOT / relative).read_text(encoding="utf-8")
            matches = pattern.findall(workflow)
            self.assertTrue(matches, relative)
            for action, revision in matches:
                if action.startswith("./"):
                    continue
                self.assertIn(action, ACTION_PINS, f"{relative}: {action}")
                self.assertEqual(
                    revision,
                    ACTION_PINS[action],
                    f"{relative}: {action}",
                )

    def test_dependency_audit_is_pinned_and_complete(self) -> None:
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(
            encoding="utf-8"
        )
        audit_job = workflow.split("  dependency-audit:\n", 1)[1].split(
            "\n  package:\n", 1
        )[0]
        required = (
            "name: Dependency vulnerability audit",
            "timeout-minutes: 25",
            "python -m pip install pip-audit==2.10.1",
            "python -m pip_audit . --strict",
            "cargo install cargo-audit --version 0.22.2 --locked",
            "cargo audit --file native/Cargo.lock",
            "cargo audit --file native-dense/Cargo.lock",
        )
        for text in required:
            self.assertEqual(audit_job.count(text), 1, text)


if __name__ == "__main__":
    unittest.main()
