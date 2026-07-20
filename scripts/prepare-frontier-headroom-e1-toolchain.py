#!/usr/bin/env python3
"""Acquire and seal the exact E1 tools without touching corpus data."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
from types import ModuleType
from typing import Any
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "frontier-headroom-e1-toolchain-v1.json"
DEFAULT_ROOT = ROOT / ".research-tools" / "frontier-headroom-e1-v1"
DEFAULT_IMPORTS = {
    "kanzi-max": ROOT / ".baseline-tools" / "text-source-v1" / "bin" / "kanzi",
    "zstd-19-long": Path("/opt/homebrew/Cellar/zstd/1.5.7_1/bin/zstd"),
    "xz-lzma2-9e": Path("/opt/homebrew/Cellar/xz/5.8.3/bin/xz"),
    "zpaq-5-m510": ROOT
    / ".research-tools"
    / "text-source-v1"
    / "local"
    / "bin"
    / "zpaq-5-m510",
}
DEFAULT_ASSETS = {
    "lib/libzstd.1.dylib": Path(
        "/opt/homebrew/Cellar/zstd/1.5.7_1/lib/libzstd.1.5.7.dylib"
    ),
    "lib/liblzma.5.dylib": Path("/opt/homebrew/Cellar/xz/5.8.3/lib/liblzma.5.dylib"),
    "lib/liblz4.1.dylib": Path(
        "/opt/homebrew/Cellar/lz4/1.10.0/lib/liblz4.1.10.0.dylib"
    ),
}


def load_script(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VERIFIER = load_script(
    "frontier_headroom_e1_toolchain_verifier",
    ROOT / "scripts" / "verify-frontier-headroom-e1-toolchain.py",
)


class OfficialRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_hosts: set[str]) -> None:
        super().__init__()
        self.allowed_hosts = allowed_hosts

    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> Any:
        require_official_url(newurl, self.allowed_hosts)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def require_official_url(url: str, allowed_hosts: set[str]) -> None:
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in allowed_hosts
        or parsed.username
        or parsed.password
    ):
        raise ValueError(f"source URL is outside the official allowlist: {url}")


def copy_atomic(source: Path, destination: Path, *, executable: bool = False) -> None:
    VERIFIER.ordinary_file(source, executable=executable)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".partial", dir=destination.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as output, source.open("rb") as input_file:
            shutil.copyfileobj(input_file, output, 1024 * 1024)
        os.chmod(temporary_name, 0o755 if executable else 0o644)
        os.replace(temporary_name, destination)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def acquire_source(
    row: dict[str, Any], root: Path, *, allowed_hosts: set[str], allow_download: bool
) -> None:
    destination = root / row["cache_path"]
    if destination.exists():
        VERIFIER.verify_file(destination, row["bytes"], row["sha256"])
        return
    if not allow_download:
        raise ValueError(
            f"official source is absent and downloads are disabled: {row['codec_id']}"
        )
    require_official_url(row["url"], allowed_hosts)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".partial", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        total = 0
        opener = urllib.request.build_opener(OfficialRedirectHandler(allowed_hosts))
        request = urllib.request.Request(
            row["url"], headers={"User-Agent": "compression-lab-e1-toolchain-v1"}
        )
        with (
            os.fdopen(descriptor, "wb") as output,
            opener.open(request, timeout=120) as response,
        ):  # noqa: S310
            require_official_url(response.geturl(), allowed_hosts)
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > row["bytes"]:
                    raise ValueError("official source exceeded the frozen byte count")
                output.write(chunk)
        if total != row["bytes"] or VERIFIER.sha256_file(temporary) != row["sha256"]:
            raise ValueError("official source identity differs")
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def verify_build_toolchain(config: dict[str, Any]) -> list[dict[str, Any]]:
    records = []
    for row in config["build_toolchain"]:
        path = Path(row["path"])
        VERIFIER.verify_file(path, row["bytes"], row["sha256"], executable=True)
        completed = subprocess.run(
            [str(path), "--version"],
            check=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=60,
        )
        output = (completed.stdout + completed.stderr).decode("utf-8", "replace")
        if completed.returncode != 0 or row["version_line"] not in output:
            raise ValueError(f"build tool identity differs: {row['id']}")
        records.append(
            {
                "id": row["id"],
                "path": str(path),
                "bytes": row["bytes"],
                "sha256": row["sha256"],
                "version_line": row["version_line"],
            }
        )
    return records


def host_record(config: dict[str, Any]) -> dict[str, Any]:
    lock = config["platform_lock"]
    if platform.system() != lock["system"] or platform.machine() != lock["machine"]:
        raise ValueError("host platform differs from the E1 lock")
    completed = subprocess.run(
        ["/usr/sbin/sysctl", "-n", "hw.memsize"],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    memory_bytes = int(completed.stdout.strip())
    if memory_bytes < lock["minimum_memory_bytes"]:
        raise ValueError("host memory is below the E1 tool limit")
    for feature in ("wait4", "killpg", "setsid"):
        if not hasattr(os, feature):
            raise ValueError(f"required process feature is unavailable: os.{feature}")
    return {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "memory_bytes": memory_bytes,
        "python": platform.python_version(),
    }


def prepare(
    config_path: Path,
    root: Path,
    *,
    imports: dict[str, Path],
    assets: dict[str, Path],
    allow_download: bool,
) -> Path:
    config = json.loads(config_path.read_bytes())
    VERIFIER.validate_declaration(config)
    if root.is_symlink() or (root.exists() and not root.is_dir()):
        raise ValueError("tool root is not an ordinary directory")
    root.mkdir(parents=True, exist_ok=True)
    if (root / "receipt.json").exists():
        VERIFIER.verify_tool_root(config, root)
        return root / "receipt.json"
    allowed_hosts = set(config["security_boundary"]["allowed_hosts"])
    for row in config["sources"]:
        acquire_source(
            row, root, allowed_hosts=allowed_hosts, allow_download=allow_download
        )
    for row in config["executables"]:
        copy_atomic(imports[row["codec_id"]], root / row["path"], executable=True)
    for row in config["runtime_assets"]:
        copy_atomic(assets[row["path"]], root / row["path"])
    VERIFIER.verify_tool_root(config, root, verify_receipt=False)
    toolchain = verify_build_toolchain(config)
    host = host_record(config)
    receipt = {
        "schema_version": 1,
        "name": "frontier-headroom-e1-toolchain-receipt-v1",
        "completed": True,
        "config_sha256": VERIFIER.sha256_file(config_path),
        "e1_config_sha256": VERIFIER.sha256_file(VERIFIER.E1_CONFIG),
        "host": host,
        "build_toolchain": toolchain,
        "sources": [
            {"path": row["cache_path"], "bytes": row["bytes"], "sha256": row["sha256"]}
            for row in config["sources"]
        ],
        "executables": [
            {
                "codec_id": row["codec_id"],
                "path": row["path"],
                "bytes": row["bytes"],
                "sha256": row["sha256"],
            }
            for row in config["executables"]
        ],
        "runtime_assets": config["runtime_assets"],
        "cache_roster": sorted(row["cache_path"] for row in config["sources"]),
        "tool_roster": sorted(
            [row["path"] for row in config["executables"]]
            + [row["path"] for row in config["runtime_assets"]]
        ),
        "corpus_accessed": False,
        "measurements_exist": False,
        "claim_ceiling": config["execution_plan"]["claim_ceiling"],
    }
    receipt_path = root / "receipt.json"
    encoded = VERIFIER.json_bytes(receipt)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".receipt.", suffix=".partial", dir=root
    )
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(encoded)
        os.replace(temporary_name, receipt_path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise
    VERIFIER.verify_tool_root(config, root)
    return receipt_path


def acquire_sources(config_path: Path, root: Path, *, allow_download: bool) -> None:
    """Acquire only frozen source archives; this cannot seal or admit a tool root."""
    config = json.loads(config_path.read_bytes())
    VERIFIER.validate_declaration(config)
    if root.is_symlink() or (root.exists() and not root.is_dir()):
        raise ValueError("tool root is not an ordinary directory")
    root.mkdir(parents=True, exist_ok=True)
    if any(path.is_file() for path in root.rglob("*") if "cache" not in path.parts):
        raise ValueError("source-only root already contains non-cache files")
    allowed_hosts = set(config["security_boundary"]["allowed_hosts"])
    for row in config["sources"]:
        acquire_source(
            row, root, allowed_hosts=allowed_hosts, allow_download=allow_download
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--allow-download", action="store_true")
    parser.add_argument("--sources-only", action="store_true")
    parser.add_argument("--kanzi", type=Path, default=DEFAULT_IMPORTS["kanzi-max"])
    parser.add_argument("--zstd", type=Path, default=DEFAULT_IMPORTS["zstd-19-long"])
    parser.add_argument("--xz", type=Path, default=DEFAULT_IMPORTS["xz-lzma2-9e"])
    parser.add_argument("--zpaq", type=Path, default=DEFAULT_IMPORTS["zpaq-5-m510"])
    parser.add_argument(
        "--libzstd", type=Path, default=DEFAULT_ASSETS["lib/libzstd.1.dylib"]
    )
    parser.add_argument(
        "--liblzma", type=Path, default=DEFAULT_ASSETS["lib/liblzma.5.dylib"]
    )
    parser.add_argument(
        "--liblz4", type=Path, default=DEFAULT_ASSETS["lib/liblz4.1.dylib"]
    )
    args = parser.parse_args()
    imports = {
        "kanzi-max": args.kanzi,
        "zstd-19-long": args.zstd,
        "xz-lzma2-9e": args.xz,
        "zpaq-5-m510": args.zpaq,
    }
    assets = {
        "lib/libzstd.1.dylib": args.libzstd,
        "lib/liblzma.5.dylib": args.liblzma,
        "lib/liblz4.1.dylib": args.liblz4,
    }
    try:
        if args.sources_only:
            acquire_sources(args.config, args.root, allow_download=args.allow_download)
            receipt = args.root / "cache"
        else:
            receipt = prepare(
                args.config,
                args.root,
                imports=imports,
                assets=assets,
                allow_download=args.allow_download,
            )
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as error:
        raise SystemExit(f"E1 tool acquisition failed: {error}") from error
    print(receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
