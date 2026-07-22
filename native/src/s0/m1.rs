//! Exact synthetic-only M1 template and field-demultiplexing chassis.

use super::template::{fnv1a64, fnv1a64_extend};
use super::{
    split_records, ContextStore, EventDecoder, EventEncoder, EventError, JsonLayout,
    JsonLayoutError, Ledger, LossTable, Tape, TemplateError, TemplateStore,
};
use std::error::Error;
use std::fmt::{Display, Formatter};

const M1_ARM_ID: u8 = 1;
const MORE_CONTEXT: usize = 0;
const TERMINATED_CONTEXT: usize = 1;
const FALLBACK_MORE_CONTEXT: usize = 2;
const SAME_TEMPLATE_CONTEXT: usize = 3;
const VALUE_MANTISSA_BASE: usize = 4;
const VALUE_MANTISSA_CONTEXTS: usize = 210;
const BINARY_CONTEXTS: usize = VALUE_MANTISSA_BASE + VALUE_MANTISSA_CONTEXTS;

const TYPE_TREE_BASE: usize = 0;
const TYPE_TREE_COUNT: usize = 4;
const SLOT_TREE: usize = TYPE_TREE_BASE + TYPE_TREE_COUNT;
const VALUE_LENGTH_TREE_BASE: usize = SLOT_TREE + 1;
const VALUE_LENGTH_TREE_COUNT: usize = 4_096;
const VALUE_ORDER1_TREE_BASE: usize = VALUE_LENGTH_TREE_BASE + VALUE_LENGTH_TREE_COUNT;
const VALUE_ORDER_TREE_COUNT: usize = 8_192;
const VALUE_ORDER2_TREE_BASE: usize = VALUE_ORDER1_TREE_BASE + VALUE_ORDER_TREE_COUNT;
const MAX_VALUE_BYTES: usize = 1 << 20;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u32)]
enum RecordType {
    Hit = 0,
    Miss = 1,
    Fallback = 2,
    Empty = 3,
}

impl TryFrom<u32> for RecordType {
    type Error = M1Error;

    fn try_from(value: u32) -> Result<Self, Self::Error> {
        match value {
            0 => Ok(Self::Hit),
            1 => Ok(Self::Miss),
            2 => Ok(Self::Fallback),
            3 => Ok(Self::Empty),
            _ => Err(M1Error::InvalidRecordType),
        }
    }
}

pub fn encode_m1_item(
    source: &[u8],
    table: &LossTable,
    item_index: u8,
) -> Result<(Tape, Ledger), M1Error> {
    let records = split_records(source);
    let mut events = EventEncoder::new(table, m1_contexts()?, M1_ARM_ID, item_index);
    let mut templates = TemplateStore::new();
    let mut previous_type = RecordType::Miss;

    for (index, record) in records.iter().enumerate() {
        if index + 1 != records.len() && !record.terminated {
            return Err(M1Error::InvalidRecordBoundary);
        }
        events.bit(MORE_CONTEXT, true)?;
        events.record()?;
        previous_type = encode_record(record.content, previous_type, &mut events, &mut templates)?;
    }
    events.bit(MORE_CONTEXT, false)?;
    if let Some(last) = records.last() {
        events.bit(TERMINATED_CONTEXT, last.terminated)?;
    }
    Ok(events.finish())
}

pub fn decode_m1_item(
    tape: &Tape,
    expected_ledger: Ledger,
    table: &LossTable,
    expected_item_index: u8,
) -> Result<Vec<u8>, M1Error> {
    if tape.arm_id() != M1_ARM_ID || tape.item_index() != expected_item_index {
        return Err(M1Error::TapeIdentityMismatch);
    }
    let mut events = EventDecoder::new(table, m1_contexts()?, tape);
    let mut templates = TemplateStore::new();
    let mut previous_type = RecordType::Miss;
    let mut output = Vec::new();
    let mut pending_record: Option<Vec<u8>> = None;

    while events.bit(MORE_CONTEXT)? {
        if let Some(previous) = pending_record.take() {
            extend_checked(&mut output, &previous)?;
            output.push(b'\n');
        }
        events.record()?;
        let (record, record_type) = decode_record(previous_type, &mut events, &mut templates)?;
        previous_type = record_type;
        pending_record = Some(record);
    }
    if let Some(last) = pending_record {
        let terminated = events.bit(TERMINATED_CONTEXT)?;
        extend_checked(&mut output, &last)?;
        if terminated {
            output.push(b'\n');
        }
    }
    events.finish(expected_ledger)?;
    Ok(output)
}

fn encode_record(
    record: &[u8],
    previous_type: RecordType,
    events: &mut EventEncoder<'_>,
    templates: &mut TemplateStore,
) -> Result<RecordType, M1Error> {
    if record.is_empty() {
        encode_type(events, previous_type, RecordType::Empty)?;
        return Ok(RecordType::Empty);
    }

    let layout = match JsonLayout::parse(record) {
        Ok(layout) => layout,
        Err(_) => {
            encode_type(events, previous_type, RecordType::Fallback)?;
            encode_fallback(record, events)?;
            return Ok(RecordType::Fallback);
        }
    };
    let previous_slot = templates.last_slot();
    if let Some(hit) = templates.lookup(layout.skeleton()) {
        encode_type(events, previous_type, RecordType::Hit)?;
        if previous_slot.is_some() {
            events.bit(SAME_TEMPLATE_CONTEXT, hit.same_as_last)?;
        }
        if previous_slot.is_none() || !hit.same_as_last {
            events.symbol(SLOT_TREE, hit.slot as u32)?;
        }
        encode_values(layout.skeleton(), layout.values(), events)?;
        Ok(RecordType::Hit)
    } else {
        encode_type(events, previous_type, RecordType::Miss)?;
        events.literal(record)?;
        templates.insert(layout.skeleton())?;
        Ok(RecordType::Miss)
    }
}

fn decode_record(
    previous_type: RecordType,
    events: &mut EventDecoder<'_>,
    templates: &mut TemplateStore,
) -> Result<(Vec<u8>, RecordType), M1Error> {
    let record_type = RecordType::try_from(events.symbol(type_tree(previous_type))?)?;
    let record = match record_type {
        RecordType::Empty => Vec::new(),
        RecordType::Fallback => decode_fallback(events)?,
        RecordType::Miss => {
            let record = events.literal()?;
            let layout = JsonLayout::parse(&record)?;
            templates.insert(layout.skeleton())?;
            record
        }
        RecordType::Hit => {
            let previous_slot = templates.last_slot();
            let slot = if let Some(slot) = previous_slot {
                if events.bit(SAME_TEMPLATE_CONTEXT)? {
                    slot
                } else {
                    events.symbol(SLOT_TREE)? as usize
                }
            } else {
                events.symbol(SLOT_TREE)? as usize
            };
            let skeleton = templates.select(slot)?.to_vec();
            let values = decode_values(&skeleton, events)?;
            let record = JsonLayout::reconstruct_from(&skeleton, &values)?;
            let validated = JsonLayout::parse(&record)?;
            if validated.skeleton() != skeleton || validated.values() != values {
                return Err(M1Error::InvalidDecodedLayout);
            }
            record
        }
    };
    Ok((record, record_type))
}

fn encode_type(
    events: &mut EventEncoder<'_>,
    previous: RecordType,
    current: RecordType,
) -> Result<(), M1Error> {
    events.symbol(type_tree(previous), current as u32)?;
    Ok(())
}

fn type_tree(previous: RecordType) -> usize {
    TYPE_TREE_BASE + previous as usize
}

fn encode_fallback(record: &[u8], events: &mut EventEncoder<'_>) -> Result<(), M1Error> {
    let chunk_count = record.len().div_ceil(MAX_VALUE_BYTES);
    for (index, chunk) in record.chunks(MAX_VALUE_BYTES).enumerate() {
        events.literal(chunk)?;
        events.bit(FALLBACK_MORE_CONTEXT, index + 1 < chunk_count)?;
    }
    Ok(())
}

fn decode_fallback(events: &mut EventDecoder<'_>) -> Result<Vec<u8>, M1Error> {
    let mut record = Vec::new();
    loop {
        let chunk = events.literal()?;
        extend_checked(&mut record, &chunk)?;
        if !events.bit(FALLBACK_MORE_CONTEXT)? {
            return Ok(record);
        }
    }
}

fn encode_values(
    skeleton: &[u8],
    values: &[Vec<u8>],
    events: &mut EventEncoder<'_>,
) -> Result<(), M1Error> {
    for (index, value) in values.iter().enumerate() {
        let lane = lane_key(skeleton, index)?;
        events.length(
            value_length_tree(lane),
            VALUE_MANTISSA_BASE,
            value.len(),
            MAX_VALUE_BYTES,
        )?;
        let mut previous_one = 0_u8;
        let mut previous_two = 0_u8;
        for &byte in value {
            events.mixed_symbol(
                value_order1_tree(lane, previous_one),
                value_order2_tree(lane, previous_two, previous_one),
                u32::from(byte),
            )?;
            previous_two = previous_one;
            previous_one = byte;
        }
    }
    Ok(())
}

fn decode_values(skeleton: &[u8], events: &mut EventDecoder<'_>) -> Result<Vec<Vec<u8>>, M1Error> {
    let count = JsonLayout::placeholder_count(skeleton)?;
    let mut values = Vec::with_capacity(count);
    for index in 0..count {
        let lane = lane_key(skeleton, index)?;
        let length = events.length(
            value_length_tree(lane),
            VALUE_MANTISSA_BASE,
            MAX_VALUE_BYTES,
        )?;
        let mut value = Vec::new();
        value
            .try_reserve_exact(length)
            .map_err(|_| M1Error::Overflow)?;
        let mut previous_one = 0_u8;
        let mut previous_two = 0_u8;
        for _ in 0..length {
            let symbol = events.mixed_symbol(
                value_order1_tree(lane, previous_one),
                value_order2_tree(lane, previous_two, previous_one),
            )?;
            let byte = u8::try_from(symbol).map_err(|_| M1Error::InvalidValueByte)?;
            value.push(byte);
            previous_two = previous_one;
            previous_one = byte;
        }
        values.push(value);
    }
    Ok(values)
}

fn lane_key(skeleton: &[u8], index: usize) -> Result<u64, M1Error> {
    let index = u16::try_from(index).map_err(|_| M1Error::TooManyValues)?;
    Ok(fnv1a64_extend(fnv1a64(skeleton), &index.to_le_bytes()))
}

fn value_length_tree(lane: u64) -> usize {
    VALUE_LENGTH_TREE_BASE + (lane as usize & (VALUE_LENGTH_TREE_COUNT - 1))
}

fn value_order1_tree(lane: u64, previous_one: u8) -> usize {
    let context = fnv1a64_extend(lane, &[previous_one]);
    VALUE_ORDER1_TREE_BASE + (context as usize & (VALUE_ORDER_TREE_COUNT - 1))
}

fn value_order2_tree(lane: u64, previous_two: u8, previous_one: u8) -> usize {
    let context = fnv1a64_extend(lane, &[previous_two, previous_one]);
    VALUE_ORDER2_TREE_BASE + (context as usize & (VALUE_ORDER_TREE_COUNT - 1))
}

fn m1_contexts() -> Result<ContextStore, M1Error> {
    let mut alphabets = Vec::with_capacity(VALUE_ORDER2_TREE_BASE + VALUE_ORDER_TREE_COUNT);
    alphabets.extend(std::iter::repeat_n(4, TYPE_TREE_COUNT));
    alphabets.push(4_096);
    alphabets.extend(std::iter::repeat_n(21, VALUE_LENGTH_TREE_COUNT));
    alphabets.extend(std::iter::repeat_n(256, VALUE_ORDER_TREE_COUNT * 2));
    Ok(ContextStore::new(BINARY_CONTEXTS, &alphabets)?)
}

fn extend_checked(output: &mut Vec<u8>, bytes: &[u8]) -> Result<(), M1Error> {
    output
        .len()
        .checked_add(bytes.len())
        .ok_or(M1Error::Overflow)?;
    output
        .try_reserve(bytes.len())
        .map_err(|_| M1Error::Overflow)?;
    output.extend_from_slice(bytes);
    Ok(())
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum M1Error {
    Event(EventError),
    Template(TemplateError),
    Json(JsonLayoutError),
    InvalidRecordType,
    InvalidRecordBoundary,
    InvalidDecodedLayout,
    InvalidValueByte,
    TapeIdentityMismatch,
    TooManyValues,
    Overflow,
}

impl From<EventError> for M1Error {
    fn from(error: EventError) -> Self {
        Self::Event(error)
    }
}

impl From<TemplateError> for M1Error {
    fn from(error: TemplateError) -> Self {
        Self::Template(error)
    }
}

impl From<JsonLayoutError> for M1Error {
    fn from(error: JsonLayoutError) -> Self {
        Self::Json(error)
    }
}

impl Display for M1Error {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "S0 M1 error: {self:?}")
    }
}

impl Error for M1Error {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mixed_item_round_trips_all_record_types_and_delimiters() {
        let table = LossTable::generate();
        let mut source = Vec::new();
        source.extend_from_slice(b"{\"a\":1,\"b\":\"x\"}\n");
        source.extend_from_slice(b"{\"a\":2,\"b\":\"y\"}\n");
        source.extend_from_slice(b"\n");
        source.extend_from_slice(b"{bad}\n");
        source.extend(std::iter::repeat_n(b'x', MAX_VALUE_BYTES + 1));
        source.push(b'\n');
        source.extend_from_slice(b"{\"a\":3,\"b\":\"z\"}");

        let (tape, ledger) = encode_m1_item(&source, &table, 0).unwrap();
        assert_eq!(ledger.records, 6);
        assert_eq!(decode_m1_item(&tape, ledger, &table, 0).unwrap(), source);

        let (second_tape, second_ledger) = encode_m1_item(&source, &table, 0).unwrap();
        assert_eq!(second_tape.to_bytes(), tape.to_bytes());
        assert_eq!(second_ledger, ledger);
    }

    #[test]
    fn empty_item_round_trips_without_an_uncharged_terminator() {
        let table = LossTable::generate();
        let (tape, ledger) = encode_m1_item(b"", &table, 1).unwrap();
        assert_eq!(ledger.records, 0);
        assert_eq!(ledger.modeled_binary_events, 1);
        assert_eq!(decode_m1_item(&tape, ledger, &table, 1).unwrap(), b"");
    }

    #[test]
    fn decoder_rejects_a_hit_on_an_empty_template_slot() {
        let table = LossTable::generate();
        let mut events = EventEncoder::new(&table, m1_contexts().unwrap(), M1_ARM_ID, 0);
        events.bit(MORE_CONTEXT, true).unwrap();
        events.record().unwrap();
        events
            .symbol(type_tree(RecordType::Miss), RecordType::Hit as u32)
            .unwrap();
        events.symbol(SLOT_TREE, 0).unwrap();
        events.bit(MORE_CONTEXT, false).unwrap();
        events.bit(TERMINATED_CONTEXT, false).unwrap();
        let (tape, ledger) = events.finish();
        assert_eq!(
            decode_m1_item(&tape, ledger, &table, 0),
            Err(M1Error::Template(TemplateError::EmptySlot))
        );
    }

    #[test]
    fn alternating_templates_exercise_charged_non_same_slot_hits() {
        let table = LossTable::generate();
        let source = b"{\"a\":1}\n{\"b\":2}\n{\"a\":3}\n{\"b\":4}\n";
        let (tape, ledger) = encode_m1_item(source, &table, 2).unwrap();
        assert_eq!(decode_m1_item(&tape, ledger, &table, 2).unwrap(), source);
        assert!(ledger.records == 4 && ledger.raw_literal_bytes > 0);
    }

    #[test]
    fn decoded_value_cannot_inject_new_structure() {
        let table = LossTable::generate();
        let first = JsonLayout::parse(b"{\"a\":1}").unwrap();
        let skeleton = first.skeleton();
        let injected = b"1,\"b\":2";
        let lane = lane_key(skeleton, 0).unwrap();
        let mut events = EventEncoder::new(&table, m1_contexts().unwrap(), M1_ARM_ID, 0);

        events.bit(MORE_CONTEXT, true).unwrap();
        events.record().unwrap();
        events
            .symbol(type_tree(RecordType::Miss), RecordType::Miss as u32)
            .unwrap();
        events.literal(b"{\"a\":1}").unwrap();

        events.bit(MORE_CONTEXT, true).unwrap();
        events.record().unwrap();
        events
            .symbol(type_tree(RecordType::Miss), RecordType::Hit as u32)
            .unwrap();
        events.bit(SAME_TEMPLATE_CONTEXT, true).unwrap();
        events
            .length(
                value_length_tree(lane),
                VALUE_MANTISSA_BASE,
                injected.len(),
                MAX_VALUE_BYTES,
            )
            .unwrap();
        let mut previous_one = 0_u8;
        let mut previous_two = 0_u8;
        for &byte in injected {
            events
                .mixed_symbol(
                    value_order1_tree(lane, previous_one),
                    value_order2_tree(lane, previous_two, previous_one),
                    u32::from(byte),
                )
                .unwrap();
            previous_two = previous_one;
            previous_one = byte;
        }
        events.bit(MORE_CONTEXT, false).unwrap();
        events.bit(TERMINATED_CONTEXT, false).unwrap();
        let (tape, ledger) = events.finish();
        assert_eq!(
            decode_m1_item(&tape, ledger, &table, 0),
            Err(M1Error::InvalidDecodedLayout)
        );
    }

    #[test]
    fn decoder_binds_tape_arm_and_item_identity() {
        let table = LossTable::generate();
        let (tape, ledger) = encode_m1_item(b"{}", &table, 2).unwrap();
        assert_eq!(
            decode_m1_item(&tape, ledger, &table, 1),
            Err(M1Error::TapeIdentityMismatch)
        );
    }
}
