//! C3: bounded live adaptation for non-stationary JSON/log streams.
//!
//! Development-only Cycle 2 arm. C3 preserves H1's byte grammar and context
//! set, but replaces lifetime counters with confidence-sensitive exponential
//! predictors and adds a neutral, three-stage residual recalibration chain.
//! It is deliberately isolated from H1 so the published Cycle 1 floor remains
//! byte-for-byte frozen. All state and arithmetic are fixed-size and integer.

use crate::s0::{
    Ledger, LossTable, M5Mixer, Probability, Tape, TapeError, TapeReader, TapeWriter,
    MAX_PROBABILITY, MIN_PROBABILITY,
};
use std::error::Error;
use std::fmt::{Display, Formatter};

use super::mixer::{MoonMixer, MOON_MIXER_WEIGHT_BYTES};

pub const C3_ARM_ID: u8 = 104;
pub const C3_CONTEXT_COUNT: usize = 8;
pub const C3_BYTE_ORDERS: [usize; 6] = [1, 2, 3, 4, 6, 8];
pub const C3_CONTEXT_CELL_BITS: u32 = 24;
pub const C3_CONTEXT_CELLS: usize = 1 << C3_CONTEXT_CELL_BITS;
pub const C3_CELL_BYTES: usize = 6;
pub const C3_CONTEXT_TABLE_BYTES: usize = C3_CONTEXT_CELLS * C3_CELL_BYTES;
pub const C3_APM_STAGES: usize = 3;
pub const C3_APM_BUCKET_BITS: u32 = 20;
pub const C3_APM_BUCKETS: usize = 1 << C3_APM_BUCKET_BITS;
pub const C3_APM_STATE_BYTES: usize = C3_APM_STAGES * C3_APM_BUCKETS * 2;

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct C3QuarterSnapshot {
    pub source_bytes: u64,
    pub modeled_binary_events: u64,
    pub modeled_loss_q24: u64,
}

const PROBE_DEPTH: usize = 4;
const NEWCOMER_PRIORITY: u8 = 1;
const CONTINUATION_RATE_SHIFT: u32 = 5;
const CONTINUATION_EVENT_ID: u64 = u64::MAX;
const APM_CORRECTION_LIMIT: i32 = 16_384;
const APM_LEARN_SHIFT: u32 = 7;

const TAG_ORDER: u8 = 0x01;
const TAG_SPARSE: u8 = 0xa5;
const TAG_WORD: u8 = 0x5a;
const TAG_WORD_ACCUM: u8 = 0x33;
const FNV_OFFSET: u64 = 14_695_981_039_346_656_037;
const FNV_PRIME: u64 = 1_099_511_628_211;

const _: () = assert!(C3_CONTEXT_TABLE_BYTES == 96 * 1024 * 1024);
const _: () = assert!(C3_APM_STATE_BYTES == 6 * 1024 * 1024);

fn fnv1a64(seed: u64, bytes: &[u8]) -> u64 {
    bytes.iter().fold(seed, |hash, byte| {
        (hash ^ u64::from(*byte)).wrapping_mul(FNV_PRIME)
    })
}

fn is_word_byte(byte: u8) -> bool {
    byte.is_ascii_alphanumeric() || byte == b'_'
}

fn observed_probability(probability_of_one: u16, bit: bool) -> u32 {
    if bit {
        u32::from(probability_of_one)
    } else {
        65_536 - u32::from(probability_of_one)
    }
}

/// Six-byte non-stationary cell. `probability` is an EWMA in Q16 and
/// `confidence` chooses a fast-cold/slow-warm learning rate. A strong surprise
/// halves confidence before learning, allowing regime changes to be tracked.
#[repr(C)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct C3Cell {
    probability: u16,
    confidence: u16,
    check: u8,
    priority: u8,
}

const _: () = assert!(std::mem::size_of::<C3Cell>() == C3_CELL_BYTES);

impl Default for C3Cell {
    fn default() -> Self {
        Self {
            probability: 1 << 15,
            confidence: 0,
            check: 0,
            priority: 0,
        }
    }
}

impl C3Cell {
    fn observe(&mut self, bit: bool) {
        let surprising = (bit && self.probability < 16_384) || (!bit && self.probability > 49_152);
        if surprising {
            self.confidence >>= 1;
        }
        let shift = match self.confidence {
            0..=3 => 2,
            4..=15 => 3,
            16..=63 => 4,
            64..=255 => 5,
            _ => 6,
        };
        let current = i32::from(self.probability);
        let target = if bit { 65_536 } else { 0 };
        self.probability = (current + ((target - current) >> shift))
            .clamp(i32::from(MIN_PROBABILITY), i32::from(MAX_PROBABILITY))
            as u16;
        self.confidence = self.confidence.saturating_add(1);
        self.priority = self.priority.saturating_add(1);
    }
}

struct C3ContextTable {
    cells: Box<[C3Cell]>,
    mask: usize,
}

impl C3ContextTable {
    fn new() -> Self {
        Self::with_cells(C3_CONTEXT_CELLS)
    }

    fn with_cells(cells: usize) -> Self {
        assert!(cells.is_power_of_two());
        Self {
            cells: vec![C3Cell::default(); cells].into_boxed_slice(),
            mask: cells - 1,
        }
    }

    fn resolve(&mut self, hash: u64) -> usize {
        let home = (hash as usize) & self.mask;
        let check = ((hash >> 40) as u8) | 1;
        let mut weakest = home;
        let mut weakest_priority = u8::MAX;
        for step in 0..PROBE_DEPTH {
            let index = (home + step) & self.mask;
            let cell = self.cells[index];
            if cell.check == 0 {
                self.claim(index, check);
                return index;
            }
            if cell.check == check {
                return index;
            }
            if cell.priority < NEWCOMER_PRIORITY {
                self.claim(index, check);
                return index;
            }
            if cell.priority < weakest_priority {
                weakest = index;
                weakest_priority = cell.priority;
            }
            self.cells[index].priority = cell.priority.saturating_sub(1);
        }
        self.claim(weakest, check);
        weakest
    }

    fn claim(&mut self, index: usize, check: u8) {
        self.cells[index] = C3Cell {
            check,
            priority: NEWCOMER_PRIORITY,
            ..C3Cell::default()
        };
    }

    fn observe(&mut self, index: usize, bit: bool) {
        self.cells[index].observe(bit);
    }
}

struct ApmScratch {
    indices: [usize; C3_APM_STAGES],
    predictions: [i32; C3_APM_STAGES],
}

/// Three neutral residual APM stages. Zero-initialized corrections leave the
/// incoming probability unchanged, unlike a fresh absolute-probability table.
struct C3Recalibrator {
    corrections: Box<[i16]>,
    scratch: Option<ApmScratch>,
}

impl C3Recalibrator {
    fn new() -> Self {
        Self {
            corrections: vec![0_i16; C3_APM_STAGES * C3_APM_BUCKETS].into_boxed_slice(),
            scratch: None,
        }
    }

    fn predict(&mut self, event_id: u64, base: u16, confidence: u16, run: u16) -> u16 {
        assert!(self.scratch.is_none(), "C3 APM prediction pairing violated");
        let features = [
            event_id,
            event_id ^ (u64::from(confidence.checked_ilog2().unwrap_or(0)) << 48),
            event_id.rotate_left(23) ^ (u64::from(run.min(255)) << 40),
        ];
        let mut current = i32::from(base);
        let mut indices = [0_usize; C3_APM_STAGES];
        let mut predictions = [0_i32; C3_APM_STAGES];
        for stage in 0..C3_APM_STAGES {
            let hash = fnv1a64(
                FNV_OFFSET ^ ((stage as u64 + 1) << 56),
                &features[stage].to_le_bytes(),
            );
            let index = stage * C3_APM_BUCKETS + (hash as usize & (C3_APM_BUCKETS - 1));
            current = (current + i32::from(self.corrections[index]))
                .clamp(i32::from(MIN_PROBABILITY), i32::from(MAX_PROBABILITY));
            indices[stage] = index;
            predictions[stage] = current;
        }
        self.scratch = Some(ApmScratch {
            indices,
            predictions,
        });
        current as u16
    }

    fn update(&mut self, bit: bool) {
        let scratch = self
            .scratch
            .take()
            .expect("C3 APM update without prediction");
        let target = if bit { 65_536 } else { 0 };
        for stage in 0..C3_APM_STAGES {
            let index = scratch.indices[stage];
            let delta = (target - scratch.predictions[stage]) >> APM_LEARN_SHIFT;
            self.corrections[index] = (i32::from(self.corrections[index]) + delta)
                .clamp(-APM_CORRECTION_LIMIT, APM_CORRECTION_LIMIT)
                as i16;
        }
    }
}

#[must_use]
pub fn c3_declared_state_bytes(table: &LossTable, sse_bucket_bits: u32) -> usize {
    let (mixer_bytes, sse_bytes) =
        M5Mixer::with_sse_bucket_bits(table, sse_bucket_bits).declared_state_bytes();
    C3_CONTEXT_TABLE_BYTES + MOON_MIXER_WEIGHT_BYTES + mixer_bytes + sse_bytes + C3_APM_STATE_BYTES
}

struct C3Model {
    contexts: C3ContextTable,
    moon: MoonMixer,
    mixer: Box<M5Mixer>,
    apm: C3Recalibrator,
    continuation: Probability,
    word: u64,
    last_byte: u8,
    last_bit: bool,
    bit_run: u16,
}

impl C3Model {
    fn new(table: &LossTable, sse_bucket_bits: u32) -> Self {
        Self {
            contexts: C3ContextTable::new(),
            moon: MoonMixer::new(table),
            mixer: Box::new(M5Mixer::with_sse_bucket_bits(table, sse_bucket_bits)),
            apm: C3Recalibrator::new(),
            continuation: Probability::default(),
            word: 0,
            last_byte: 0,
            last_bit: false,
            bit_run: 0,
        }
    }

    fn context_hashes(&self, history: &[u8], node: u8) -> [u64; C3_CONTEXT_COUNT] {
        let mut hashes = [0_u64; C3_CONTEXT_COUNT];
        let position = history.len();
        for (slot, &order) in C3_BYTE_ORDERS.iter().enumerate() {
            let start = position.saturating_sub(order);
            let mut hash = fnv1a64(FNV_OFFSET, &[TAG_ORDER, order as u8]);
            hash = fnv1a64(hash, &history[start..position]);
            hashes[slot] = fnv1a64(hash, &[node]);
        }
        let near = position.checked_sub(1).map(|i| history[i]).unwrap_or(0);
        let far = position.checked_sub(3).map(|i| history[i]).unwrap_or(0);
        hashes[6] = fnv1a64(fnv1a64(FNV_OFFSET, &[TAG_SPARSE]), &[near, far, node]);
        let word = fnv1a64(fnv1a64(FNV_OFFSET, &[TAG_WORD]), &self.word.to_le_bytes());
        hashes[7] = fnv1a64(word, &[node]);
        hashes
    }

    fn resolve(&mut self, history: &[u8], node: u8) -> ([usize; 8], [u16; 8], u16) {
        let hashes = self.context_hashes(history, node);
        let mut indices = [0_usize; 8];
        let mut probabilities = [0_u16; 8];
        let mut confidence = 0_u32;
        for (slot, hash) in hashes.into_iter().enumerate() {
            let index = self.contexts.resolve(hash);
            let cell = self.contexts.cells[index];
            indices[slot] = index;
            probabilities[slot] = cell.probability;
            confidence += u32::from(cell.confidence);
        }
        (
            indices,
            probabilities,
            (confidence / 8).min(u32::from(u16::MAX)) as u16,
        )
    }

    fn event_id(&self, node: u8) -> u64 {
        (u64::from(self.last_byte) << 8) | u64::from(node)
    }

    fn predict(&mut self, probabilities: &[u16; 8], node: u8, confidence: u16) -> u16 {
        let event_id = self.event_id(node);
        let base = self.moon.predict(node, self.last_byte, probabilities);
        let mixed = self.mixer.predict(event_id, base);
        self.apm.predict(event_id, mixed, confidence, self.bit_run)
    }

    fn update(&mut self, indices: &[usize; 8], bit: bool) {
        self.apm.update(bit);
        self.mixer.update(bit);
        self.moon.update(bit);
        for index in indices {
            self.contexts.observe(*index, bit);
        }
        if self.bit_run == 0 || bit != self.last_bit {
            self.bit_run = 1;
            self.last_bit = bit;
        } else {
            self.bit_run = self.bit_run.saturating_add(1);
        }
    }

    fn advance_byte(&mut self, byte: u8) {
        self.last_byte = byte;
        if is_word_byte(byte) {
            let seed = if self.word == 0 {
                fnv1a64(FNV_OFFSET, &[TAG_WORD_ACCUM])
            } else {
                self.word
            };
            let hash = fnv1a64(seed, &[byte]);
            self.word = if hash == 0 { FNV_OFFSET } else { hash };
        } else {
            self.word = 0;
        }
    }

    fn encode_continuation(
        &mut self,
        bit: bool,
        table: &LossTable,
        ledger: &mut Ledger,
        writer: &mut TapeWriter,
    ) -> Result<(), C3Error> {
        let base = self.continuation.probability_of_one();
        let mixed = self.mixer.predict(CONTINUATION_EVENT_ID, base);
        let charged = self
            .apm
            .predict(CONTINUATION_EVENT_ID, mixed, 0, self.bit_run);
        charge(charged, bit, table, ledger)?;
        writer.push_bit(bit)?;
        self.apm.update(bit);
        self.mixer.update(bit);
        self.continuation.update(bit, CONTINUATION_RATE_SHIFT);
        self.track_run(bit);
        Ok(())
    }

    fn decode_continuation(
        &mut self,
        table: &LossTable,
        ledger: &mut Ledger,
        reader: &mut TapeReader<'_>,
    ) -> Result<bool, C3Error> {
        let bit = reader.read_bit()?;
        let base = self.continuation.probability_of_one();
        let mixed = self.mixer.predict(CONTINUATION_EVENT_ID, base);
        let charged = self
            .apm
            .predict(CONTINUATION_EVENT_ID, mixed, 0, self.bit_run);
        charge(charged, bit, table, ledger)?;
        self.apm.update(bit);
        self.mixer.update(bit);
        self.continuation.update(bit, CONTINUATION_RATE_SHIFT);
        self.track_run(bit);
        Ok(bit)
    }

    fn track_run(&mut self, bit: bool) {
        if self.bit_run == 0 || bit != self.last_bit {
            self.bit_run = 1;
            self.last_bit = bit;
        } else {
            self.bit_run = self.bit_run.saturating_add(1);
        }
    }

    fn encode_byte(
        &mut self,
        byte: u8,
        history: &[u8],
        table: &LossTable,
        ledger: &mut Ledger,
        writer: &mut TapeWriter,
    ) -> Result<(), C3Error> {
        let mut node = 1_u32;
        for shift in (0..8_u32).rev() {
            let bit = (byte >> shift) & 1 == 1;
            let (indices, probabilities, confidence) = self.resolve(history, node as u8);
            let charged = self.predict(&probabilities, node as u8, confidence);
            charge(charged, bit, table, ledger)?;
            writer.push_bit(bit)?;
            self.update(&indices, bit);
            node = (node << 1) | u32::from(bit);
        }
        self.advance_byte(byte);
        Ok(())
    }

    fn decode_byte(
        &mut self,
        history: &[u8],
        table: &LossTable,
        ledger: &mut Ledger,
        reader: &mut TapeReader<'_>,
    ) -> Result<u8, C3Error> {
        let mut node = 1_u32;
        for _ in 0..8 {
            let bit = reader.read_bit()?;
            let (indices, probabilities, confidence) = self.resolve(history, node as u8);
            let charged = self.predict(&probabilities, node as u8, confidence);
            charge(charged, bit, table, ledger)?;
            self.update(&indices, bit);
            node = (node << 1) | u32::from(bit);
        }
        let byte = (node & 0xff) as u8;
        self.advance_byte(byte);
        Ok(byte)
    }
}

fn charge(
    probability: u16,
    bit: bool,
    table: &LossTable,
    ledger: &mut Ledger,
) -> Result<(), C3Error> {
    let loss = table
        .get(observed_probability(probability, bit))
        .ok_or(C3Error::InvalidProbability)?;
    ledger
        .add_modeled_event(loss)
        .ok_or(C3Error::LedgerOverflow)?;
    Ok(())
}

pub fn encode_c3_item(
    source: &[u8],
    table: &LossTable,
    item_index: u8,
) -> Result<(Tape, Ledger), C3Error> {
    encode_c3_item_with_bits(source, table, item_index, crate::s0::SSE_BASE_BUCKET_BITS)
}

pub fn encode_c3_item_with_bits(
    source: &[u8],
    table: &LossTable,
    item_index: u8,
    sse_bucket_bits: u32,
) -> Result<(Tape, Ledger), C3Error> {
    let (tape, ledger, _) =
        encode_c3_item_with_bits_and_quarters(source, table, item_index, sse_bucket_bits)?;
    Ok((tape, ledger))
}

pub fn encode_c3_item_with_bits_and_quarters(
    source: &[u8],
    table: &LossTable,
    item_index: u8,
    sse_bucket_bits: u32,
) -> Result<(Tape, Ledger, [C3QuarterSnapshot; 4]), C3Error> {
    let mut model = C3Model::new(table, sse_bucket_bits);
    let mut writer = TapeWriter::new(C3_ARM_ID, item_index);
    let mut ledger = Ledger::default();
    let mut quarters = [C3QuarterSnapshot::default(); 4];
    let boundaries: [usize; 4] = std::array::from_fn(|index| {
        (source.len() as u128 * (index + 1) as u128).div_ceil(4) as usize
    });
    let mut next_quarter = 0_usize;
    for (position, byte) in source.iter().copied().enumerate() {
        model.encode_continuation(true, table, &mut ledger, &mut writer)?;
        model.encode_byte(byte, &source[..position], table, &mut ledger, &mut writer)?;
        if byte == b'\n' {
            ledger.add_record().ok_or(C3Error::LedgerOverflow)?;
        }
        while next_quarter < 3 && position + 1 >= boundaries[next_quarter] {
            quarters[next_quarter] = C3QuarterSnapshot {
                source_bytes: boundaries[next_quarter] as u64,
                modeled_binary_events: ledger.modeled_binary_events,
                modeled_loss_q24: ledger.modeled_loss_q24,
            };
            next_quarter += 1;
        }
    }
    model.encode_continuation(false, table, &mut ledger, &mut writer)?;
    quarters[3] = C3QuarterSnapshot {
        source_bytes: source.len() as u64,
        modeled_binary_events: ledger.modeled_binary_events,
        modeled_loss_q24: ledger.modeled_loss_q24,
    };
    Ok((writer.finish(), ledger, quarters))
}

pub fn decode_c3_item(
    tape: &Tape,
    ledger: Ledger,
    table: &LossTable,
    item_index: u8,
) -> Result<Vec<u8>, C3Error> {
    decode_c3_item_with_bits(
        tape,
        ledger,
        table,
        item_index,
        crate::s0::SSE_BASE_BUCKET_BITS,
    )
}

pub fn decode_c3_item_with_bits(
    tape: &Tape,
    expected: Ledger,
    table: &LossTable,
    item_index: u8,
    sse_bucket_bits: u32,
) -> Result<Vec<u8>, C3Error> {
    if tape.arm_id() != C3_ARM_ID || tape.item_index() != item_index {
        return Err(C3Error::TapeIdentityMismatch);
    }
    let mut model = C3Model::new(table, sse_bucket_bits);
    let mut ledger = Ledger::default();
    let mut reader = tape.reader();
    let mut output = Vec::new();
    loop {
        if !model.decode_continuation(table, &mut ledger, &mut reader)? {
            break;
        }
        let byte = model.decode_byte(&output, table, &mut ledger, &mut reader)?;
        output.push(byte);
        if byte == b'\n' {
            ledger.add_record().ok_or(C3Error::LedgerOverflow)?;
        }
    }
    if !reader.is_finished() {
        return Err(C3Error::TrailingChargedData);
    }
    if ledger != expected {
        return Err(C3Error::LedgerDivergence {
            encoder: expected,
            decoder: ledger,
        });
    }
    Ok(output)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum C3Error {
    InvalidProbability,
    LedgerOverflow,
    TapeIdentityMismatch,
    TrailingChargedData,
    LedgerDivergence { encoder: Ledger, decoder: Ledger },
    Tape(TapeError),
}

impl From<TapeError> for C3Error {
    fn from(error: TapeError) -> Self {
        Self::Tape(error)
    }
}

impl Display for C3Error {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "moon C3 error: {self:?}")
    }
}

impl Error for C3Error {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cell_is_six_bytes_and_adapts_after_a_regime_change() {
        assert_eq!(std::mem::size_of::<C3Cell>(), 6);
        let mut cell = C3Cell::default();
        for _ in 0..512 {
            cell.observe(true);
        }
        let before = cell.probability;
        for _ in 0..32 {
            cell.observe(false);
        }
        assert!(before > 60_000);
        assert!(
            cell.probability < 32_768,
            "regime change was not tracked: {}",
            cell.probability
        );
    }

    #[test]
    fn cold_cells_learn_faster_than_warm_cells() {
        let mut cold = C3Cell::default();
        cold.observe(true);
        let cold_delta = i32::from(cold.probability) - 32_768;

        let mut warm = C3Cell::default();
        for index in 0..512 {
            warm.observe(index % 2 == 0);
        }
        let before = warm.probability;
        warm.observe(true);
        let warm_delta = i32::from(warm.probability) - i32::from(before);
        assert!(warm.confidence > 255);
        assert!(cold_delta > warm_delta);
    }

    #[test]
    fn collision_resolution_reuses_a_matching_cold_cell_before_eviction() {
        let mut table = C3ContextTable::with_cells(8);
        let hash = 3_u64 | (0x22_u64 << 40);
        let index = table.resolve(hash);
        table.cells[index].priority = 0;
        table.cells[index].probability = 40_000;
        assert_eq!(table.resolve(hash), index);
        assert_eq!(table.cells[index].probability, 40_000);
    }

    #[test]
    fn residual_apm_is_initially_neutral_and_deterministic() {
        let mut first = C3Recalibrator::new();
        let mut second = C3Recalibrator::new();
        assert_eq!(first.predict(7, 40_000, 12, 3), 40_000);
        assert_eq!(second.predict(7, 40_000, 12, 3), 40_000);
        first.update(true);
        second.update(true);
        assert_eq!(
            first.predict(7, 40_000, 12, 3),
            second.predict(7, 40_000, 12, 3)
        );
    }

    #[test]
    fn exact_roundtrip_and_identity_rejection() {
        let table = LossTable::generate();
        let source = b"{\"level\":\"info\",\"value\":1}\n{\"level\":\"warn\",\"value\":2}\n";
        let (tape, ledger) = encode_c3_item(source, &table, 9).unwrap();
        assert_eq!(decode_c3_item(&tape, ledger, &table, 9).unwrap(), source);
        assert_eq!(
            decode_c3_item(&tape, ledger, &table, 8),
            Err(C3Error::TapeIdentityMismatch)
        );
    }

    #[test]
    fn declared_state_adds_exactly_six_mib_to_h1_shape() {
        let table = LossTable::generate();
        let (mixer, sse) = M5Mixer::new(&table).declared_state_bytes();
        assert_eq!(
            c3_declared_state_bytes(&table, crate::s0::SSE_BASE_BUCKET_BITS),
            C3_CONTEXT_TABLE_BYTES + MOON_MIXER_WEIGHT_BYTES + mixer + sse + 6 * 1024 * 1024
        );
        assert_eq!(
            c3_declared_state_bytes(&table, crate::s0::SSE_BASE_BUCKET_BITS),
            126_238_720
        );
    }

    #[test]
    fn quarter_snapshots_cover_exact_source_and_loss_deltas() {
        let table = LossTable::generate();
        let source = b"123456789";
        let (_, ledger, quarters) = encode_c3_item_with_bits_and_quarters(
            source,
            &table,
            0,
            crate::s0::SSE_BASE_BUCKET_BITS,
        )
        .unwrap();
        assert_eq!(quarters.map(|quarter| quarter.source_bytes), [3, 5, 7, 9]);
        assert_eq!(
            quarters[3].modeled_binary_events,
            ledger.modeled_binary_events
        );
        assert_eq!(quarters[3].modeled_loss_q24, ledger.modeled_loss_q24);
        assert!(quarters
            .windows(2)
            .all(|pair| pair[0].modeled_loss_q24 <= pair[1].modeled_loss_q24));
    }
}
