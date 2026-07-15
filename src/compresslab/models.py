from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List


@dataclass(frozen=True)
class CorpusItem:
    id: str
    path: Path
    category: str
    split: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class CodecSpec:
    id: str
    family: str
    implementation: str
    level: int = 0
    available: bool = True
    unavailable_reason: str = ""


@dataclass
class TrialResult:
    run_id: str
    item_id: str
    item_category: str
    item_split: str
    codec_id: str
    codec_family: str
    repetition: int
    original_bytes: int
    compressed_bytes: int
    compression_ns: int
    decompression_ns: int
    compression_cpu_ns: int
    decompression_cpu_ns: int
    compression_peak_rss_bytes: int
    decompression_peak_rss_bytes: int
    roundtrip_ok: bool
    source_sha256: str
    restored_sha256: str
    selected_backend: str = ""
    selector_ns: int = 0
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        row = asdict(self)
        row.update(
            {
                "compressed_percent": (
                    100.0 * self.compressed_bytes / self.original_bytes
                    if self.original_bytes
                    else 0.0
                ),
                "savings_percent": (
                    100.0 * (1.0 - self.compressed_bytes / self.original_bytes)
                    if self.original_bytes
                    else 0.0
                ),
                "compression_mbps": _throughput(self.original_bytes, self.compression_ns),
                "decompression_mbps": _throughput(self.original_bytes, self.decompression_ns),
            }
        )
        return row


def _throughput(byte_count: int, elapsed_ns: int) -> float:
    if byte_count <= 0 or elapsed_ns <= 0:
        return 0.0
    return (byte_count / 1_000_000.0) / (elapsed_ns / 1_000_000_000.0)


@dataclass
class BenchmarkRun:
    schema_version: int
    run_id: str
    generated_at: str
    system: Dict[str, Any]
    config: Dict[str, Any]
    corpus: List[Dict[str, Any]]
    codecs: List[Dict[str, Any]]
    trials: List[Dict[str, Any]]
    medians: List[Dict[str, Any]]
    summary: List[Dict[str, Any]]
    oracle: Dict[str, Any]
    failures: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
