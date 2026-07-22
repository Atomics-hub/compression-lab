//! Reversible, charged event primitives for the synthetic-only S0 harness.
//!
//! Decoding decisions are driven only by modeled bits and literal bytes. Tape
//! header lengths are integrity bounds; exhaustion and `is_finished` are
//! fail-closed checks, never grammar signals.

use super::{Ledger, LossTable, Probability, Tape, TapeError, TapeReader, TapeWriter};
use std::error::Error;
use std::fmt::{Display, Formatter};

pub const EVENT_LAYER_VERSION: u8 = 1;
pub const EVENT_LAYER_ID: &str = "s0-event-layer-v1";
pub const RATE_SHIFT: u32 = 5;
pub const MAX_LITERAL_RUN: usize = 1 << 20;

const MIN_ALPHABET: u32 = 2;
const MAX_ALPHABET: u32 = 65_536;
const LENGTH_CLASS_ALPHABET: u32 = 21;
const LENGTH_MANTISSA_CONTEXTS: usize = 210;
const _: () = assert!(LENGTH_CLASS_ALPHABET as usize == MAX_LITERAL_RUN.ilog2() as usize + 1);
const _: () = assert!(
    LENGTH_MANTISSA_CONTEXTS
        == (LENGTH_CLASS_ALPHABET as usize * (LENGTH_CLASS_ALPHABET as usize - 1)) / 2
);

#[derive(Clone, Debug)]
struct BitTree {
    alphabet: u32,
    width: u32,
    probabilities: Box<[Probability]>,
}

impl BitTree {
    fn new(alphabet: u32) -> Result<Self, EventError> {
        if !(MIN_ALPHABET..=MAX_ALPHABET).contains(&alphabet) {
            return Err(EventError::AlphabetOutOfRange);
        }
        let width = u32::BITS - (alphabet - 1).leading_zeros();
        let nodes = (1_usize << width) - 1;
        Ok(Self {
            alphabet,
            width,
            probabilities: vec![Probability::default(); nodes].into_boxed_slice(),
        })
    }

    fn encode(
        &mut self,
        symbol: u32,
        table: &LossTable,
        ledger: &mut Ledger,
        writer: &mut TapeWriter,
    ) -> Result<(), EventError> {
        if symbol >= self.alphabet {
            return Err(EventError::SymbolOutOfRange);
        }
        let mut node = 0_usize;
        for shift in (0..self.width).rev() {
            let bit = symbol & (1 << shift) != 0;
            encode_modeled_bit(&mut self.probabilities[node], bit, table, ledger, writer)?;
            node = node * 2 + 1 + usize::from(bit);
        }
        Ok(())
    }

    fn decode(
        &mut self,
        table: &LossTable,
        ledger: &mut Ledger,
        reader: &mut TapeReader<'_>,
    ) -> Result<u32, EventError> {
        let mut symbol = 0_u32;
        let mut node = 0_usize;
        for _ in 0..self.width {
            let bit = decode_modeled_bit(&mut self.probabilities[node], table, ledger, reader)?;
            symbol = (symbol << 1) | u32::from(bit);
            node = node * 2 + 1 + usize::from(bit);
        }
        if symbol >= self.alphabet {
            return Err(EventError::ForbiddenSymbol);
        }
        Ok(symbol)
    }
}

#[derive(Clone, Debug)]
pub struct ContextStore {
    bits: Box<[Probability]>,
    trees: Box<[BitTree]>,
    length_class: BitTree,
    length_mantissas: Box<[Probability; LENGTH_MANTISSA_CONTEXTS]>,
}

impl ContextStore {
    #[must_use]
    pub fn event_layer_identity() -> (&'static str, u8) {
        (EVENT_LAYER_ID, EVENT_LAYER_VERSION)
    }

    pub fn new(binary_contexts: usize, alphabets: &[u32]) -> Result<Self, EventError> {
        let mut trees = Vec::with_capacity(alphabets.len());
        for &alphabet in alphabets {
            trees.push(BitTree::new(alphabet)?);
        }
        let length_mantissas = vec![Probability::default(); LENGTH_MANTISSA_CONTEXTS]
            .into_boxed_slice()
            .try_into()
            .unwrap_or_else(|_| unreachable!("literal context count is constant"));
        Ok(Self {
            bits: vec![Probability::default(); binary_contexts].into_boxed_slice(),
            trees: trees.into_boxed_slice(),
            length_class: BitTree::new(LENGTH_CLASS_ALPHABET)?,
            length_mantissas,
        })
    }

    #[must_use]
    /// Logical probability-table bytes, excluding fixed metadata and allocator overhead.
    pub fn modeled_state_bytes(&self) -> usize {
        let tree_nodes = self
            .trees
            .iter()
            .map(|tree| tree.probabilities.len())
            .sum::<usize>()
            + self.length_class.probabilities.len();
        (self.bits.len() + tree_nodes + LENGTH_MANTISSA_CONTEXTS)
            * std::mem::size_of::<Probability>()
    }
}

pub struct EventEncoder<'a> {
    table: &'a LossTable,
    contexts: ContextStore,
    ledger: Ledger,
    writer: TapeWriter,
}

impl<'a> EventEncoder<'a> {
    #[must_use]
    pub fn new(table: &'a LossTable, contexts: ContextStore, arm_id: u8, item_index: u8) -> Self {
        Self {
            table,
            contexts,
            ledger: Ledger::default(),
            writer: TapeWriter::new(arm_id, item_index),
        }
    }

    pub fn bit(&mut self, context: usize, bit: bool) -> Result<(), EventError> {
        let probability = self
            .contexts
            .bits
            .get_mut(context)
            .ok_or(EventError::ContextOutOfRange)?;
        encode_modeled_bit(
            probability,
            bit,
            self.table,
            &mut self.ledger,
            &mut self.writer,
        )
    }

    pub fn symbol(&mut self, context: usize, symbol: u32) -> Result<(), EventError> {
        let tree = self
            .contexts
            .trees
            .get_mut(context)
            .ok_or(EventError::ContextOutOfRange)?;
        tree.encode(symbol, self.table, &mut self.ledger, &mut self.writer)
    }

    pub fn mixed_symbol(
        &mut self,
        first_context: usize,
        second_context: usize,
        symbol: u32,
    ) -> Result<(), EventError> {
        let (first, second) =
            two_trees_mut(&mut self.contexts.trees, first_context, second_context)?;
        encode_mixed_symbol(
            first,
            second,
            symbol,
            self.table,
            &mut self.ledger,
            &mut self.writer,
        )
    }

    pub fn length(
        &mut self,
        class_tree_context: usize,
        mantissa_context_base: usize,
        length: usize,
        maximum: usize,
    ) -> Result<(), EventError> {
        // The caller owns the frozen context layout: this tree and contiguous
        // mantissa range must not overlap unrelated grammar contexts.
        let ContextStore { bits, trees, .. } = &mut self.contexts;
        let tree = trees
            .get_mut(class_tree_context)
            .ok_or(EventError::ContextOutOfRange)?;
        let mantissas = bits
            .get_mut(mantissa_context_base..)
            .ok_or(EventError::ContextOutOfRange)?;
        encode_length(
            tree,
            mantissas,
            length,
            maximum,
            self.table,
            &mut self.ledger,
            &mut self.writer,
        )
    }

    pub fn literal(&mut self, bytes: &[u8]) -> Result<(), EventError> {
        // Every encoder error is terminal for the item. Callers must discard
        // this instance rather than trying to reuse partially charged state.
        if bytes.is_empty() {
            return Err(EventError::LiteralRunEmpty);
        }
        if bytes.len() > MAX_LITERAL_RUN {
            return Err(EventError::LiteralRunTooLong);
        }
        encode_length(
            &mut self.contexts.length_class,
            self.contexts.length_mantissas.as_mut_slice(),
            bytes.len(),
            MAX_LITERAL_RUN,
            self.table,
            &mut self.ledger,
            &mut self.writer,
        )?;
        self.writer.push_literals(bytes)?;
        self.ledger
            .add_raw_literals(bytes.len() as u64)
            .ok_or(EventError::LedgerOverflow)
    }

    pub fn record(&mut self) -> Result<(), EventError> {
        self.ledger.add_record().ok_or(EventError::LedgerOverflow)
    }

    #[must_use]
    pub fn ledger(&self) -> Ledger {
        self.ledger
    }

    #[must_use]
    pub fn finish(self) -> (Tape, Ledger) {
        (self.writer.finish(), self.ledger)
    }
}

pub struct EventDecoder<'a> {
    table: &'a LossTable,
    contexts: ContextStore,
    ledger: Ledger,
    reader: TapeReader<'a>,
}

impl<'a> EventDecoder<'a> {
    #[must_use]
    pub fn new(table: &'a LossTable, contexts: ContextStore, tape: &'a Tape) -> Self {
        Self {
            table,
            contexts,
            ledger: Ledger::default(),
            reader: tape.reader(),
        }
    }

    pub fn bit(&mut self, context: usize) -> Result<bool, EventError> {
        let probability = self
            .contexts
            .bits
            .get_mut(context)
            .ok_or(EventError::ContextOutOfRange)?;
        decode_modeled_bit(probability, self.table, &mut self.ledger, &mut self.reader)
    }

    pub fn symbol(&mut self, context: usize) -> Result<u32, EventError> {
        let tree = self
            .contexts
            .trees
            .get_mut(context)
            .ok_or(EventError::ContextOutOfRange)?;
        tree.decode(self.table, &mut self.ledger, &mut self.reader)
    }

    pub fn mixed_symbol(
        &mut self,
        first_context: usize,
        second_context: usize,
    ) -> Result<u32, EventError> {
        let (first, second) =
            two_trees_mut(&mut self.contexts.trees, first_context, second_context)?;
        decode_mixed_symbol(
            first,
            second,
            self.table,
            &mut self.ledger,
            &mut self.reader,
        )
    }

    pub fn length(
        &mut self,
        class_tree_context: usize,
        mantissa_context_base: usize,
        maximum: usize,
    ) -> Result<usize, EventError> {
        // The caller owns the frozen context layout: this tree and contiguous
        // mantissa range must match the encoder's assignment exactly.
        let ContextStore { bits, trees, .. } = &mut self.contexts;
        let tree = trees
            .get_mut(class_tree_context)
            .ok_or(EventError::ContextOutOfRange)?;
        let mantissas = bits
            .get_mut(mantissa_context_base..)
            .ok_or(EventError::ContextOutOfRange)?;
        decode_length(
            tree,
            mantissas,
            maximum,
            self.table,
            &mut self.ledger,
            &mut self.reader,
        )
    }

    pub fn literal(&mut self) -> Result<Vec<u8>, EventError> {
        let length = decode_length(
            &mut self.contexts.length_class,
            self.contexts.length_mantissas.as_mut_slice(),
            MAX_LITERAL_RUN,
            self.table,
            &mut self.ledger,
            &mut self.reader,
        )
        .map_err(|error| match error {
            EventError::LengthOutOfRange => EventError::LiteralRunTooLong,
            other => other,
        })?;
        let bytes = self.reader.read_literals(length)?.to_vec();
        self.ledger
            .add_raw_literals(length as u64)
            .ok_or(EventError::LedgerOverflow)?;
        Ok(bytes)
    }

    pub fn record(&mut self) -> Result<(), EventError> {
        self.ledger.add_record().ok_or(EventError::LedgerOverflow)
    }

    #[must_use]
    pub fn ledger(&self) -> Ledger {
        self.ledger
    }

    pub fn finish(self, encoder_ledger: Ledger) -> Result<Ledger, EventError> {
        if !self.reader.is_finished() {
            return Err(EventError::TrailingChargedData);
        }
        if self.ledger != encoder_ledger {
            return Err(EventError::LedgerDivergence {
                encoder: encoder_ledger,
                decoder: self.ledger,
            });
        }
        Ok(self.ledger)
    }
}

fn encode_modeled_bit(
    probability: &mut Probability,
    bit: bool,
    table: &LossTable,
    ledger: &mut Ledger,
    writer: &mut TapeWriter,
) -> Result<(), EventError> {
    let loss = table
        .get(probability.probability_of(bit))
        .ok_or(EventError::InvalidProbability)?;
    ledger
        .add_modeled_event(loss)
        .ok_or(EventError::LedgerOverflow)?;
    writer.push_bit(bit)?;
    probability.update(bit, RATE_SHIFT);
    Ok(())
}

fn decode_modeled_bit(
    probability: &mut Probability,
    table: &LossTable,
    ledger: &mut Ledger,
    reader: &mut TapeReader<'_>,
) -> Result<bool, EventError> {
    let bit = reader.read_bit()?;
    let loss = table
        .get(probability.probability_of(bit))
        .ok_or(EventError::InvalidProbability)?;
    ledger
        .add_modeled_event(loss)
        .ok_or(EventError::LedgerOverflow)?;
    probability.update(bit, RATE_SHIFT);
    Ok(bit)
}

fn encode_mixed_symbol(
    first: &mut BitTree,
    second: &mut BitTree,
    symbol: u32,
    table: &LossTable,
    ledger: &mut Ledger,
    writer: &mut TapeWriter,
) -> Result<(), EventError> {
    validate_mixed_trees(first, second, symbol)?;
    let mut node = 0_usize;
    for shift in (0..first.width).rev() {
        let bit = symbol & (1 << shift) != 0;
        charge_mixed_bit(
            &mut first.probabilities[node],
            &mut second.probabilities[node],
            bit,
            table,
            ledger,
            |output_bit| writer.push_bit(output_bit).map_err(EventError::from),
        )?;
        node = node * 2 + 1 + usize::from(bit);
    }
    Ok(())
}

fn decode_mixed_symbol(
    first: &mut BitTree,
    second: &mut BitTree,
    table: &LossTable,
    ledger: &mut Ledger,
    reader: &mut TapeReader<'_>,
) -> Result<u32, EventError> {
    validate_mixed_trees(first, second, 0)?;
    let mut symbol = 0_u32;
    let mut node = 0_usize;
    for _ in 0..first.width {
        let bit = reader.read_bit()?;
        charge_mixed_bit(
            &mut first.probabilities[node],
            &mut second.probabilities[node],
            bit,
            table,
            ledger,
            |_| Ok(()),
        )?;
        symbol = (symbol << 1) | u32::from(bit);
        node = node * 2 + 1 + usize::from(bit);
    }
    if symbol >= first.alphabet {
        return Err(EventError::ForbiddenSymbol);
    }
    Ok(symbol)
}

fn charge_mixed_bit(
    first: &mut Probability,
    second: &mut Probability,
    bit: bool,
    table: &LossTable,
    ledger: &mut Ledger,
    write: impl FnOnce(bool) -> Result<(), EventError>,
) -> Result<(), EventError> {
    // Freeze the mix as floor((p1_a + p1_b) / 2), then derive p0 as its
    // complement. This rounds odd sums one unit toward zero for p1.
    let mixed_one =
        (u32::from(first.probability_of_one()) + u32::from(second.probability_of_one())) / 2;
    let observed = if bit { mixed_one } else { 65_536 - mixed_one };
    let loss = table.get(observed).ok_or(EventError::InvalidProbability)?;
    ledger
        .add_modeled_event(loss)
        .ok_or(EventError::LedgerOverflow)?;
    write(bit)?;
    first.update(bit, RATE_SHIFT);
    second.update(bit, RATE_SHIFT);
    Ok(())
}

fn validate_mixed_trees(first: &BitTree, second: &BitTree, symbol: u32) -> Result<(), EventError> {
    if first.alphabet != second.alphabet || first.width != second.width {
        return Err(EventError::AlphabetMismatch);
    }
    if symbol >= first.alphabet {
        return Err(EventError::SymbolOutOfRange);
    }
    Ok(())
}

fn two_trees_mut(
    trees: &mut [BitTree],
    first: usize,
    second: usize,
) -> Result<(&mut BitTree, &mut BitTree), EventError> {
    if first == second {
        return Err(EventError::ContextOverlap);
    }
    if first >= trees.len() || second >= trees.len() {
        return Err(EventError::ContextOutOfRange);
    }
    if first < second {
        let (left, right) = trees.split_at_mut(second);
        Ok((
            left.get_mut(first).ok_or(EventError::ContextOutOfRange)?,
            right.get_mut(0).ok_or(EventError::ContextOutOfRange)?,
        ))
    } else {
        let (left, right) = trees.split_at_mut(first);
        Ok((
            right.get_mut(0).ok_or(EventError::ContextOutOfRange)?,
            left.get_mut(second).ok_or(EventError::ContextOutOfRange)?,
        ))
    }
}

#[allow(clippy::too_many_arguments)]
fn encode_length(
    class_tree: &mut BitTree,
    mantissas: &mut [Probability],
    length: usize,
    maximum: usize,
    table: &LossTable,
    ledger: &mut Ledger,
    writer: &mut TapeWriter,
) -> Result<(), EventError> {
    if length == 0 || length > maximum || maximum == 0 {
        return Err(EventError::LengthOutOfRange);
    }
    let length = u32::try_from(length).map_err(|_| EventError::LengthOutOfRange)?;
    let class = u32::BITS - length.leading_zeros();
    let offset = mantissa_offset(class);
    let required = offset + (class - 1) as usize;
    if mantissas.len() < required {
        return Err(EventError::ContextOutOfRange);
    }
    // Bounds and context capacity are intentionally checked before the first
    // charged event so these configuration errors leave the encoder untouched.
    class_tree.encode(class - 1, table, ledger, writer)?;
    for position in (0..class - 1).rev() {
        let probability = mantissas
            .get_mut(offset + position as usize)
            .ok_or(EventError::ContextOutOfRange)?;
        let bit = length & (1 << position) != 0;
        encode_modeled_bit(probability, bit, table, ledger, writer)?;
    }
    Ok(())
}

fn decode_length(
    class_tree: &mut BitTree,
    mantissas: &mut [Probability],
    maximum: usize,
    table: &LossTable,
    ledger: &mut Ledger,
    reader: &mut TapeReader<'_>,
) -> Result<usize, EventError> {
    if maximum == 0 {
        return Err(EventError::LengthOutOfRange);
    }
    let class = class_tree.decode(table, ledger, reader)? + 1;
    let offset = mantissa_offset(class);
    let mut length = 1_u32
        .checked_shl(class - 1)
        .ok_or(EventError::LengthOutOfRange)?;
    for position in (0..class - 1).rev() {
        let probability = mantissas
            .get_mut(offset + position as usize)
            .ok_or(EventError::ContextOutOfRange)?;
        if decode_modeled_bit(probability, table, ledger, reader)? {
            length |= 1 << position;
        }
    }
    let length = usize::try_from(length).map_err(|_| EventError::LengthOutOfRange)?;
    if length > maximum {
        return Err(EventError::LengthOutOfRange);
    }
    Ok(length)
}

fn mantissa_offset(class: u32) -> usize {
    let lower_classes = usize::try_from(class - 1).expect("literal class is bounded");
    lower_classes * lower_classes.saturating_sub(1) / 2
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum EventError {
    AlphabetOutOfRange,
    ContextOutOfRange,
    ContextOverlap,
    AlphabetMismatch,
    SymbolOutOfRange,
    ForbiddenSymbol,
    LiteralRunEmpty,
    LiteralRunTooLong,
    LengthOutOfRange,
    InvalidProbability,
    LedgerOverflow,
    LedgerDivergence { encoder: Ledger, decoder: Ledger },
    TrailingChargedData,
    Tape(TapeError),
}

impl From<TapeError> for EventError {
    fn from(error: TapeError) -> Self {
        Self::Tape(error)
    }
}

impl Display for EventError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "S0 event error: {self:?}")
    }
}

impl Error for EventError {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mixed_script_round_trips_with_an_independent_ledger() {
        let table = LossTable::generate();
        let contexts = ContextStore::new(2, &[3, 17, 65_536]).unwrap();
        let mut encoder = EventEncoder::new(&table, contexts, 6, 2);
        encoder.record().unwrap();
        encoder.bit(0, true).unwrap();
        encoder.bit(1, false).unwrap();
        encoder.symbol(0, 2).unwrap();
        encoder.symbol(1, 16).unwrap();
        encoder.symbol(2, 65_535).unwrap();
        encoder.literal(b"exact bytes\n").unwrap();
        let (tape, expected) = encoder.finish();

        let bytes = tape.to_bytes();
        let tape = Tape::from_bytes(&bytes).unwrap();
        let contexts = ContextStore::new(2, &[3, 17, 65_536]).unwrap();
        let mut decoder = EventDecoder::new(&table, contexts, &tape);
        decoder.record().unwrap();
        assert!(decoder.bit(0).unwrap());
        assert!(!decoder.bit(1).unwrap());
        assert_eq!(decoder.symbol(0).unwrap(), 2);
        assert_eq!(decoder.symbol(1).unwrap(), 16);
        assert_eq!(decoder.symbol(2).unwrap(), 65_535);
        assert_eq!(decoder.literal().unwrap(), b"exact bytes\n");
        assert_eq!(decoder.finish(expected).unwrap(), expected);
    }

    #[test]
    fn symbols_use_fixed_width_and_forbidden_codes_fail_closed() {
        let table = LossTable::generate();
        for alphabet in 2..=64_u32 {
            for symbol in 0..alphabet {
                let mut encoder =
                    EventEncoder::new(&table, ContextStore::new(0, &[alphabet]).unwrap(), 0, 0);
                encoder.symbol(0, symbol).unwrap();
                let (tape, ledger) = encoder.finish();
                assert_eq!(
                    ledger.modeled_binary_events,
                    u64::from(u32::BITS - (alphabet - 1).leading_zeros())
                );
                let mut decoder =
                    EventDecoder::new(&table, ContextStore::new(0, &[alphabet]).unwrap(), &tape);
                assert_eq!(decoder.symbol(0).unwrap(), symbol);
                decoder.finish(ledger).unwrap();
            }
        }

        let mut writer = TapeWriter::new(0, 0);
        writer.push_bit(true).unwrap();
        writer.push_bit(true).unwrap();
        let tape = writer.finish();
        let mut decoder = EventDecoder::new(&table, ContextStore::new(0, &[3]).unwrap(), &tape);
        assert_eq!(decoder.symbol(0), Err(EventError::ForbiddenSymbol));
    }

    #[test]
    fn mixed_symbols_charge_one_event_per_bit_and_update_both_models() {
        let table = LossTable::generate();
        let mut encoder = EventEncoder::new(&table, ContextStore::new(0, &[4, 4]).unwrap(), 0, 0);
        for _ in 0..10 {
            encoder.symbol(0, 3).unwrap();
            encoder.symbol(1, 0).unwrap();
        }
        let before = encoder.ledger().modeled_binary_events;
        encoder.mixed_symbol(0, 1, 2).unwrap();
        assert_eq!(encoder.ledger().modeled_binary_events - before, 2);
        let (tape, ledger) = encoder.finish();

        let mut decoder = EventDecoder::new(&table, ContextStore::new(0, &[4, 4]).unwrap(), &tape);
        for _ in 0..10 {
            assert_eq!(decoder.symbol(0).unwrap(), 3);
            assert_eq!(decoder.symbol(1).unwrap(), 0);
        }
        assert_eq!(decoder.mixed_symbol(0, 1).unwrap(), 2);
        decoder.finish(ledger).unwrap();
    }

    #[test]
    fn mixed_symbols_reject_overlapping_or_incompatible_contexts_precharge() {
        let table = LossTable::generate();
        let mut encoder = EventEncoder::new(&table, ContextStore::new(0, &[3, 4]).unwrap(), 0, 0);
        assert_eq!(
            encoder.mixed_symbol(0, 0, 1),
            Err(EventError::ContextOverlap)
        );
        assert_eq!(
            encoder.mixed_symbol(0, 1, 1),
            Err(EventError::AlphabetMismatch)
        );
        assert_eq!(
            encoder.mixed_symbol(0, 2, 1),
            Err(EventError::ContextOutOfRange)
        );
        assert_eq!(
            encoder.mixed_symbol(3, 0, 1),
            Err(EventError::ContextOutOfRange)
        );
        assert_eq!(encoder.ledger(), Ledger::default());
    }

    #[test]
    fn literal_boundaries_are_exactly_charged_and_round_trip() {
        let table = LossTable::generate();
        for length in [1, 2, 255, 256, MAX_LITERAL_RUN - 1, MAX_LITERAL_RUN] {
            let payload = vec![(length & 0xff) as u8; length];
            let mut encoder = EventEncoder::new(&table, ContextStore::new(0, &[]).unwrap(), 0, 0);
            encoder.literal(&payload).unwrap();
            let (tape, ledger) = encoder.finish();
            let class = usize::BITS - length.leading_zeros();
            assert_eq!(ledger.raw_literal_bytes, length as u64);
            assert_eq!(ledger.modeled_binary_events, 4 + class as u64);
            let mut decoder = EventDecoder::new(&table, ContextStore::new(0, &[]).unwrap(), &tape);
            assert_eq!(decoder.literal().unwrap(), payload);
            decoder.finish(ledger).unwrap();
        }
    }

    #[test]
    fn shared_modeled_lengths_round_trip_and_enforce_bounds() {
        let table = LossTable::generate();
        let values = [1, 2, 255, 256, MAX_LITERAL_RUN];
        let mut encoder = EventEncoder::new(
            &table,
            ContextStore::new(LENGTH_MANTISSA_CONTEXTS, &[LENGTH_CLASS_ALPHABET]).unwrap(),
            0,
            0,
        );
        for value in values {
            encoder.length(0, 0, value, MAX_LITERAL_RUN).unwrap();
        }
        let (tape, ledger) = encoder.finish();
        let mut decoder = EventDecoder::new(
            &table,
            ContextStore::new(LENGTH_MANTISSA_CONTEXTS, &[LENGTH_CLASS_ALPHABET]).unwrap(),
            &tape,
        );
        for value in values {
            assert_eq!(decoder.length(0, 0, MAX_LITERAL_RUN).unwrap(), value);
        }
        decoder.finish(ledger).unwrap();

        let mut encoder = EventEncoder::new(
            &table,
            ContextStore::new(LENGTH_MANTISSA_CONTEXTS, &[LENGTH_CLASS_ALPHABET]).unwrap(),
            0,
            0,
        );
        assert_eq!(
            encoder.length(0, 0, 0, MAX_LITERAL_RUN),
            Err(EventError::LengthOutOfRange)
        );
        assert_eq!(
            encoder.length(0, 0, 9, 8),
            Err(EventError::LengthOutOfRange)
        );

        encoder.length(0, 0, 9, 16).unwrap();
        let (tape, _) = encoder.finish();
        let mut decoder = EventDecoder::new(
            &table,
            ContextStore::new(LENGTH_MANTISSA_CONTEXTS, &[LENGTH_CLASS_ALPHABET]).unwrap(),
            &tape,
        );
        assert_eq!(decoder.length(0, 0, 8), Err(EventError::LengthOutOfRange));
    }

    #[test]
    fn shared_modeled_lengths_fail_closed_on_bad_contexts_and_hostile_classes() {
        let table = LossTable::generate();
        let mut encoder = EventEncoder::new(&table, ContextStore::new(0, &[]).unwrap(), 0, 0);
        assert_eq!(
            encoder.length(0, 0, 1, MAX_LITERAL_RUN),
            Err(EventError::ContextOutOfRange)
        );

        let mut encoder = EventEncoder::new(&table, ContextStore::new(0, &[21]).unwrap(), 0, 0);
        assert_eq!(
            encoder.length(0, 0, 2, MAX_LITERAL_RUN),
            Err(EventError::ContextOutOfRange)
        );
        assert_eq!(encoder.ledger(), Ledger::default());

        let mut encoder = EventEncoder::new(
            &table,
            ContextStore::new(LENGTH_MANTISSA_CONTEXTS, &[2]).unwrap(),
            0,
            0,
        );
        assert_eq!(
            encoder.length(0, 0, 4, MAX_LITERAL_RUN),
            Err(EventError::SymbolOutOfRange)
        );
        assert_eq!(encoder.ledger(), Ledger::default());

        // Symbol 32 in a 64-way class tree means class 33. The checked leading
        // shift rejects it before any mantissa access or unchecked shift.
        let mut writer = TapeWriter::new(0, 0);
        for bit in [true, false, false, false, false, false] {
            writer.push_bit(bit).unwrap();
        }
        let tape = writer.finish();
        let mut decoder = EventDecoder::new(&table, ContextStore::new(0, &[64]).unwrap(), &tape);
        assert_eq!(
            decoder.length(0, 0, usize::MAX),
            Err(EventError::LengthOutOfRange)
        );
    }

    #[test]
    fn invalid_inputs_and_trailing_charged_data_fail_closed() {
        let table = LossTable::generate();
        assert!(matches!(
            ContextStore::new(0, &[1]),
            Err(EventError::AlphabetOutOfRange)
        ));
        let mut encoder = EventEncoder::new(&table, ContextStore::new(1, &[3]).unwrap(), 0, 0);
        assert_eq!(encoder.bit(1, true), Err(EventError::ContextOutOfRange));
        assert_eq!(encoder.symbol(0, 3), Err(EventError::SymbolOutOfRange));
        assert_eq!(encoder.literal(b""), Err(EventError::LiteralRunEmpty));
        assert_eq!(
            encoder.literal(&vec![0; MAX_LITERAL_RUN + 1]),
            Err(EventError::LiteralRunTooLong)
        );

        let mut writer = TapeWriter::new(0, 0);
        writer.push_bit(false).unwrap();
        let tape = writer.finish();
        let decoder = EventDecoder::new(&table, ContextStore::new(0, &[]).unwrap(), &tape);
        assert_eq!(
            decoder.finish(Ledger::default()),
            Err(EventError::TrailingChargedData)
        );
    }

    #[test]
    fn hostile_literal_lengths_and_short_literal_lanes_fail_closed() {
        let table = LossTable::generate();

        // Length class 21 is symbol 20 = 10100, followed by a 20-bit
        // mantissa. Setting only bit zero reconstructs 2^20 + 1.
        let mut writer = TapeWriter::new(0, 0);
        for bit in [true, false, true, false, false] {
            writer.push_bit(bit).unwrap();
        }
        for _ in 0..19 {
            writer.push_bit(false).unwrap();
        }
        writer.push_bit(true).unwrap();
        let tape = writer.finish();
        let mut decoder = EventDecoder::new(&table, ContextStore::new(0, &[]).unwrap(), &tape);
        assert_eq!(decoder.literal(), Err(EventError::LiteralRunTooLong));

        // Length one is class symbol zero = 00000 and needs one literal byte.
        let mut writer = TapeWriter::new(0, 0);
        for _ in 0..5 {
            writer.push_bit(false).unwrap();
        }
        let tape = writer.finish();
        let mut decoder = EventDecoder::new(&table, ContextStore::new(0, &[]).unwrap(), &tape);
        assert_eq!(
            decoder.literal(),
            Err(EventError::Tape(TapeError::ExhaustedLiterals))
        );
    }

    #[test]
    fn finalization_rejects_an_independently_divergent_ledger() {
        let table = LossTable::generate();
        let mut encoder = EventEncoder::new(&table, ContextStore::new(1, &[]).unwrap(), 0, 0);
        encoder.bit(0, true).unwrap();
        encoder.bit(0, true).unwrap();
        let (tape, expected) = encoder.finish();
        let mut decoder = EventDecoder::new(&table, ContextStore::new(1, &[]).unwrap(), &tape);
        assert!(decoder.bit(0).unwrap());
        assert!(decoder.bit(0).unwrap());
        let mut wrong = expected;
        wrong.modeled_loss_q24 += 1;
        assert!(matches!(
            decoder.finish(wrong),
            Err(EventError::LedgerDivergence { .. })
        ));
    }

    #[test]
    fn fresh_item_contexts_are_deterministic_and_fully_reset() {
        fn encode(table: &LossTable) -> (Vec<u8>, Ledger) {
            let mut encoder = EventEncoder::new(table, ContextStore::new(1, &[5]).unwrap(), 3, 1);
            for value in 0..100_u32 {
                encoder.bit(0, value % 3 == 0).unwrap();
                encoder.symbol(0, value % 5).unwrap();
            }
            let (tape, ledger) = encoder.finish();
            (tape.to_bytes(), ledger)
        }
        let table = LossTable::generate();
        assert_eq!(encode(&table), encode(&table));
    }

    #[test]
    fn state_size_is_exact_and_independent_of_observations() {
        let table = LossTable::generate();
        let mut store = ContextStore::new(7, &[3, 256]).unwrap();
        // 7 flags + (3-node + 255-node) trees + 31 length-class nodes +
        // 210 literal-mantissa contexts, each represented by one u16.
        let expected = (7 + 3 + 255 + 31 + 210) * 2;
        assert_eq!(store.modeled_state_bytes(), expected);
        let mut ledger = Ledger::default();
        let mut writer = TapeWriter::new(0, 0);
        for value in 0..1_000_u32 {
            encode_modeled_bit(
                &mut store.bits[(value as usize) % 7],
                value % 3 == 0,
                &table,
                &mut ledger,
                &mut writer,
            )
            .unwrap();
            store.trees[0]
                .encode(value % 3, &table, &mut ledger, &mut writer)
                .unwrap();
            store.trees[1]
                .encode(value % 256, &table, &mut ledger, &mut writer)
                .unwrap();
        }
        assert_eq!(store.modeled_state_bytes(), expected);
    }
}
