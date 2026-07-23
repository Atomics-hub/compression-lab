//! Arm 0: single raw byte stream with order-3 context modeling.
//!
//! The diagnostic baseline arm ignores all structure: every source byte is
//! one modeled 256-way symbol whose context is the previous three bytes
//! hashed into a bounded tree bank, preceded by one continuation bit. There
//! is no record grammar, no literal channel, and no per-record event budget
//! (attribution arms may exceed it; only the full arm decides).

use super::chassis::{ChassisError, SegmentSnapshot};
use super::template::{fnv1a64, fnv1a64_extend};
use super::{split_records, ContextStore, EventDecoder, EventEncoder, Ledger, LossTable, Tape};

pub const RAW_ARM_ID: u8 = 0;

/// Order-3 contexts are hashed into this many 256-way trees. The bank is the
/// dominant table: 262,144 trees x 255 nodes x 2 bytes = 127.5 MiB, inside
/// the frozen 192 MiB context-table maximum.
pub const RAW_ORDER3_TREES: usize = 1 << 18;
const MORE_CONTEXT: usize = 0;
const RAW_BINARY_CONTEXTS: usize = 1;
const BYTE_ALPHABET: u32 = 256;

const _: () = assert!(RAW_ORDER3_TREES.is_power_of_two());
const _: () = assert!(RAW_ORDER3_TREES * 255 * 2 <= 192 * 1_048_576);

fn raw_contexts() -> Result<ContextStore, ChassisError> {
    let alphabets = vec![BYTE_ALPHABET; RAW_ORDER3_TREES];
    Ok(ContextStore::new(RAW_BINARY_CONTEXTS, &alphabets)?)
}

fn order3_tree(history: [u8; 3]) -> usize {
    let hash = fnv1a64_extend(fnv1a64(b"s0-raw-o3"), &history);
    hash as usize & (RAW_ORDER3_TREES - 1)
}

pub fn encode_raw_o3_item(
    source: &[u8],
    table: &LossTable,
    item_index: u8,
) -> Result<(Tape, Ledger), ChassisError> {
    let (tape, ledger, _) = encode_raw_o3_item_with_segments(source, table, item_index, None)?;
    Ok((tape, ledger))
}

/// Byte-identical to [`encode_raw_o3_item`]; additionally closes diagnostic
/// segment snapshots at the first record boundary at or after each
/// `segment_bytes` interval, with no model state reset.
pub fn encode_raw_o3_item_with_segments(
    source: &[u8],
    table: &LossTable,
    item_index: u8,
    segment_bytes: Option<u64>,
) -> Result<(Tape, Ledger, Vec<SegmentSnapshot>), ChassisError> {
    if segment_bytes == Some(0) {
        return Err(ChassisError::InvalidSegmentInterval);
    }
    let mut events = EventEncoder::new(table, raw_contexts()?, RAW_ARM_ID, item_index);
    let mut history = [0_u8; 3];
    let encode_byte = |events: &mut EventEncoder<'_>, history: &mut [u8; 3], byte: u8| {
        events.bit(MORE_CONTEXT, true)?;
        events.symbol(order3_tree(*history), u32::from(byte))?;
        *history = [history[1], history[2], byte];
        Ok::<(), ChassisError>(())
    };
    let mut snapshots = Vec::new();
    let mut consumed: u64 = 0;
    let mut next_boundary = segment_bytes;
    for (index, record) in split_records(source).into_iter().enumerate() {
        for &byte in record.content {
            encode_byte(&mut events, &mut history, byte)?;
        }
        if record.terminated {
            encode_byte(&mut events, &mut history, b'\n')?;
        }
        consumed += record.content.len() as u64 + u64::from(record.terminated);
        if let (Some(boundary), Some(interval)) = (next_boundary, segment_bytes) {
            if consumed >= boundary {
                snapshots.push(SegmentSnapshot {
                    records: index as u64 + 1,
                    source_bytes: consumed,
                    ledger: events.ledger(),
                });
                let mut advanced = boundary;
                while consumed >= advanced {
                    advanced += interval;
                }
                next_boundary = Some(advanced);
            }
        }
    }
    events.bit(MORE_CONTEXT, false)?;
    let (tape, ledger) = events.finish();
    Ok((tape, ledger, snapshots))
}

pub fn decode_raw_o3_item(
    tape: &Tape,
    expected_ledger: Ledger,
    table: &LossTable,
    expected_item_index: u8,
) -> Result<Vec<u8>, ChassisError> {
    if tape.arm_id() != RAW_ARM_ID || tape.item_index() != expected_item_index {
        return Err(ChassisError::TapeIdentityMismatch);
    }
    let mut events = EventDecoder::new(table, raw_contexts()?, tape);
    let mut history = [0_u8; 3];
    let mut output = Vec::new();
    while events.bit(MORE_CONTEXT)? {
        let symbol = events.symbol(order3_tree(history))?;
        let byte = u8::try_from(symbol).map_err(|_| ChassisError::InvalidValueByte)?;
        output.push(byte);
        history = [history[1], history[2], byte];
    }
    events.finish(expected_ledger)?;
    Ok(output)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn raw_stream_round_trips_arbitrary_bytes_exactly() {
        let table = LossTable::generate();
        let mut source = Vec::new();
        source.extend_from_slice(b"{\"json\":1}\nplain text\n");
        source.extend((0..=255_u16).map(|byte| byte as u8));
        source.extend(std::iter::repeat_n(b'z', 4_096));

        let (tape, ledger) = encode_raw_o3_item(&source, &table, 0).unwrap();
        assert_eq!(
            decode_raw_o3_item(&tape, ledger, &table, 0).unwrap(),
            source
        );
        assert_eq!(
            ledger.modeled_binary_events,
            source.len() as u64 * 9 + 1,
            "one continuation bit plus eight tree bits per byte"
        );
        assert_eq!(ledger.raw_literal_bytes, 0);

        let (repeat_tape, repeat_ledger) = encode_raw_o3_item(&source, &table, 0).unwrap();
        assert_eq!(repeat_tape.to_bytes(), tape.to_bytes());
        assert_eq!(repeat_ledger, ledger);
    }

    #[test]
    fn empty_item_costs_one_event_and_identity_is_bound() {
        let table = LossTable::generate();
        let (tape, ledger) = encode_raw_o3_item(b"", &table, 1).unwrap();
        assert_eq!(ledger.modeled_binary_events, 1);
        assert_eq!(decode_raw_o3_item(&tape, ledger, &table, 1).unwrap(), b"");
        assert_eq!(
            decode_raw_o3_item(&tape, ledger, &table, 2),
            Err(ChassisError::TapeIdentityMismatch)
        );
    }

    #[test]
    fn repeated_context_bytes_get_cheaper() {
        // The order-3 model must learn a repeating pattern: the second half
        // of a periodic stream costs less than the first half.
        let table = LossTable::generate();
        let pattern: Vec<u8> = b"abcd".repeat(512);
        let (_, full) = encode_raw_o3_item(&pattern, &table, 3).unwrap();
        let (_, half) = encode_raw_o3_item(&pattern[..pattern.len() / 2], &table, 3).unwrap();
        assert!(full.modeled_loss_q24 < 2 * half.modeled_loss_q24);
    }
}
