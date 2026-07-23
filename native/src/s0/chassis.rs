//! Shared exact record chassis for S0 arms.
//!
//! The chassis owns record framing, template grammar, fallback and empty
//! records, and the frozen M1 prefix of the context layout. Mechanism arms
//! plug in through [`ValueCoder`] hooks, supply their arm identity explicitly,
//! and append their contexts strictly after the unchanged M1 prefix via
//! [`chassis_contexts`].

use super::event::MAX_LITERAL_RUN;
use super::m5::M5Mixer;
use super::template::{fnv1a64, fnv1a64_extend, TEMPLATE_SLOTS};
use super::{
    split_records, ContextStore, EventDecoder, EventEncoder, EventError, JsonLayout,
    JsonLayoutError, Ledger, LossTable, Tape, TemplateError, TemplateStore,
};
use std::error::Error;
use std::fmt::{Display, Formatter};

pub const MORE_CONTEXT: usize = 0;
pub const TERMINATED_CONTEXT: usize = 1;
pub const FALLBACK_MORE_CONTEXT: usize = 2;
pub const SAME_TEMPLATE_CONTEXT: usize = 3;
pub const VALUE_MANTISSA_BASE: usize = 4;
pub const VALUE_MANTISSA_CONTEXTS: usize = 210;
pub const M1_BINARY_CONTEXTS: usize = VALUE_MANTISSA_BASE + VALUE_MANTISSA_CONTEXTS;

pub const TYPE_TREE_BASE: usize = 0;
pub const TYPE_TREE_COUNT: usize = 4;
pub const SLOT_TREE: usize = TYPE_TREE_BASE + TYPE_TREE_COUNT;
pub const VALUE_LENGTH_TREE_BASE: usize = SLOT_TREE + 1;
pub const VALUE_LENGTH_TREE_COUNT: usize = 4_096;
pub const VALUE_ORDER1_TREE_BASE: usize = VALUE_LENGTH_TREE_BASE + VALUE_LENGTH_TREE_COUNT;
pub const VALUE_ORDER_TREE_COUNT: usize = 8_192;
pub const VALUE_ORDER2_TREE_BASE: usize = VALUE_ORDER1_TREE_BASE + VALUE_ORDER_TREE_COUNT;
pub const M1_TREE_CONTEXTS: usize = VALUE_ORDER2_TREE_BASE + VALUE_ORDER_TREE_COUNT;

pub const TYPE_TREE_ALPHABET: u32 = 4;
pub const SLOT_TREE_ALPHABET: u32 = TEMPLATE_SLOTS as u32;
pub const VALUE_LENGTH_ALPHABET: u32 = 21;
pub const VALUE_BYTE_ALPHABET: u32 = 256;
pub const MAX_VALUE_BYTES: usize = 1 << 20;

// The frozen M1 context prefix. Any change to one of these boundaries changes
// the charged bit stream, so every edge is pinned at compile time.
const _: () = assert!(MORE_CONTEXT == 0);
const _: () = assert!(TERMINATED_CONTEXT == MORE_CONTEXT + 1);
const _: () = assert!(FALLBACK_MORE_CONTEXT == TERMINATED_CONTEXT + 1);
const _: () = assert!(SAME_TEMPLATE_CONTEXT == FALLBACK_MORE_CONTEXT + 1);
const _: () = assert!(VALUE_MANTISSA_BASE == SAME_TEMPLATE_CONTEXT + 1);
const _: () = assert!(M1_BINARY_CONTEXTS == 214);
const _: () = assert!(TYPE_TREE_BASE == 0);
const _: () = assert!(SLOT_TREE == 4);
const _: () = assert!(VALUE_LENGTH_TREE_BASE == 5);
const _: () = assert!(VALUE_ORDER1_TREE_BASE == 4_101);
const _: () = assert!(VALUE_ORDER2_TREE_BASE == 12_293);
const _: () = assert!(M1_TREE_CONTEXTS == 20_485);
const _: () = assert!(SLOT_TREE_ALPHABET as usize == TEMPLATE_SLOTS);
const _: () = assert!(TYPE_TREE_ALPHABET == 4);
const _: () = assert!(TYPE_TREE_COUNT == TYPE_TREE_ALPHABET as usize);
const _: () = assert!(RecordType::Empty as usize + 1 == TYPE_TREE_ALPHABET as usize);
const _: () = assert!(VALUE_BYTE_ALPHABET == 256);
const _: () = assert!(MAX_VALUE_BYTES == MAX_LITERAL_RUN);
const _: () = assert!(
    VALUE_MANTISSA_CONTEXTS
        == (VALUE_LENGTH_ALPHABET as usize * (VALUE_LENGTH_ALPHABET as usize - 1)) / 2
);
const _: () = assert!(VALUE_LENGTH_ALPHABET as usize == MAX_VALUE_BYTES.ilog2() as usize + 1);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u32)]
pub enum RecordType {
    Hit = 0,
    Miss = 1,
    Fallback = 2,
    Empty = 3,
}

impl TryFrom<u32> for RecordType {
    type Error = ChassisError;

    fn try_from(value: u32) -> Result<Self, Self::Error> {
        match value {
            0 => Ok(Self::Hit),
            1 => Ok(Self::Miss),
            2 => Ok(Self::Fallback),
            3 => Ok(Self::Empty),
            _ => Err(ChassisError::InvalidRecordType),
        }
    }
}

/// Per-lane value coding hooks. The chassis charges all framing, template,
/// fallback, and empty-record grammar itself; a coder only observes template
/// mutations and codes the exact bytes of each top-level value on a hit.
///
/// Encoder and decoder must drive the same hook sequence for identical input:
/// the chassis calls `on_slots_cleared` then `after_miss_insert` for every
/// cacheable miss, in that order, on both sides.
pub trait ValueCoder {
    fn encode_value(
        &mut self,
        events: &mut EventEncoder<'_>,
        slot: usize,
        lane_index: usize,
        lane_key: u64,
        bytes: &[u8],
    ) -> Result<(), ChassisError>;

    fn decode_value(
        &mut self,
        events: &mut EventDecoder<'_>,
        slot: usize,
        lane_index: usize,
        lane_key: u64,
    ) -> Result<Vec<u8>, ChassisError>;

    fn after_miss_insert(&mut self, slot: usize, layout: &JsonLayout) -> Result<(), ChassisError>;

    fn on_slots_cleared(&mut self, cleared_slots: &[usize]) -> Result<(), ChassisError>;
}

/// The default M1 value coder: shared modeled lengths plus mixed order-1 and
/// order-2 byte models, with no per-slot state.
pub struct M1ValueCoder;

impl ValueCoder for M1ValueCoder {
    fn encode_value(
        &mut self,
        events: &mut EventEncoder<'_>,
        _slot: usize,
        _lane_index: usize,
        lane_key: u64,
        bytes: &[u8],
    ) -> Result<(), ChassisError> {
        encode_m1_value(events, lane_key, bytes)
    }

    fn decode_value(
        &mut self,
        events: &mut EventDecoder<'_>,
        _slot: usize,
        _lane_index: usize,
        lane_key: u64,
    ) -> Result<Vec<u8>, ChassisError> {
        decode_m1_value(events, lane_key)
    }

    fn after_miss_insert(
        &mut self,
        _slot: usize,
        _layout: &JsonLayout,
    ) -> Result<(), ChassisError> {
        Ok(())
    }

    fn on_slots_cleared(&mut self, _cleared_slots: &[usize]) -> Result<(), ChassisError> {
        Ok(())
    }
}

/// Build the frozen M1 context prefix and append mechanism contexts after it.
/// Extra binary contexts start at `M1_BINARY_CONTEXTS` and extra tree contexts
/// start at `M1_TREE_CONTEXTS`, in the order supplied.
pub fn chassis_contexts(
    extra_binary_contexts: usize,
    extra_tree_alphabets: &[u32],
) -> Result<ContextStore, ChassisError> {
    let binary_contexts = M1_BINARY_CONTEXTS
        .checked_add(extra_binary_contexts)
        .ok_or(ChassisError::Overflow)?;
    let mut alphabets = Vec::with_capacity(
        M1_TREE_CONTEXTS
            .checked_add(extra_tree_alphabets.len())
            .ok_or(ChassisError::Overflow)?,
    );
    alphabets.extend(std::iter::repeat_n(TYPE_TREE_ALPHABET, TYPE_TREE_COUNT));
    alphabets.push(SLOT_TREE_ALPHABET);
    alphabets.extend(std::iter::repeat_n(
        VALUE_LENGTH_ALPHABET,
        VALUE_LENGTH_TREE_COUNT,
    ));
    alphabets.extend(std::iter::repeat_n(
        VALUE_BYTE_ALPHABET,
        VALUE_ORDER_TREE_COUNT * 2,
    ));
    alphabets.extend_from_slice(extra_tree_alphabets);
    Ok(ContextStore::new(binary_contexts, &alphabets)?)
}

pub fn encode_chassis_item<C: ValueCoder>(
    source: &[u8],
    table: &LossTable,
    contexts: ContextStore,
    arm_id: u8,
    item_index: u8,
    coder: &mut C,
) -> Result<(Tape, Ledger), ChassisError> {
    let (tape, ledger, _) = encode_chassis_item_with_segments(
        source, table, contexts, arm_id, item_index, coder, None,
    )?;
    Ok((tape, ledger))
}

pub fn encode_chassis_item_with_segments<C: ValueCoder>(
    source: &[u8],
    table: &LossTable,
    contexts: ContextStore,
    arm_id: u8,
    item_index: u8,
    coder: &mut C,
    segment_bytes: Option<u64>,
) -> Result<(Tape, Ledger, Vec<SegmentSnapshot>), ChassisError> {
    let events = EventEncoder::new(table, contexts, arm_id, item_index);
    encode_chassis_records_with_segments(source, events, coder, segment_bytes)
}

/// M5 arms: identical grammar and tape bits, refined charged probabilities.
#[allow(clippy::too_many_arguments)]
pub fn encode_chassis_item_with_mixer<C: ValueCoder>(
    source: &[u8],
    table: &LossTable,
    contexts: ContextStore,
    arm_id: u8,
    item_index: u8,
    coder: &mut C,
    mixer: Box<M5Mixer>,
) -> Result<(Tape, Ledger), ChassisError> {
    let (tape, ledger, _) = encode_chassis_item_with_mixer_and_segments(
        source, table, contexts, arm_id, item_index, coder, mixer, None,
    )?;
    Ok((tape, ledger))
}

/// Mixer variant of [`encode_chassis_item_with_segments`].
#[allow(clippy::too_many_arguments)]
pub fn encode_chassis_item_with_mixer_and_segments<C: ValueCoder>(
    source: &[u8],
    table: &LossTable,
    contexts: ContextStore,
    arm_id: u8,
    item_index: u8,
    coder: &mut C,
    mixer: Box<M5Mixer>,
    segment_bytes: Option<u64>,
) -> Result<(Tape, Ledger, Vec<SegmentSnapshot>), ChassisError> {
    let events = EventEncoder::with_mixer(table, contexts, arm_id, item_index, mixer);
    encode_chassis_records_with_segments(source, events, coder, segment_bytes)
}

/// Diagnostic-only segment ledger: closes a snapshot at the first record
/// boundary at or after each `segment_bytes` interval of consumed source.
/// No model state resets at a segment boundary, and snapshots never enter
/// decision calculations.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct SegmentSnapshot {
    pub records: u64,
    pub source_bytes: u64,
    pub ledger: Ledger,
}

fn encode_chassis_records_with_segments<C: ValueCoder>(
    source: &[u8],
    mut events: EventEncoder<'_>,
    coder: &mut C,
    segment_bytes: Option<u64>,
) -> Result<(Tape, Ledger, Vec<SegmentSnapshot>), ChassisError> {
    if segment_bytes == Some(0) {
        return Err(ChassisError::InvalidSegmentInterval);
    }
    let records = split_records(source);
    let mut templates = TemplateStore::new();
    let mut previous_type = RecordType::Miss;
    let mut snapshots = Vec::new();
    let mut consumed: u64 = 0;
    let mut next_boundary = segment_bytes;

    for (index, record) in records.iter().enumerate() {
        if index + 1 != records.len() && !record.terminated {
            return Err(ChassisError::InvalidRecordBoundary);
        }
        events.bit(MORE_CONTEXT, true)?;
        events.record()?;
        previous_type = encode_record(
            record.content,
            previous_type,
            &mut events,
            &mut templates,
            coder,
        )?;
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
    if let Some(last) = records.last() {
        events.bit(TERMINATED_CONTEXT, last.terminated)?;
    }
    let (tape, ledger) = events.finish();
    Ok((tape, ledger, snapshots))
}

pub fn decode_chassis_item<C: ValueCoder>(
    tape: &Tape,
    expected_ledger: Ledger,
    table: &LossTable,
    contexts: ContextStore,
    expected_arm_id: u8,
    expected_item_index: u8,
    coder: &mut C,
) -> Result<Vec<u8>, ChassisError> {
    if tape.arm_id() != expected_arm_id || tape.item_index() != expected_item_index {
        return Err(ChassisError::TapeIdentityMismatch);
    }
    let events = EventDecoder::new(table, contexts, tape);
    decode_chassis_records(events, expected_ledger, coder)
}

/// Mirror of [`encode_chassis_item_with_mixer`].
#[allow(clippy::too_many_arguments)]
pub fn decode_chassis_item_with_mixer<C: ValueCoder>(
    tape: &Tape,
    expected_ledger: Ledger,
    table: &LossTable,
    contexts: ContextStore,
    expected_arm_id: u8,
    expected_item_index: u8,
    coder: &mut C,
    mixer: Box<M5Mixer>,
) -> Result<Vec<u8>, ChassisError> {
    if tape.arm_id() != expected_arm_id || tape.item_index() != expected_item_index {
        return Err(ChassisError::TapeIdentityMismatch);
    }
    let events = EventDecoder::with_mixer(table, contexts, tape, mixer);
    decode_chassis_records(events, expected_ledger, coder)
}

fn decode_chassis_records<C: ValueCoder>(
    mut events: EventDecoder<'_>,
    expected_ledger: Ledger,
    coder: &mut C,
) -> Result<Vec<u8>, ChassisError> {
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
        let (record, record_type) =
            decode_record(previous_type, &mut events, &mut templates, coder)?;
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

fn encode_record<C: ValueCoder>(
    record: &[u8],
    previous_type: RecordType,
    events: &mut EventEncoder<'_>,
    templates: &mut TemplateStore,
    coder: &mut C,
) -> Result<RecordType, ChassisError> {
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
        for (index, value) in layout.values().iter().enumerate() {
            let lane = lane_key(layout.skeleton(), index)?;
            coder.encode_value(events, hit.slot, index, lane, value)?;
        }
        Ok(RecordType::Hit)
    } else {
        encode_type(events, previous_type, RecordType::Miss)?;
        events.literal(record)?;
        let outcome = templates.insert(layout.skeleton())?;
        coder.on_slots_cleared(&outcome.cleared)?;
        if let Some(slot) = outcome.inserted {
            coder.after_miss_insert(slot, &layout)?;
        }
        Ok(RecordType::Miss)
    }
}

fn decode_record<C: ValueCoder>(
    previous_type: RecordType,
    events: &mut EventDecoder<'_>,
    templates: &mut TemplateStore,
    coder: &mut C,
) -> Result<(Vec<u8>, RecordType), ChassisError> {
    let record_type = RecordType::try_from(events.symbol(type_tree(previous_type))?)?;
    let record = match record_type {
        RecordType::Empty => Vec::new(),
        RecordType::Fallback => decode_fallback(events)?,
        RecordType::Miss => {
            let record = events.literal()?;
            let layout = JsonLayout::parse(&record)?;
            let outcome = templates.insert(layout.skeleton())?;
            coder.on_slots_cleared(&outcome.cleared)?;
            if let Some(slot) = outcome.inserted {
                coder.after_miss_insert(slot, &layout)?;
            }
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
            let count = JsonLayout::placeholder_count(&skeleton)?;
            let mut values = Vec::with_capacity(count);
            for index in 0..count {
                let lane = lane_key(&skeleton, index)?;
                values.push(coder.decode_value(events, slot, index, lane)?);
            }
            let record = JsonLayout::reconstruct_from(&skeleton, &values)?;
            let validated = JsonLayout::parse(&record)?;
            if validated.skeleton() != skeleton || validated.values() != values {
                return Err(ChassisError::InvalidDecodedLayout);
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
) -> Result<(), ChassisError> {
    events.symbol(type_tree(previous), current as u32)?;
    Ok(())
}

pub fn type_tree(previous: RecordType) -> usize {
    TYPE_TREE_BASE + previous as usize
}

fn encode_fallback(record: &[u8], events: &mut EventEncoder<'_>) -> Result<(), ChassisError> {
    let chunk_count = record.len().div_ceil(MAX_VALUE_BYTES);
    for (index, chunk) in record.chunks(MAX_VALUE_BYTES).enumerate() {
        events.literal(chunk)?;
        events.bit(FALLBACK_MORE_CONTEXT, index + 1 < chunk_count)?;
    }
    Ok(())
}

fn decode_fallback(events: &mut EventDecoder<'_>) -> Result<Vec<u8>, ChassisError> {
    let mut record = Vec::new();
    loop {
        let chunk = events.literal()?;
        extend_checked(&mut record, &chunk)?;
        if !events.bit(FALLBACK_MORE_CONTEXT)? {
            return Ok(record);
        }
    }
}

/// The unchanged M1 value coding, callable directly so later mechanisms can
/// escape into it without altering its charged sequence.
pub fn encode_m1_value(
    events: &mut EventEncoder<'_>,
    lane: u64,
    bytes: &[u8],
) -> Result<(), ChassisError> {
    events.length(
        value_length_tree(lane),
        VALUE_MANTISSA_BASE,
        bytes.len(),
        MAX_VALUE_BYTES,
    )?;
    let mut previous_one = 0_u8;
    let mut previous_two = 0_u8;
    for &byte in bytes {
        events.mixed_symbol(
            value_order1_tree(lane, previous_one),
            value_order2_tree(lane, previous_two, previous_one),
            u32::from(byte),
        )?;
        previous_two = previous_one;
        previous_one = byte;
    }
    Ok(())
}

pub fn decode_m1_value(events: &mut EventDecoder<'_>, lane: u64) -> Result<Vec<u8>, ChassisError> {
    let length = events.length(
        value_length_tree(lane),
        VALUE_MANTISSA_BASE,
        MAX_VALUE_BYTES,
    )?;
    let mut value = Vec::new();
    value
        .try_reserve_exact(length)
        .map_err(|_| ChassisError::Overflow)?;
    let mut previous_one = 0_u8;
    let mut previous_two = 0_u8;
    for _ in 0..length {
        let symbol = events.mixed_symbol(
            value_order1_tree(lane, previous_one),
            value_order2_tree(lane, previous_two, previous_one),
        )?;
        let byte = u8::try_from(symbol).map_err(|_| ChassisError::InvalidValueByte)?;
        value.push(byte);
        previous_two = previous_one;
        previous_one = byte;
    }
    Ok(value)
}

pub fn lane_key(skeleton: &[u8], index: usize) -> Result<u64, ChassisError> {
    let index = u16::try_from(index).map_err(|_| ChassisError::TooManyValues)?;
    Ok(fnv1a64_extend(fnv1a64(skeleton), &index.to_le_bytes()))
}

pub fn value_length_tree(lane: u64) -> usize {
    VALUE_LENGTH_TREE_BASE + (lane as usize & (VALUE_LENGTH_TREE_COUNT - 1))
}

pub fn value_order1_tree(lane: u64, previous_one: u8) -> usize {
    let context = fnv1a64_extend(lane, &[previous_one]);
    VALUE_ORDER1_TREE_BASE + (context as usize & (VALUE_ORDER_TREE_COUNT - 1))
}

pub fn value_order2_tree(lane: u64, previous_two: u8, previous_one: u8) -> usize {
    let context = fnv1a64_extend(lane, &[previous_two, previous_one]);
    VALUE_ORDER2_TREE_BASE + (context as usize & (VALUE_ORDER_TREE_COUNT - 1))
}

fn extend_checked(output: &mut Vec<u8>, bytes: &[u8]) -> Result<(), ChassisError> {
    output
        .len()
        .checked_add(bytes.len())
        .ok_or(ChassisError::Overflow)?;
    output
        .try_reserve(bytes.len())
        .map_err(|_| ChassisError::Overflow)?;
    output.extend_from_slice(bytes);
    Ok(())
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ChassisError {
    Event(EventError),
    Template(TemplateError),
    Json(JsonLayoutError),
    InvalidRecordType,
    InvalidRecordBoundary,
    InvalidDecodedLayout,
    InvalidValueByte,
    TapeIdentityMismatch,
    TooManyValues,
    InvalidSegmentInterval,
    LaneOutOfRange,
    DeltaOverflow,
    SessionReference,
    TokenReference,
    Overflow,
}

impl From<EventError> for ChassisError {
    fn from(error: EventError) -> Self {
        Self::Event(error)
    }
}

impl From<TemplateError> for ChassisError {
    fn from(error: TemplateError) -> Self {
        Self::Template(error)
    }
}

impl From<JsonLayoutError> for ChassisError {
    fn from(error: JsonLayoutError) -> Self {
        Self::Json(error)
    }
}

impl Display for ChassisError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "S0 chassis error: {self:?}")
    }
}

impl Error for ChassisError {}

#[cfg(test)]
mod tests {
    use super::super::m1::M1_ARM_ID;
    use super::super::{decode_m1_item, encode_m1_item};
    use super::*;

    fn m1_contexts() -> ContextStore {
        chassis_contexts(0, &[]).unwrap()
    }

    #[test]
    fn decoder_rejects_a_hit_on_an_empty_template_slot() {
        let table = LossTable::generate();
        let mut events = EventEncoder::new(&table, m1_contexts(), M1_ARM_ID, 0);
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
            Err(ChassisError::Template(TemplateError::EmptySlot))
        );
    }

    #[test]
    fn decoded_value_cannot_inject_new_structure() {
        let table = LossTable::generate();
        let first = JsonLayout::parse(b"{\"a\":1}").unwrap();
        let skeleton = first.skeleton();
        let injected = b"1,\"b\":2";
        let lane = lane_key(skeleton, 0).unwrap();
        let mut events = EventEncoder::new(&table, m1_contexts(), M1_ARM_ID, 0);

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
        encode_m1_value(&mut events, lane, injected).unwrap();
        events.bit(MORE_CONTEXT, false).unwrap();
        events.bit(TERMINATED_CONTEXT, false).unwrap();
        let (tape, ledger) = events.finish();
        assert_eq!(
            decode_m1_item(&tape, ledger, &table, 0),
            Err(ChassisError::InvalidDecodedLayout)
        );
    }

    #[test]
    fn chassis_contexts_append_strictly_after_the_m1_prefix() {
        let table = LossTable::generate();
        let mut encoder = EventEncoder::new(&table, chassis_contexts(2, &[7]).unwrap(), 9, 0);
        // The first appended binary context and tree context are addressable
        // exactly at the published M1 boundary.
        encoder.bit(M1_BINARY_CONTEXTS, true).unwrap();
        encoder.bit(M1_BINARY_CONTEXTS + 1, false).unwrap();
        encoder.symbol(M1_TREE_CONTEXTS, 6).unwrap();
        assert_eq!(
            encoder.bit(M1_BINARY_CONTEXTS + 2, true),
            Err(EventError::ContextOutOfRange)
        );
        assert_eq!(
            encoder.symbol(M1_TREE_CONTEXTS + 1, 0),
            Err(EventError::ContextOutOfRange)
        );
        assert_eq!(
            encoder.symbol(M1_TREE_CONTEXTS, 7),
            Err(EventError::SymbolOutOfRange)
        );

        let base = chassis_contexts(0, &[]).unwrap();
        let extended = chassis_contexts(2, &[7]).unwrap();
        // 2 binary flags + one 7-symbol tree (7 nodes in a width-3 tree).
        assert_eq!(
            extended.modeled_state_bytes() - base.modeled_state_bytes(),
            (2 + 7) * 2
        );
    }

    /// A probe coder proving hook ordering, hook arguments, and that the
    /// chassis drives encoder and decoder through identical hook sequences.
    #[derive(Default)]
    struct ProbeCoder {
        log: Vec<String>,
    }

    impl ValueCoder for ProbeCoder {
        fn encode_value(
            &mut self,
            events: &mut EventEncoder<'_>,
            slot: usize,
            lane_index: usize,
            lane_key: u64,
            bytes: &[u8],
        ) -> Result<(), ChassisError> {
            self.log
                .push(format!("value slot={slot} lane={lane_index}"));
            assert_eq!(
                lane_key,
                super::lane_key(&skeleton_for_probe(slot), lane_index).unwrap()
            );
            encode_m1_value(events, lane_key, bytes)
        }

        fn decode_value(
            &mut self,
            events: &mut EventDecoder<'_>,
            slot: usize,
            lane_index: usize,
            lane_key: u64,
        ) -> Result<Vec<u8>, ChassisError> {
            self.log
                .push(format!("value slot={slot} lane={lane_index}"));
            decode_m1_value(events, lane_key)
        }

        fn after_miss_insert(
            &mut self,
            slot: usize,
            layout: &JsonLayout,
        ) -> Result<(), ChassisError> {
            self.log.push(format!(
                "insert slot={slot} values={}",
                layout.values().len()
            ));
            Ok(())
        }

        fn on_slots_cleared(&mut self, cleared_slots: &[usize]) -> Result<(), ChassisError> {
            self.log.push(format!("cleared {cleared_slots:?}"));
            Ok(())
        }
    }

    fn skeleton_for_probe(slot: usize) -> Vec<u8> {
        let source: &[u8] = match slot {
            0 => b"{\"a\":1,\"b\":2}",
            1 => b"{\"c\":3}",
            _ => panic!("unexpected probe slot {slot}"),
        };
        JsonLayout::parse(source).unwrap().skeleton().to_vec()
    }

    #[test]
    fn hooks_fire_in_frozen_order_and_symmetrically_on_both_sides() {
        let table = LossTable::generate();
        let source = b"{\"a\":1,\"b\":2}\n{\"c\":3}\n{\"a\":4,\"b\":5}\n{bad}\n\n{\"c\":6}\n";
        let mut encode_probe = ProbeCoder::default();
        let (tape, ledger) = encode_chassis_item(
            source,
            &table,
            chassis_contexts(0, &[]).unwrap(),
            7,
            3,
            &mut encode_probe,
        )
        .unwrap();
        let expected_log = vec![
            "cleared []".to_string(),
            "insert slot=0 values=2".to_string(),
            "cleared []".to_string(),
            "insert slot=1 values=1".to_string(),
            "value slot=0 lane=0".to_string(),
            "value slot=0 lane=1".to_string(),
            "value slot=1 lane=0".to_string(),
        ];
        assert_eq!(encode_probe.log, expected_log);

        let mut decode_probe = ProbeCoder::default();
        let decoded = decode_chassis_item(
            &tape,
            ledger,
            &table,
            chassis_contexts(0, &[]).unwrap(),
            7,
            3,
            &mut decode_probe,
        )
        .unwrap();
        assert_eq!(decoded, source);
        assert_eq!(decode_probe.log, expected_log);
    }

    #[test]
    fn explicit_arm_identity_is_bound_to_the_tape() {
        let table = LossTable::generate();
        let source = b"{\"a\":1}\n";
        let (tape, ledger) = encode_chassis_item(
            source,
            &table,
            chassis_contexts(0, &[]).unwrap(),
            7,
            3,
            &mut M1ValueCoder,
        )
        .unwrap();
        assert_eq!(
            decode_chassis_item(
                &tape,
                ledger,
                &table,
                chassis_contexts(0, &[]).unwrap(),
                8,
                3,
                &mut M1ValueCoder,
            ),
            Err(ChassisError::TapeIdentityMismatch)
        );
        assert_eq!(
            decode_chassis_item(
                &tape,
                ledger,
                &table,
                chassis_contexts(0, &[]).unwrap(),
                7,
                4,
                &mut M1ValueCoder,
            ),
            Err(ChassisError::TapeIdentityMismatch)
        );
        assert_eq!(
            decode_chassis_item(
                &tape,
                ledger,
                &table,
                chassis_contexts(0, &[]).unwrap(),
                7,
                3,
                &mut M1ValueCoder,
            )
            .unwrap(),
            source
        );
    }

    #[test]
    fn m1_entry_points_match_the_generic_chassis_exactly() {
        let table = LossTable::generate();
        let source = b"{\"a\":1,\"b\":\"x\"}\n{\"a\":2,\"b\":\"y\"}\n{bad}\n";
        let (m1_tape, m1_ledger) = encode_m1_item(source, &table, 5).unwrap();
        let (chassis_tape, chassis_ledger) = encode_chassis_item(
            source,
            &table,
            chassis_contexts(0, &[]).unwrap(),
            M1_ARM_ID,
            5,
            &mut M1ValueCoder,
        )
        .unwrap();
        assert_eq!(chassis_tape.to_bytes(), m1_tape.to_bytes());
        assert_eq!(chassis_ledger, m1_ledger);
    }
}
