from __future__ import annotations

import bz2
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build-text-source-corpora.py"
RULES = ROOT / "config" / "text-source-path-rules-v1.json"


def load_module():
    specification = importlib.util.spec_from_file_location("text_source_builders", SCRIPT)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


BUILDERS = load_module()
U64 = struct.Struct("<Q")


def write_tar(path: Path, rows: list[tuple[str, bytes]], *, reverse: bool = False) -> None:
    ordered = list(reversed(rows)) if reverse else rows
    with tarfile.open(path, "w:xz") as archive:
        for name, content in ordered:
            member = tarfile.TarInfo(name)
            member.size = len(content)
            member.mtime = 123456 if reverse else 0
            member.uid = 501 if reverse else 0
            member.mode = 0o777 if reverse else 0o644
            archive.addfile(member, io.BytesIO(content))


def decode_source_bundle(path: Path) -> tuple[list[tuple[str, bytes]], bytes]:
    encoded = path.read_bytes()
    position = len(BUILDERS.SOURCE_MAGIC)
    count = U64.unpack_from(encoded, position)[0]
    position += U64.size
    rows = []
    for _ in range(count):
        path_size = U64.unpack_from(encoded, position)[0]
        position += U64.size
        name = encoded[position : position + path_size].decode("utf-8")
        position += path_size
        content_size = U64.unpack_from(encoded, position)[0]
        position += U64.size
        content = encoded[position : position + content_size]
        position += content_size
        rows.append((name, content))
    digest = encoded[position : position + 32]
    position += 32
    if position != len(encoded):
        raise AssertionError("trailing source bundle bytes")
    return rows, digest


def wiki_xml(pages: str, declaration: str = "") -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        + declaration
        + '<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">'
        + pages
        + "</mediawiki>"
    ).encode("utf-8")


def page(
    page_id: int,
    revision_id: int,
    title: str,
    text: str,
    *,
    namespace: int = 0,
    redirect: bool = False,
) -> str:
    redirect_element = '<redirect title="Elsewhere" />' if redirect else ""
    return (
        f"<page><title>{title}</title><ns>{namespace}</ns><id>{page_id}</id>"
        f"{redirect_element}<revision><id>{revision_id}</id>"
        f'<text xml:space="preserve">{text}</text></revision></page>'
    )


def decode_wiki_bundle(path: Path) -> tuple[list[tuple[int, int, str, bytes]], bytes]:
    encoded = path.read_bytes()
    position = len(BUILDERS.WIKIMEDIA_MAGIC)
    count = U64.unpack_from(encoded, position)[0]
    position += U64.size
    rows = []
    for _ in range(count):
        page_id = U64.unpack_from(encoded, position)[0]
        position += U64.size
        revision_id = U64.unpack_from(encoded, position)[0]
        position += U64.size
        title_size = U64.unpack_from(encoded, position)[0]
        position += U64.size
        title = encoded[position : position + title_size].decode("utf-8")
        position += title_size
        text_size = U64.unpack_from(encoded, position)[0]
        position += U64.size
        text = encoded[position : position + text_size]
        position += text_size
        rows.append((page_id, revision_id, title, text))
    digest = encoded[position : position + 32]
    position += 32
    if position != len(encoded):
        raise AssertionError("trailing Wikimedia bundle bytes")
    return rows, digest


class TextSourceBuilderTests(unittest.TestCase):
    def test_source_bundle_is_byte_exact_ordered_and_metadata_independent(self):
        rows = [
            ("fixture-root/z.py", b"print('z')\r\n"),
            ("fixture-root/a.rs", b"fn main() {}\n"),
            ("fixture-root/vendor/ignored.c", b"ignored"),
            ("fixture-root/tests/ignored.ts", b"ignored"),
            ("fixture-root/readme.md", b"ignored"),
        ]
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            first_archive = root / "first.tar.xz"
            second_archive = root / "second.tar.xz"
            write_tar(first_archive, rows)
            write_tar(second_archive, rows, reverse=True)
            first = root / "first.axsrc"
            second = root / "second.axsrc"
            first_manifest = BUILDERS.build_source_bundle(
                archive_path=first_archive,
                destination=first,
                source={"id": "fixture-source"},
                rules_path=RULES,
            )
            second_manifest = BUILDERS.build_source_bundle(
                archive_path=second_archive,
                destination=second,
                source={"id": "fixture-source"},
                rules_path=RULES,
            )
            self.assertEqual(first.read_bytes(), second.read_bytes())
            decoded, terminal_digest = decode_source_bundle(first)
            self.assertEqual(
                decoded,
                [("a.rs", b"fn main() {}\n"), ("z.py", b"print('z')\r\n")],
            )
            self.assertEqual(first_manifest["retained_file_count"], 2)
            self.assertEqual(first_manifest["selected_file_count"], 2)
            self.assertEqual(
                terminal_digest.hex(), first_manifest["ordered_manifest_sha256"]
            )
            self.assertEqual(
                first_manifest["bundle_sha256"], hashlib.sha256(first.read_bytes()).hexdigest()
            )
            self.assertEqual(
                first_manifest["ordered_manifest_sha256"],
                second_manifest["ordered_manifest_sha256"],
            )

    def test_source_bundle_rejects_links_traversal_and_case_collisions(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            link_archive = root / "link.tar.xz"
            with tarfile.open(link_archive, "w:xz") as archive:
                link = tarfile.TarInfo("root/link.py")
                link.type = tarfile.SYMTYPE
                link.linkname = "target.py"
                archive.addfile(link)
            with self.assertRaisesRegex(ValueError, "links are forbidden"):
                BUILDERS.build_source_bundle(
                    archive_path=link_archive,
                    destination=root / "link.axsrc",
                    source={"id": "fixture-source"},
                    rules_path=RULES,
                )

            traversal = root / "traversal.tar.xz"
            write_tar(traversal, [("root/../escape.py", b"escape")])
            with self.assertRaisesRegex(ValueError, "unsafe archive path"):
                BUILDERS.build_source_bundle(
                    archive_path=traversal,
                    destination=root / "traversal.axsrc",
                    source={"id": "fixture-source"},
                    rules_path=RULES,
                )

            collision = root / "collision.tar.xz"
            write_tar(
                collision,
                [("root/Alpha.py", b"a"), ("root/alpha.py", b"b")],
            )
            with self.assertRaisesRegex(ValueError, "case-fold archive collision"):
                BUILDERS.build_source_bundle(
                    archive_path=collision,
                    destination=root / "collision.axsrc",
                    source={"id": "fixture-source"},
                    rules_path=RULES,
                )

    def test_source_bundle_cap_keeps_longest_ordered_whole_file_prefix(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "fixture.tar.xz"
            write_tar(
                archive,
                [("root/a.py", b"a" * 20), ("root/b.py", b"b" * 20)],
            )
            rules = json.loads(RULES.read_text(encoding="utf-8"))
            rules["maximum_bundle_bytes"] = (
                len(BUILDERS.SOURCE_MAGIC) + 8 + 32 + 8 + len("a.py") + 8 + 20
            )
            rules_path = root / "rules.json"
            rules_path.write_text(json.dumps(rules), encoding="utf-8")
            destination = root / "capped.axsrc"
            manifest = BUILDERS.build_source_bundle(
                archive_path=archive,
                destination=destination,
                source={"id": "fixture-source"},
                rules_path=rules_path,
            )
            decoded, _ = decode_source_bundle(destination)
            self.assertEqual(decoded, [("a.py", b"a" * 20)])
            self.assertTrue(manifest["truncated_at_byte_cap"])

    def test_wikimedia_bundle_selects_exact_xml_decoded_revision_text(self):
        pages = "".join(
            [
                page(1, 101, "Alpha", "A &amp; B\n{{markup}}"),
                page(2, 102, "Redirect", "skip", redirect=True),
                page(3, 103, "Talk", "skip", namespace=1),
                page(4, 104, "Beta", "β text"),
            ]
        )
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "wiki.xml.bz2"
            archive.write_bytes(bz2.compress(wiki_xml(pages)))
            destination = root / "wiki.axwkt"
            manifest = BUILDERS.build_wikimedia_bundle(
                archive_path=archive,
                destination=destination,
                source={"id": "fixture-wiki", "dump_date": "20260701"},
            )
            decoded, terminal_digest = decode_wiki_bundle(destination)
            self.assertEqual(
                decoded,
                [
                    (1, 101, "Alpha", b"A & B\n{{markup}}"),
                    (4, 104, "Beta", "β text".encode()),
                ],
            )
            self.assertEqual(manifest["retained_page_count"], 2)
            self.assertEqual(
                terminal_digest.hex(), manifest["ordered_manifest_sha256"]
            )

    def test_wikimedia_builder_rejects_doctype_and_cleans_partial_output(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "entity.xml.bz2"
            declaration = '<!DOCTYPE mediawiki [<!ENTITY x "expanded">]>'
            archive.write_bytes(
                bz2.compress(wiki_xml(page(1, 2, "Title", "&x;"), declaration))
            )
            destination = root / "entity.axwkt"
            with self.assertRaisesRegex(ValueError, "declarations are forbidden"):
                BUILDERS.build_wikimedia_bundle(
                    archive_path=archive,
                    destination=destination,
                    source={"id": "fixture-wiki", "dump_date": "20260701"},
                )
            self.assertFalse(destination.exists())
            self.assertEqual(list(root.glob("*.partial")), [])


if __name__ == "__main__":
    unittest.main()
