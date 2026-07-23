//! H6 hybrid arm: the H1 mixing floor with a whole-line reuse layer.
//!
//! Development-only prescreen arm for the moonshot cycle 1 (Lane 2). It stacks
//! the only two S0-winning mechanisms: the moon H1 byte-level shared-table
//! mixing as the floor coder that never loses, and a whole-value reuse layer
//! (the byte-level analogue of S0's M3, [`LineCache`]) that fires on exact
//! whole-line repeats. No per-lane structure and no online charged dictionary.
//!
//! Grammar (attribution firewall). At every line boundary one line-present
//! flag and one decision bit precede the line. On a hit, the 16-bit slot
//! reference is charged and the line's bytes are skipped entirely; on a miss,
//! the line's bytes flow through the unchanged H1 floor coder (identical
//! per-byte grammar, with the line-present flag doubling as the first byte's
//! continuation) and are then taught to the cache. The floor model sees only
//! miss bytes, so "H1 on the miss substream" is exactly recoverable and an
//! all-unique stream pays exactly one decision bit per line over pure H1.
//! Decode mirrors exactly; fail-closed on corruption, exhaustion, identity
//! mismatch, and bad references; ledger equality as in H1.

use crate::s0::{Ledger, LossTable, Probability, Tape, TapeError, TapeReader, TapeWriter};
use std::error::Error;
use std::fmt::{Display, Formatter};

use super::h1::{h1_declared_state_bytes, H1Error, H1Model};
use super::reuse::{LineCache, ReferenceCoder, ReferenceWalk, REFERENCE_TREE_BYTES};

/// Tape arm identity for the H6 hybrid arm. Disjoint from the H1 floor arm.
pub const H6_ARM_ID: u8 = 101;

/// Mixing-context buckets for the per-line hit/miss decision bit.
pub const H6_DECISION_BUCKETS: usize = 1_024;
pub const H6_DECISION_STATE_BYTES: usize = H6_DECISION_BUCKETS * 2;
/// Bytes of preceding output that condition the decision bucket.
const DECISION_CONTEXT_BYTES: usize = 8;

// Disjoint mixer event namespaces, high above the H1 byte identities (< 2^16)
// and the H1 continuation identity (u64::MAX).
const FLAG_EVENT_ID: u64 = 1 << 50;
const DECISION_EVENT_BASE: u64 = 1 << 51;
const REFERENCE_EVENT_BASE: u64 = 1 << 52;

const FNV_OFFSET: u64 = 14_695_981_039_346_656_037;
const FNV_PRIME: u64 = 1_099_511_628_211;

fn decision_bucket(output: &[u8]) -> usize {
    let start = output.len().saturating_sub(DECISION_CONTEXT_BYTES);
    let hash = output[start..].iter().fold(FNV_OFFSET, |hash, byte| {
        (hash ^ u64::from(*byte)).wrapping_mul(FNV_PRIME)
    });
    (hash as usize) & (H6_DECISION_BUCKETS - 1)
}

/// Declared model-state bytes for an H6 model: the H1 floor state, plus the
/// whole-line cache (dimensioned identically to the s0 M3 cache), the 16-bit
/// reference bit-tree, and the decision-bit buckets. O(1) scratch (the
/// line-present flag) is excluded, per the s0 convention.
#[must_use]
pub fn h6_declared_state_bytes(table: &LossTable, sse_bucket_bits: u32) -> usize {
    h1_declared_state_bytes(table, sse_bucket_bits)
        + LineCache::new().declared_state_bytes()
        + REFERENCE_TREE_BYTES
        + H6_DECISION_STATE_BYTES
}

fn next_line_end(source: &[u8], start: usize) -> usize {
    match source[start..].iter().position(|&byte| byte == b'\n') {
        Some(offset) => start + offset + 1,
        None => source.len(),
    }
}

fn encode_reference(
    model: &mut H1Model,
    reference: &mut ReferenceCoder,
    slot: u16,
    table: &LossTable,
    ledger: &mut Ledger,
    writer: &mut TapeWriter,
) -> Result<(), H6Error> {
    let mut walk = ReferenceWalk::encode(slot);
    while let Some(node) = walk.next_node() {
        let bit = walk.encode_bit();
        model.encode_flag_bit(
            reference.node(node),
            REFERENCE_EVENT_BASE | node as u64,
            bit,
            table,
            ledger,
            writer,
        )?;
        walk.advance(bit);
    }
    Ok(())
}

fn decode_reference(
    model: &mut H1Model,
    reference: &mut ReferenceCoder,
    table: &LossTable,
    ledger: &mut Ledger,
    reader: &mut TapeReader<'_>,
) -> Result<usize, H6Error> {
    let mut walk = ReferenceWalk::decode();
    while let Some(node) = walk.next_node() {
        let bit = model.decode_flag_bit(
            reference.node(node),
            REFERENCE_EVENT_BASE | node as u64,
            table,
            ledger,
            reader,
        )?;
        walk.advance(bit);
    }
    Ok(walk.decoded_slot())
}

/// Encode one item under the H6 arm at the base SSE capacity.
pub fn encode_h6_item(
    source: &[u8],
    table: &LossTable,
    item_index: u8,
) -> Result<(Tape, Ledger), H6Error> {
    encode_h6_item_with_bits(source, table, item_index, crate::s0::SSE_BASE_BUCKET_BITS)
}

/// Encode one item under the H6 arm at an explicit SSE capacity.
pub fn encode_h6_item_with_bits(
    source: &[u8],
    table: &LossTable,
    item_index: u8,
    sse_bucket_bits: u32,
) -> Result<(Tape, Ledger), H6Error> {
    let mut model = H1Model::new(table, sse_bucket_bits);
    let mut cache = LineCache::new();
    let mut reference = ReferenceCoder::new();
    let mut decisions = vec![Probability::default(); H6_DECISION_BUCKETS].into_boxed_slice();
    let mut flag = Probability::default();
    let mut writer = TapeWriter::new(H6_ARM_ID, item_index);
    let mut ledger = Ledger::default();
    let mut miss_history: Vec<u8> = Vec::new();

    let mut position = 0;
    while position < source.len() {
        let line_end = next_line_end(source, position);
        let line = &source[position..line_end];
        let hit = cache.lookup(line);

        // Line-present flag; for a miss it also serves as the first byte's
        // continuation, keeping the per-line overhead at exactly one bit.
        model.encode_flag_bit(
            &mut flag,
            FLAG_EVENT_ID,
            true,
            table,
            &mut ledger,
            &mut writer,
        )?;
        let bucket = decision_bucket(&source[..position]);
        model.encode_flag_bit(
            &mut decisions[bucket],
            DECISION_EVENT_BASE | bucket as u64,
            hit.is_some(),
            table,
            &mut ledger,
            &mut writer,
        )?;

        match hit {
            Some(slot) => {
                let slot = u16::try_from(slot).map_err(|_| H6Error::ReferenceOutOfRange)?;
                encode_reference(
                    &mut model,
                    &mut reference,
                    slot,
                    table,
                    &mut ledger,
                    &mut writer,
                )?;
            }
            None => {
                for (index, &byte) in line.iter().enumerate() {
                    if index > 0 {
                        model.encode_flag_bit(
                            &mut flag,
                            FLAG_EVENT_ID,
                            true,
                            table,
                            &mut ledger,
                            &mut writer,
                        )?;
                    }
                    model.encode_byte(byte, &miss_history, table, &mut ledger, &mut writer)?;
                    miss_history.push(byte);
                }
                cache.insert(line);
            }
        }
        ledger.add_record().ok_or(H6Error::LedgerOverflow)?;
        position = line_end;
    }
    // Terminal: no further line follows.
    model.encode_flag_bit(
        &mut flag,
        FLAG_EVENT_ID,
        false,
        table,
        &mut ledger,
        &mut writer,
    )?;
    Ok((writer.finish(), ledger))
}

/// Decode one item under the H6 arm at the base SSE capacity.
pub fn decode_h6_item(
    tape: &Tape,
    expected_ledger: Ledger,
    table: &LossTable,
    expected_item_index: u8,
) -> Result<Vec<u8>, H6Error> {
    decode_h6_item_with_bits(
        tape,
        expected_ledger,
        table,
        expected_item_index,
        crate::s0::SSE_BASE_BUCKET_BITS,
    )
}

/// Decode one item under the H6 arm at an explicit SSE capacity, checking arm
/// and item identity and independent ledger equality.
pub fn decode_h6_item_with_bits(
    tape: &Tape,
    expected_ledger: Ledger,
    table: &LossTable,
    expected_item_index: u8,
    sse_bucket_bits: u32,
) -> Result<Vec<u8>, H6Error> {
    if tape.arm_id() != H6_ARM_ID || tape.item_index() != expected_item_index {
        return Err(H6Error::TapeIdentityMismatch);
    }
    let mut model = H1Model::new(table, sse_bucket_bits);
    let mut cache = LineCache::new();
    let mut reference = ReferenceCoder::new();
    let mut decisions = vec![Probability::default(); H6_DECISION_BUCKETS].into_boxed_slice();
    let mut flag = Probability::default();
    let mut ledger = Ledger::default();
    let mut reader = tape.reader();
    let mut output: Vec<u8> = Vec::new();
    let mut miss_history: Vec<u8> = Vec::new();
    let mut current_line: Vec<u8> = Vec::new();
    let mut at_line_start = true;

    loop {
        let more =
            model.decode_flag_bit(&mut flag, FLAG_EVENT_ID, table, &mut ledger, &mut reader)?;
        if !more {
            break;
        }
        if at_line_start {
            let bucket = decision_bucket(&output);
            let hit = model.decode_flag_bit(
                &mut decisions[bucket],
                DECISION_EVENT_BASE | bucket as u64,
                table,
                &mut ledger,
                &mut reader,
            )?;
            if hit {
                let slot =
                    decode_reference(&mut model, &mut reference, table, &mut ledger, &mut reader)?;
                let line = cache.select(slot).ok_or(H6Error::ReferenceOutOfRange)?;
                output.extend_from_slice(&line);
                ledger.add_record().ok_or(H6Error::LedgerOverflow)?;
                at_line_start = true;
                continue;
            }
        }
        // A miss byte follows (its continuation was the flag just read).
        let byte = model.decode_byte(&miss_history, table, &mut ledger, &mut reader)?;
        miss_history.push(byte);
        output.push(byte);
        current_line.push(byte);
        if byte == b'\n' {
            cache.insert(&current_line);
            ledger.add_record().ok_or(H6Error::LedgerOverflow)?;
            current_line.clear();
            at_line_start = true;
        } else {
            at_line_start = false;
        }
    }
    // A final line without a trailing newline is completed by the terminal.
    if !current_line.is_empty() {
        cache.insert(&current_line);
        ledger.add_record().ok_or(H6Error::LedgerOverflow)?;
    }
    if !reader.is_finished() {
        return Err(H6Error::TrailingChargedData);
    }
    if ledger != expected_ledger {
        return Err(H6Error::LedgerDivergence {
            encoder: expected_ledger,
            decoder: ledger,
        });
    }
    Ok(output)
}

/// H6 encode/decode error. Every variant is terminal for the item.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum H6Error {
    LedgerOverflow,
    TapeIdentityMismatch,
    TrailingChargedData,
    ReferenceOutOfRange,
    LedgerDivergence { encoder: Ledger, decoder: Ledger },
    Floor(H1Error),
    Tape(TapeError),
}

impl From<H1Error> for H6Error {
    fn from(error: H1Error) -> Self {
        Self::Floor(error)
    }
}

impl From<TapeError> for H6Error {
    fn from(error: TapeError) -> Self {
        Self::Tape(error)
    }
}

impl Display for H6Error {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "moon H6 error: {self:?}")
    }
}

impl Error for H6Error {}

#[cfg(test)]
mod tests {
    use super::super::h1::encode_h1_item;
    use super::*;

    const PINNED_TAPE_SHA256: &str =
        "4f4057b4bd8a4eab42f547b9c0f9c28227ce6b7d8c82d9a2dd4bab21b439db87";

    fn regime_snippets() -> Vec<(&'static str, Vec<u8>)> {
        let mut snippets: Vec<(&'static str, Vec<u8>)> = Vec::new();

        // Heavy exact-duplicate lines: the reuse layer should fire often.
        let mut duplicated = Vec::new();
        for _ in 0..60 {
            duplicated.extend_from_slice(b"{\"level\":\"info\",\"msg\":\"ready\"}\n");
        }
        snippets.push(("heavy-duplicate", duplicated));

        // Interleaved repeats across a few distinct templates.
        let mut interleaved = Vec::new();
        for index in 0..80_u32 {
            interleaved.extend_from_slice(
                format!("{{\"event\":\"beat\",\"slot\":{}}}\n", index % 4).as_bytes(),
            );
        }
        snippets.push(("interleaved", interleaved));

        // All-unique lines: every line misses.
        let mut unique = Vec::new();
        for index in 0..60_u32 {
            let mix = index.wrapping_mul(2_654_435_761);
            unique.extend_from_slice(
                format!("{{\"id\":{},\"tag\":\"{:08x}\"}}\n", 100_000 + index, mix).as_bytes(),
            );
        }
        snippets.push(("all-unique", unique));

        // Line-oriented text with repeats.
        let mut logs = Vec::new();
        for index in 0..50_u32 {
            logs.extend_from_slice(format!("WARN worker[{}] retrying\n", index % 3).as_bytes());
        }
        snippets.push(("line-log", logs));

        // Adversarial and edge bytes.
        snippets.push(("tiny", b"{}\n".to_vec()));
        snippets.push(("binary", (0..=255_u8).cycle().take(300).collect()));
        snippets.push(("no-newline", b"{\"tail\":true}".to_vec()));
        snippets.push(("blank-lines", b"\n\n{\"a\":1}\n\n{\"a\":1}\n".to_vec()));
        snippets.push(("empty", Vec::new()));

        // A long line beyond the 128-byte cache bound, repeated (never cached).
        let long = format!("{{\"v\":\"{}\"}}\n", "z".repeat(200));
        let mut long_repeat = Vec::new();
        for _ in 0..4 {
            long_repeat.extend_from_slice(long.as_bytes());
        }
        snippets.push(("oversized-line", long_repeat));

        snippets
    }

    fn line_count(source: &[u8]) -> usize {
        if source.is_empty() {
            return 0;
        }
        let newlines = source.iter().filter(|&&byte| byte == b'\n').count();
        if source.last() == Some(&b'\n') {
            newlines
        } else {
            newlines + 1
        }
    }

    #[test]
    fn round_trips_exactly_across_every_regime() {
        let table = LossTable::generate();
        for (name, source) in regime_snippets() {
            let (tape, ledger) = encode_h6_item(&source, &table, 1).unwrap();
            let decoded = decode_h6_item(&tape, ledger, &table, 1).unwrap();
            assert_eq!(decoded, source, "regime {name} did not round-trip");
            assert_eq!(ledger.raw_literal_bytes, 0, "H6 charges no literals");
        }
    }

    #[test]
    fn repeat_runs_are_byte_identical_in_tape_and_ledger() {
        let table = LossTable::generate();
        let source = regime_snippets().remove(0).1;
        let (tape_a, ledger_a) = encode_h6_item(&source, &table, 2).unwrap();
        let (tape_b, ledger_b) = encode_h6_item(&source, &table, 2).unwrap();
        assert_eq!(tape_a.to_bytes(), tape_b.to_bytes());
        assert_eq!(ledger_a, ledger_b);
    }

    #[test]
    fn heavy_duplicates_beat_the_h1_floor() {
        let table = LossTable::generate();
        let source = regime_snippets().remove(0).1;
        let (_, h6_ledger) = encode_h6_item(&source, &table, 0).unwrap();
        let (_, h1_ledger) = encode_h1_item(&source, &table, 0).unwrap();
        let h6 = h6_ledger.project_item(source.len() as u64).unwrap();
        let h1 = h1_ledger.project_item(source.len() as u64).unwrap();
        assert!(
            h6.complete_bytes < h1.complete_bytes,
            "reuse layer did not help on heavy duplicates: h6 {} h1 {}",
            h6.complete_bytes,
            h1.complete_bytes
        );
    }

    #[test]
    fn all_unique_lines_cost_exactly_one_decision_bit_per_line_over_h1() {
        let table = LossTable::generate();
        let source = regime_snippets().remove(2).1; // all-unique
        let lines = line_count(&source);
        let (_, h6_ledger) = encode_h6_item(&source, &table, 0).unwrap();
        let (_, h1_ledger) = encode_h1_item(&source, &table, 0).unwrap();
        assert_eq!(
            h6_ledger.modeled_binary_events,
            h1_ledger.modeled_binary_events + lines as u64,
            "all-unique overhead was not exactly one bit per line"
        );
    }

    #[test]
    fn decode_fails_closed_on_a_tampered_ledger() {
        let table = LossTable::generate();
        let source = b"{\"a\":1}\n{\"a\":1}\n{\"b\":2}\n".to_vec();
        let (tape, ledger) = encode_h6_item(&source, &table, 0).unwrap();
        let mut wrong = ledger;
        wrong.modeled_loss_q24 += 1;
        assert!(matches!(
            decode_h6_item(&tape, wrong, &table, 0),
            Err(H6Error::LedgerDivergence { .. })
        ));
    }

    #[test]
    fn decode_rejects_a_foreign_arm_or_item_identity() {
        let table = LossTable::generate();
        let source = b"hello world\n".to_vec();
        let (tape, ledger) = encode_h6_item(&source, &table, 3).unwrap();
        assert_eq!(
            decode_h6_item(&tape, ledger, &table, 4),
            Err(H6Error::TapeIdentityMismatch)
        );
        // An H1 tape must not decode as H6.
        let (h1_tape, h1_ledger) = encode_h1_item(&source, &table, 3).unwrap();
        assert_eq!(
            decode_h6_item(&h1_tape, h1_ledger, &table, 3),
            Err(H6Error::TapeIdentityMismatch)
        );
    }

    #[test]
    fn a_flipped_payload_byte_is_rejected_by_the_tape_digest() {
        let table = LossTable::generate();
        let source = regime_snippets().remove(0).1;
        let (tape, _) = encode_h6_item(&source, &table, 0).unwrap();
        let mut bytes = tape.to_bytes();
        let target = bytes.len() / 2;
        bytes[target] ^= 0x01;
        assert_eq!(Tape::from_bytes(&bytes), Err(TapeError::DigestMismatch));
    }

    #[test]
    fn one_extra_charged_bit_past_end_of_stream_fails_closed() {
        use sha2::{Digest, Sha256};
        let table = LossTable::generate();
        let source = b"{\"a\":1}\n{\"a\":1}\n".to_vec();
        let (tape, ledger) = encode_h6_item(&source, &table, 0).unwrap();
        let bytes = tape.to_bytes();

        const HEADER: usize = 14;
        const DIGEST: usize = 32;
        let bit_count = u64::from_le_bytes(bytes[6..14].try_into().unwrap());
        let bit_bytes_len = bit_count.div_ceil(8) as usize;
        let new_bit_count = bit_count + 1;
        let new_bit_bytes_len = new_bit_count.div_ceil(8) as usize;
        let payload_end = bytes.len() - DIGEST;

        let mut rebuilt = Vec::new();
        rebuilt.extend_from_slice(&bytes[..6]);
        rebuilt.extend_from_slice(&new_bit_count.to_le_bytes());
        let bit_end = HEADER + bit_bytes_len;
        rebuilt.extend_from_slice(&bytes[HEADER..bit_end]);
        if new_bit_bytes_len > bit_bytes_len {
            rebuilt.push(0);
        }
        rebuilt.extend_from_slice(&bytes[bit_end..payload_end]);
        let digest = Sha256::digest(&rebuilt);
        rebuilt.extend_from_slice(&digest);

        let tampered = Tape::from_bytes(&rebuilt).unwrap();
        assert_eq!(
            decode_h6_item(&tampered, ledger, &table, 0),
            Err(H6Error::TrailingChargedData)
        );
    }

    #[test]
    fn declared_state_accounts_for_floor_cache_reference_and_decisions() {
        let table = LossTable::generate();
        let floor = h1_declared_state_bytes(&table, crate::s0::SSE_BASE_BUCKET_BITS);
        let total = h6_declared_state_bytes(&table, crate::s0::SSE_BASE_BUCKET_BITS);
        assert_eq!(
            total,
            floor
                + LineCache::new().declared_state_bytes()
                + REFERENCE_TREE_BYTES
                + H6_DECISION_STATE_BYTES
        );
        // Regression pin of the exact figure the receipts report.
        assert_eq!(total, 129_517_566);
    }

    #[test]
    fn known_answer_tape_sha256_is_pinned() {
        use sha2::{Digest, Sha256};
        let table = LossTable::generate();
        let source = b"{\"level\":\"info\",\"msg\":\"ready\",\"n\":1}\n\
                       {\"level\":\"info\",\"msg\":\"ready\",\"n\":1}\n\
                       {\"level\":\"info\",\"msg\":\"ready\",\"n\":2}\n"
            .to_vec();
        let (tape, _) = encode_h6_item(&source, &table, 0).unwrap();
        let sha: String = Sha256::digest(tape.to_bytes())
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect();
        assert_eq!(sha, PINNED_TAPE_SHA256, "pinned tape SHA-256 changed");
    }
}
