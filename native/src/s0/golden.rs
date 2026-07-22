//! Frozen golden fixtures for the M1 arm.
//!
//! These pins freeze the exact encoded tape bytes, the exact ledger, and the
//! exact decoded source for deterministic synthetic items. Any refactor of the
//! record chassis must keep every pin byte-identical. Regenerating a pin is an
//! explicit, reviewable act: the constants below must change in the diff.

use super::{decode_m1_item, encode_m1_item, Ledger, LossTable};
use sha2::{Digest, Sha256};

const CHUNK_LIMIT: usize = 1 << 20;

struct Golden {
    name: &'static str,
    item_index: u8,
    source_sha256: &'static str,
    tape_sha256: &'static str,
    ledger: Ledger,
}

const GOLDENS: &[Golden] = &[
    Golden {
        name: "mixed-records-unterminated-final",
        item_index: 0,
        source_sha256: "fea9c2a0b15ee0a1ffedbf55827a2af5d2f86520ad9b5d834ac0ce1651cf52bc",
        tape_sha256: "db04b902205a7a6a391cc802611638566dc58e21b704fe9025eb6c5d9cf8df39",
        ledger: Ledger {
            records: 9,
            modeled_binary_events: 297,
            modeled_loss_q24: 4_828_038_612,
            raw_literal_bytes: 31,
        },
    },
    Golden {
        name: "chunked-fallback-terminated-final",
        item_index: 1,
        source_sha256: "dbcb6b936de18f9218fb05c244f498965623788af2a26f97869bec813735b25d",
        tape_sha256: "26d580a27f06394a89b021df225b32af0f70cfd58f139e8f602604651f2b599e",
        ledger: Ledger {
            records: 2,
            modeled_binary_events: 48,
            modeled_loss_q24: 806_890_610,
            raw_literal_bytes: 1_048_588,
        },
    },
    Golden {
        name: "empty-item",
        item_index: 2,
        source_sha256: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        tape_sha256: "4489202ef4185af0d019bc0dba53e64eb81a034774410d457e2c990741745360",
        ledger: Ledger {
            records: 0,
            modeled_binary_events: 1,
            modeled_loss_q24: 16_777_216,
            raw_literal_bytes: 0,
        },
    },
    Golden {
        name: "uncacheable-template-repeats",
        item_index: 3,
        source_sha256: "f3a95f93518f676707f5e2f3a0c9a77c51234e9e3eec747e4e4ed9c6ba711a0f",
        tape_sha256: "e79908515e80eaac603f84905a02f776c4a15a443afefa1e706dbcd0901dafb3",
        ledger: Ledger {
            records: 4,
            modeled_binary_events: 77,
            modeled_loss_q24: 1_272_340_621,
            raw_literal_bytes: 140_019,
        },
    },
];

/// Deterministic fixture construction. All record types, multiple templates,
/// same-slot and different-slot hits, malformed fallback, a >1 MiB chunked
/// fallback, an empty item, uncacheable skeletons, and both terminated and
/// unterminated final records are covered across the four items.
fn source_for(name: &str) -> Vec<u8> {
    let mut source = Vec::new();
    match name {
        "mixed-records-unterminated-final" => {
            // Miss template A, same-slot hit, miss template B, different-slot
            // hits across A and B, an empty record, a malformed fallback, and
            // an unterminated same-slot final hit.
            source.extend_from_slice(b"{\"a\":1,\"b\":\"x\"}\n");
            source.extend_from_slice(b"{\"a\":2,\"b\":\"yy\"}\n");
            source.extend_from_slice(b"{\"c\":[1,2]}\n");
            source.extend_from_slice(b"{\"a\":3,\"b\":\"z\"}\n");
            source.extend_from_slice(b"{\"c\":[]}\n");
            source.extend_from_slice(b"\n");
            source.extend_from_slice(b"{bad}\n");
            source.extend_from_slice(b"{\"a\":4,\"b\":\"w\"}\n");
            source.extend_from_slice(b"{\"a\":5,\"b\":\"v\"}");
        }
        "chunked-fallback-terminated-final" => {
            // One record beyond the per-record limit forces the two-chunk
            // fallback path; the final record is terminated.
            source.extend(std::iter::repeat_n(b'x', CHUNK_LIMIT + 1));
            source.push(b'\n');
            source.extend_from_slice(b"{\"ok\":true}\n");
        }
        "empty-item" => {}
        "uncacheable-template-repeats" => {
            // A skeleton beyond the cacheable limit misses twice without ever
            // entering the store, then a small template misses and hits.
            let mut oversized = Vec::new();
            oversized.extend_from_slice(b"{\"");
            oversized.extend(std::iter::repeat_n(b'k', 70_000));
            oversized.extend_from_slice(b"\":1}\n");
            source.extend_from_slice(&oversized);
            let mut second = oversized.clone();
            let value_offset = second.len() - 3;
            second[value_offset] = b'2';
            source.extend_from_slice(&second);
            source.extend_from_slice(b"{\"s\":1}\n");
            source.extend_from_slice(b"{\"s\":2}\n");
        }
        other => panic!("unknown golden fixture {other}"),
    }
    source
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

#[test]
fn m1_arm_golden_tapes_ledgers_and_decodes_are_pinned() {
    let table = LossTable::generate();
    for golden in GOLDENS {
        let source = source_for(golden.name);
        assert_eq!(
            hex(&Sha256::digest(&source)),
            golden.source_sha256,
            "{}: fixture source drifted",
            golden.name
        );
        let (tape, ledger) = encode_m1_item(&source, &table, golden.item_index).unwrap();
        assert_eq!(
            hex(&Sha256::digest(tape.to_bytes())),
            golden.tape_sha256,
            "{}: tape bytes drifted",
            golden.name
        );
        assert_eq!(ledger, golden.ledger, "{}: ledger drifted", golden.name);
        let decoded = decode_m1_item(&tape, ledger, &table, golden.item_index).unwrap();
        assert_eq!(decoded, source, "{}: decode is not exact", golden.name);

        let (repeat_tape, repeat_ledger) =
            encode_m1_item(&source, &table, golden.item_index).unwrap();
        assert_eq!(
            repeat_tape.to_bytes(),
            tape.to_bytes(),
            "{}: encode is not deterministic",
            golden.name
        );
        assert_eq!(
            repeat_ledger, ledger,
            "{}: repeat ledger diverged",
            golden.name
        );
    }
}

/// Regeneration helper for intentional, reviewed pin updates only. Run with
/// `cargo test -- --ignored print_golden_pins --nocapture`.
#[test]
#[ignore = "prints pin values for explicit golden updates"]
fn print_golden_pins() {
    let table = LossTable::generate();
    for golden in GOLDENS {
        let source = source_for(golden.name);
        let (tape, ledger) = encode_m1_item(&source, &table, golden.item_index).unwrap();
        println!(
            "{}\n  source_sha256: \"{}\"\n  tape_sha256: \"{}\"\n  ledger: records {} events {} loss_q24 {} literal_bytes {}",
            golden.name,
            hex(&Sha256::digest(&source)),
            hex(&Sha256::digest(tape.to_bytes())),
            ledger.records,
            ledger.modeled_binary_events,
            ledger.modeled_loss_q24,
            ledger.raw_literal_bytes,
        );
    }
}
