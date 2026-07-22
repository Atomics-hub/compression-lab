//! Frozen golden fixtures for the M1, M2, M3, and M4 arms.
//!
//! These pins freeze the exact encoded tape bytes, the exact ledger, and the
//! exact decoded source for deterministic synthetic items. Any refactor of the
//! record chassis must keep every pin byte-identical. Regenerating a pin is an
//! explicit, reviewable act: the constants below must change in the diff.

use super::{
    decode_m1_item, decode_m1_m2_item, decode_m1_m2_m3_item, decode_m1_m2_m4_item, encode_m1_item,
    encode_m1_m2_item, encode_m1_m2_m3_item, encode_m1_m2_m4_item, Ledger, LossTable, Tape,
};
use sha2::{Digest, Sha256};

const CHUNK_LIMIT: usize = 1 << 20;

struct Golden {
    name: &'static str,
    arm: u8,
    item_index: u8,
    source_sha256: &'static str,
    tape_sha256: &'static str,
    ledger: Ledger,
}

const GOLDENS: &[Golden] = &[
    Golden {
        name: "mixed-records-unterminated-final",
        arm: 1,
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
        arm: 1,
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
        arm: 1,
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
        arm: 1,
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
    Golden {
        name: "post-uncacheable-slotless-hit",
        arm: 1,
        item_index: 4,
        source_sha256: "7a9f3f3e42e7642b53086f1cdf32364fd7733a09c8be2c8873af7c727e8c4d52",
        tape_sha256: "bb68e00693f999f66c74904c671955ee04516a3306974ba60fbd8c6ebaf6c7b3",
        ledger: Ledger {
            records: 3,
            modeled_binary_events: 64,
            modeled_loss_q24: 1_073_227_897,
            raw_literal_bytes: 70_013,
        },
    },
    Golden {
        name: "m2-id-time-lanes",
        arm: 2,
        item_index: 5,
        source_sha256: "fddf0442af26065519dfcae894d3267a9d35266c88fcaa6a435c12a01e5785b6",
        tape_sha256: "c1a44845fa28bba071d6b2e00940c965667fc1e0123ca8acd160e2c6d046346c",
        ledger: Ledger {
            records: 9,
            modeled_binary_events: 847,
            modeled_loss_q24: 13_666_490_909,
            raw_literal_bytes: 53,
        },
    },
    Golden {
        name: "m2-lane-64-boundary",
        arm: 2,
        item_index: 6,
        source_sha256: "034c2ced893a643a515362e8f179b1616d027266d9235bb3e9373b16a808d39f",
        tape_sha256: "35dc9511a92b65bb1ba2a68e181425827f6ea654a4728f6c80428f55e27822a5",
        ledger: Ledger {
            records: 2,
            modeled_binary_events: 643,
            modeled_loss_q24: 10_787_820_837,
            raw_literal_bytes: 595,
        },
    },
    Golden {
        name: "m2-slot-eviction-lane-reset",
        arm: 2,
        item_index: 7,
        source_sha256: "76469320f9961057e71f28b48970ed04ce33713f887541eedfd7ee4a5f77ff6d",
        tape_sha256: "ed941670e292221dd664fa62a8dbed597270dbb28818445839895a995d06ffaa",
        ledger: Ledger {
            records: 4_099,
            modeled_binary_events: 45_094,
            modeled_loss_q24: 11_584_963_908,
            raw_literal_bytes: 56_259,
        },
    },
    Golden {
        name: "m3-session-references",
        arm: 3,
        item_index: 8,
        source_sha256: "c2df83fa20326705929fe8c1f043303637ce292081d5c9a0c9fd2f02c4fbe01d",
        tape_sha256: "ae34028d000859ef2ca4727836b284d00502012c4088c0a51a3a10e65d471dd3",
        ledger: Ledger {
            records: 14,
            modeled_binary_events: 6_423,
            modeled_loss_q24: 83_019_960_591,
            raw_literal_bytes: 1_196,
        },
    },
    Golden {
        name: "m4-token-dictionary",
        arm: 4,
        item_index: 9,
        source_sha256: "c7c30cab1bbf7bd3ab9ae66d94645232f5709eff90bec1f750a023c4f1828af6",
        tape_sha256: "e0782102ca534edfe7e1e50c48a76049b1dd62ebf44bf511fd4add0abccc8f39",
        ledger: Ledger {
            records: 11,
            modeled_binary_events: 1_826,
            modeled_loss_q24: 22_187_851_441,
            raw_literal_bytes: 56,
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
        "post-uncacheable-slotless-hit" => {
            // A cacheable miss, then an uncacheable miss that clears the
            // last-slot tracker while the small template stays resident, then
            // a hit that must charge the slot tree directly with no
            // same-template bit.
            source.extend_from_slice(b"{\"s\":1}\n");
            let mut oversized = Vec::new();
            oversized.extend_from_slice(b"{\"");
            oversized.extend(std::iter::repeat_n(b'q', 70_000));
            oversized.extend_from_slice(b"\":1}\n");
            source.extend_from_slice(&oversized);
            source.extend_from_slice(b"{\"s\":2}\n");
        }
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
        "m2-id-time-lanes" => {
            // ID hits with positive, zero, and negative deltas; TIME hits;
            // separator and fraction-width shape changes escaping and
            // re-arming; an ID lane escaping to Other and going silent; an
            // empty record; a fallback; and an unterminated typed final.
            source
                .extend_from_slice(b"{\"id\":100,\"ts\":\"2026-07-22T10:00:00Z\",\"msg\":\"a\"}\n");
            source
                .extend_from_slice(b"{\"id\":101,\"ts\":\"2026-07-22T10:00:01Z\",\"msg\":\"b\"}\n");
            source
                .extend_from_slice(b"{\"id\":101,\"ts\":\"2026-07-22T10:00:01Z\",\"msg\":\"c\"}\n");
            source
                .extend_from_slice(b"{\"id\":90,\"ts\":\"2026-07-22 10:00:02Z\",\"msg\":\"d\"}\n");
            source.extend_from_slice(
                b"{\"id\":\"x\",\"ts\":\"2026-07-22 10:00:03Z\",\"msg\":\"e\"}\n",
            );
            source.extend_from_slice(
                b"{\"id\":\"y\",\"ts\":\"2026-07-22 10:00:04.5Z\",\"msg\":\"f\"}\n",
            );
            source.extend_from_slice(b"\n");
            source.extend_from_slice(b"{bad}\n");
            source
                .extend_from_slice(b"{\"id\":-5,\"ts\":\"2026-07-22 10:00:05.6Z\",\"msg\":\"g\"}");
        }
        "m2-lane-64-boundary" => {
            // A 66-value template: lanes 0-63 delta-code, 64 and 65 stay M1.
            let first: Vec<String> = (0..66).map(|i| format!("\"k{i:02}\":{}", i + 10)).collect();
            let second: Vec<String> = (0..66).map(|i| format!("\"k{i:02}\":{}", i + 11)).collect();
            source.extend_from_slice(format!("{{{}}}\n", first.join(",")).as_bytes());
            source.extend_from_slice(format!("{{{}}}\n", second.join(",")).as_bytes());
        }
        "m2-slot-eviction-lane-reset" => {
            // 4,097 distinct templates force one CLOCK eviction, clearing the
            // evicted slot's lanes; the evicted template then re-teaches and
            // its first hit delta-codes from the freshly seeded state.
            for index in 0..4_097_u32 {
                source.extend_from_slice(format!("{{\"t{index:04}\":{index}}}\n").as_bytes());
            }
            source.extend_from_slice(b"{\"t0000\":7}\n");
            source.extend_from_slice(b"{\"t0000\":9}\n");
        }
        "m3-session-references" => {
            // Repeated session strings hitting the reference cache across two
            // templates, interleaved with typed ID deltas consumed by M2 (and
            // so invisible to M3), M2 escapes taught to the cache, and an
            // oversized value that can never be cached.
            for index in 0..5_u32 {
                source.extend_from_slice(
                    format!(
                        "{{\"sid\":\"sess-{}\",\"seq\":{index},\"tag\":\"t{index}\"}}\n",
                        index % 2
                    )
                    .as_bytes(),
                );
                source.extend_from_slice(
                    format!(
                        "{{\"user\":\"u{}\",\"sid\":\"sess-{}\"}}\n",
                        index % 3,
                        index % 2
                    )
                    .as_bytes(),
                );
            }
            source.extend_from_slice(format!("{{\"blob\":\"{}\"}}\n", "y".repeat(200)).as_bytes());
            source.extend_from_slice(format!("{{\"blob\":\"{}\"}}\n", "y".repeat(200)).as_bytes());
            // A 66-value template whose lane-64 string repeats pins the
            // lane-index >= 64 route into the session cache.
            for round in 0..2_u32 {
                let fields: Vec<String> = (0..66)
                    .map(|lane| {
                        if lane == 64 {
                            "\"w64\":\"wide-session\"".to_string()
                        } else {
                            format!("\"w{lane:02}\":\"v{lane}r{round}\"")
                        }
                    })
                    .collect();
                source.extend_from_slice(format!("{{{}}}\n", fields.join(",")).as_bytes());
            }
        }
        "m4-token-dictionary" => {
            // Repeated path-like vocabulary hitting the token dictionary,
            // typed ID deltas consumed by M2 and invisible to M4, unmatched
            // punctuation-only values, and mixed prefix/token/suffix
            // segments, with an empty record and a fallback interleaved.
            for index in 0..8_u32 {
                source.extend_from_slice(
                    format!(
                        "{{\"seq\":{index},\"path\":\"/svc/widgets/{}/state\",\"raw\":\"#{}!\"}}\n",
                        index % 3,
                        index
                    )
                    .as_bytes(),
                );
            }
            source.extend_from_slice(b"\n");
            source.extend_from_slice(b"{bad}\n");
            source.extend_from_slice(
                b"{\"seq\":9,\"path\":\"/svc/widgets/0/state\",\"raw\":\"pre gadgets77 post\"}",
            );
        }
        other => panic!("unknown golden fixture {other}"),
    }
    source
}

fn encode_arm(golden: &Golden, source: &[u8], table: &LossTable) -> (Tape, Ledger) {
    match golden.arm {
        1 => encode_m1_item(source, table, golden.item_index).unwrap(),
        2 => encode_m1_m2_item(source, table, golden.item_index).unwrap(),
        3 => encode_m1_m2_m3_item(source, table, golden.item_index).unwrap(),
        4 => encode_m1_m2_m4_item(source, table, golden.item_index).unwrap(),
        other => panic!("unknown golden arm {other}"),
    }
}

fn decode_arm(golden: &Golden, tape: &Tape, ledger: Ledger, table: &LossTable) -> Vec<u8> {
    match golden.arm {
        1 => decode_m1_item(tape, ledger, table, golden.item_index).unwrap(),
        2 => decode_m1_m2_item(tape, ledger, table, golden.item_index).unwrap(),
        3 => decode_m1_m2_m3_item(tape, ledger, table, golden.item_index).unwrap(),
        4 => decode_m1_m2_m4_item(tape, ledger, table, golden.item_index).unwrap(),
        other => panic!("unknown golden arm {other}"),
    }
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
        let (tape, ledger) = encode_arm(golden, &source, &table);
        assert_eq!(
            hex(&Sha256::digest(tape.to_bytes())),
            golden.tape_sha256,
            "{}: tape bytes drifted",
            golden.name
        );
        assert_eq!(ledger, golden.ledger, "{}: ledger drifted", golden.name);
        let decoded = decode_arm(golden, &tape, ledger, &table);
        assert_eq!(decoded, source, "{}: decode is not exact", golden.name);

        let (repeat_tape, repeat_ledger) = encode_arm(golden, &source, &table);
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
        let (tape, ledger) = encode_arm(golden, &source, &table);
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
