from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUST_VERSION = "1.96.0"


class RustToolchainBindingTests(unittest.TestCase):
    def test_repository_toolchain_is_exact_and_complete(self) -> None:
        toolchain = (ROOT / "rust-toolchain.toml").read_text(encoding="utf-8")
        self.assertRegex(
            toolchain, rf'(?m)^channel = "{re.escape(RUST_VERSION)}"$'
        )
        self.assertRegex(toolchain, r'(?m)^profile = "minimal"$')
        self.assertRegex(
            toolchain,
            r'(?m)^components = \["clippy", "rustfmt"\]$',
        )

    def test_wheel_bootstrap_and_sdist_use_the_same_pin(self) -> None:
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        bootstrap_versions = re.findall(
            r"--default-toolchain ([0-9]+\.[0-9]+\.[0-9]+)", pyproject
        )
        self.assertTrue(bootstrap_versions)
        self.assertEqual(set(bootstrap_versions), {RUST_VERSION})
        section_parts = re.split(r"(?m)^\[([^]]+)\]\s*$", pyproject)
        sections = dict(zip(section_parts[1::2], section_parts[2::2]))
        global_environment = re.search(
            r"(?m)^environment = \{([^}]*)\}$",
            sections["tool.cibuildwheel"],
        )
        self.assertIsNotNone(global_environment)
        self.assertIn(
            f'RUSTUP_TOOLCHAIN = "{RUST_VERSION}"',
            global_environment.group(1),  # type: ignore[union-attr]
        )
        for section_name, body in sections.items():
            if not section_name.startswith("tool.cibuildwheel."):
                continue
            platform_environment = re.search(
                r"(?m)^environment = \{([^}]*)\}$", body
            )
            if platform_environment is None:
                continue
            self.assertIn(
                f'RUSTUP_TOOLCHAIN = "{RUST_VERSION}"',
                platform_environment.group(1),
                section_name,
            )
        manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
        self.assertEqual(
            manifest.splitlines().count("include rust-toolchain.toml"),
            1,
        )


if __name__ == "__main__":
    unittest.main()
