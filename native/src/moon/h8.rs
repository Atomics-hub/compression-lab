//! H8 arm: frozen offline-learned mixer weights over H1's adaptive contexts.
//!
//! Development-only prescreen arm for the moonshot cycle 1 (Lane 2). H8 is an
//! H1 variant: it keeps H1's adaptive shared context table (the same eight
//! hashed byte-order/sparse/word contexts sharing one open-addressed
//! [`ContextTable`]) and an adaptive SSE recalibration stage, but it
//! **replaces** H1's adaptive per-context logistic mixer (and the s0 adaptive
//! mixer table it fed) with a **frozen static weight vector** indexed by
//! `(context slot x confidence bucket)`. That vector is learned OFFLINE on a
//! pinned public month-A slice and shipped as a small committed data file whose
//! SHA-256 is pinned and verified here; it never learns per event at
//! encode/decode time. The arm therefore tests, cheaply, whether mixing's
//! benefit is structural/transferable or must be learned live per stream.
//!
//! Every modeled bit is still charged read-only through the frozen s0
//! [`Ledger`] and written to the frozen s0 tape, so the projection is exact,
//! integer-only, and directly comparable to the other moon arms. Encode
//! immediately re-decodes and checks ledger equality; decode is fail-closed on
//! corruption, exhaustion, trailing data, and arm/item identity mismatch. No
//! s0 behavior is mutated; the s0 stretch/squash transform is reconstructed
//! locally from the frozen [`LossTable`], the same pattern the H1 moon mixer
//! uses.

use crate::s0::{
    Ledger, LossTable, Probability, Tape, TapeError, TapeReader, TapeWriter, MAX_PROBABILITY,
    MIN_PROBABILITY, SSE_NODES,
};
use std::error::Error;
use std::fmt::{Display, Formatter};

use super::table::{ContextTable, H1_CONTEXT_TABLE_BYTES};

/// Tape arm identity for the H8 static-mixer arm. Disjoint from every other
/// moon and s0 arm id so a tape can never be decoded under the wrong kernel.
pub const H8_ARM_ID: u8 = 103;
/// Number of hashed contexts combined per modeled bit (identical to H1).
pub const H8_CONTEXT_COUNT: usize = 8;
/// Byte orders (context lengths in bytes) of the six direct contexts.
pub const H8_BYTE_ORDERS: [usize; 6] = [1, 2, 3, 4, 6, 8];
/// Number of confidence buckets a context cell is quantized into.
pub const H8_CONFIDENCE_BUCKETS: usize = 16;
/// The frozen weight vector: one weight per `(context slot x confidence
/// bucket)` plus one constant-bias weight.
pub const H8_STATIC_WEIGHT_COUNT: usize = H8_CONTEXT_COUNT * H8_CONFIDENCE_BUCKETS + 1;
/// Index of the constant-bias weight (last entry of the vector).
const H8_BIAS_WEIGHT_INDEX: usize = H8_CONTEXT_COUNT * H8_CONFIDENCE_BUCKETS;
/// Declared mutable-state bytes contributed by the frozen weight vector
/// (`i32` per weight). Tiny by construction (< 0.1 MiB): the whole point of H8.
pub const H8_STATIC_WEIGHT_BYTES: usize = H8_STATIC_WEIGHT_COUNT * 4;

/// Offline training/procedure version. Travels in the weight-file header and
/// the training receipt; bump it if the learning procedure or mixing math
/// changes so a stale artifact is rejected.
pub const H8_PROCEDURE_VERSION: u32 = 1;

/// Probability update rate shift for the continuation and SSE cells (matches
/// the s0 event layer's `RATE_SHIFT`).
const H8_RATE_SHIFT: u32 = 5;

// Fixed-point mixing constants, mirrored from the moon logistic mixer so the
// frozen weights compose with the same stretch/squash transform.
const WEIGHT_ONE: i32 = 1 << 16;
/// Per-input initial weight used to seed offline training (8 contexts + bias).
pub const H8_WEIGHT_INIT: i32 = WEIGHT_ONE / (H8_CONTEXT_COUNT as i32 + 1);
const WEIGHT_LIMIT: i32 = 1 << 20;
const LEARN_SHIFT: u32 = 34;
const STRETCH_CLAMP: i64 = 8 << 24;
const BIAS_STRETCH: i64 = 1 << 24;

// Disjoint FNV-1a namespaces per context kind (identical to H1 so the two arms
// resolve the exact same adaptive contexts; only the mixer differs).
const TAG_ORDER: u8 = 0x01;
const TAG_SPARSE: u8 = 0xa5;
const TAG_WORD: u8 = 0x5a;
const TAG_WORD_ACCUM: u8 = 0x33;

// SSE bucket / continuation event identities.
const CONTINUATION_EVENT_ID: u64 = u64::MAX;

const FNV_OFFSET: u64 = 14_695_981_039_346_656_037;
const FNV_PRIME: u64 = 1_099_511_628_211;

// Committed weight-file layout: a 20-byte header then the `i32` weights, all
// little-endian. The header pins the dimensions so a shape-mismatched or
// truncated artifact is rejected before it is trusted.
const WEIGHT_FILE_MAGIC: [u8; 4] = *b"H8SM";
const WEIGHT_FILE_HEADER_BYTES: usize = 20;
/// Total committed weight-file length in bytes.
pub const H8_WEIGHT_FILE_BYTES: usize = WEIGHT_FILE_HEADER_BYTES + H8_STATIC_WEIGHT_BYTES;

/// The offline-learned static weight vector, embedded at build time and pinned
/// by SHA-256 in the tests. Regenerated only by the offline trainer bin on the
/// pinned month-A slice; never by CI (the slice is out of tree).
const EMBEDDED_WEIGHTS: &[u8] = include_bytes!("data/h8-static-mixer-weights.bin");

/// SHA-256 of [`EMBEDDED_WEIGHTS`], pinned so any change to the shipped static
/// weights is a visible, reviewed edit. Verified by `weight_file_sha256_is_pinned`.
pub const H8_WEIGHT_FILE_SHA256: &str =
    "ad0d73cdfcac3e376731852eaf99b1c146a933e9f8efbdd49743bf7b538c908e";

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

/// Quantize a context cell's confidence (its total observation count) into one
/// of [`H8_CONFIDENCE_BUCKETS`] buckets by bit width: bucket 0 is an unseen
/// cell, higher buckets are exponentially more-observed cells. Total function,
/// saturating at the last bucket.
#[must_use]
pub fn confidence_bucket(confidence: u32) -> usize {
    let width = (u32::BITS - confidence.leading_zeros()) as usize;
    width.min(H8_CONFIDENCE_BUCKETS - 1)
}

/// `stretch(p) = log2(p / (65536 - p))` in Q24, reconstructed exactly from the
/// frozen loss table (its `build_stretch` is private to `m5`). Shared by the
/// frozen mixer and the SSE stage; not charged as state (a derived constant,
/// like the loss table itself).
fn build_stretch(table: &LossTable) -> Box<[i32; 65_536]> {
    let mut values = vec![0_i32; 65_536].into_boxed_slice();
    for probability in 1..65_536_u32 {
        let loss_one = table.get(probability).expect("in range");
        let loss_zero = table.get(65_536 - probability).expect("in range");
        values[probability as usize] = loss_zero as i32 - loss_one as i32;
    }
    values[0] = values[1];
    values
        .try_into()
        .unwrap_or_else(|_| unreachable!("stretch table length is constant"))
}

fn stretch_of(stretch: &[i32; 65_536], probability_of_one: u16) -> i64 {
    i64::from(stretch[usize::from(probability_of_one)]).clamp(-STRETCH_CLAMP, STRETCH_CLAMP)
}

/// Smallest probability whose stretch reaches `target` (ties resolve to the
/// smallest `p`), by binary search over the monotone stretch table. Identical
/// rule to the s0 mixer's squash.
fn squash(stretch: &[i32; 65_536], target: i64) -> i32 {
    let mut low = 1_u32;
    let mut high = 65_535_u32;
    while low < high {
        let middle = (low + high) / 2;
        if i64::from(stretch[middle as usize]) >= target {
            high = middle;
        } else {
            low = middle + 1;
        }
    }
    low as i32
}

/// One mixer input: which weight it draws and its stretched value. Reused by
/// both frozen inference (which ignores the gradient) and offline training
/// (which applies it), so the two share identical mixing arithmetic.
#[derive(Clone, Copy)]
struct MixInput {
    weight_index: usize,
    stretch_value: i64,
}

/// Compute the mixed log-odds (Q24) for one bit from the eight context
/// predictions and their confidence buckets, plus the constant bias, using the
/// given weights. Returns the clamped mixed stretch and the per-input records
/// needed to apply a gradient step. Pure and deterministic.
fn mix(
    weights: &[i32],
    stretch: &[i32; 65_536],
    probabilities: &[u16; H8_CONTEXT_COUNT],
    confidence_buckets: &[usize; H8_CONTEXT_COUNT],
) -> (i64, [MixInput; H8_CONTEXT_COUNT + 1]) {
    let mut inputs = [MixInput {
        weight_index: 0,
        stretch_value: 0,
    }; H8_CONTEXT_COUNT + 1];
    let mut dot = 0_i64;
    for slot in 0..H8_CONTEXT_COUNT {
        let weight_index = slot * H8_CONFIDENCE_BUCKETS + confidence_buckets[slot];
        let stretch_value = stretch_of(stretch, probabilities[slot]);
        dot += i64::from(weights[weight_index]) * stretch_value;
        inputs[slot] = MixInput {
            weight_index,
            stretch_value,
        };
    }
    dot += i64::from(weights[H8_BIAS_WEIGHT_INDEX]) * BIAS_STRETCH;
    inputs[H8_CONTEXT_COUNT] = MixInput {
        weight_index: H8_BIAS_WEIGHT_INDEX,
        stretch_value: BIAS_STRETCH,
    };
    let mixed_q24 = (dot >> 16).clamp(-STRETCH_CLAMP, STRETCH_CLAMP);
    (mixed_q24, inputs)
}

/// Apply the pinned logistic gradient step to the weights for one observed
/// bit. Used only by the offline trainer; the frozen inference path never
/// calls it. Deterministic integer arithmetic.
fn apply_gradient(
    weights: &mut [i32],
    inputs: &[MixInput; H8_CONTEXT_COUNT + 1],
    mixed_probability: i32,
    bit: bool,
) {
    let error = i64::from(if bit { 65_536 } else { 0 } - mixed_probability);
    for input in inputs {
        let delta = ((error * input.stretch_value) >> LEARN_SHIFT) as i32;
        let weight = &mut weights[input.weight_index];
        *weight = (*weight + delta).clamp(-WEIGHT_LIMIT, WEIGHT_LIMIT);
    }
}

/// The frozen static mixer: fixed offline-learned weights, no per-event
/// learning. Loaded from the embedded, SHA-pinned weight file.
pub struct StaticMixer {
    weights: Box<[i32; H8_STATIC_WEIGHT_COUNT]>,
}

impl StaticMixer {
    /// Load the frozen mixer from the embedded committed weight file, verifying
    /// the header dimensions. Fails closed on any shape or magic mismatch.
    pub fn from_embedded() -> Result<Self, H8Error> {
        let weights = parse_weight_file(EMBEDDED_WEIGHTS)?;
        Ok(Self {
            weights: Box::new(weights),
        })
    }

    /// Mix the eight context predictions plus the constant bias into one base
    /// probability of a one, using the frozen weights and the shared stretch
    /// table. No state changes: the mixer is frozen.
    #[must_use]
    fn predict(
        &self,
        stretch: &[i32; 65_536],
        probabilities: &[u16; H8_CONTEXT_COUNT],
        confidence_buckets: &[usize; H8_CONTEXT_COUNT],
    ) -> u16 {
        let (mixed_q24, _) = mix(
            self.weights.as_slice(),
            stretch,
            probabilities,
            confidence_buckets,
        );
        (squash(stretch, mixed_q24) as u32)
            .clamp(u32::from(MIN_PROBABILITY), u32::from(MAX_PROBABILITY)) as u16
    }

    /// Declared mutable-state bytes (the weight vector only).
    #[cfg(test)]
    #[must_use]
    pub fn declared_state_bytes(&self) -> usize {
        H8_STATIC_WEIGHT_BYTES
    }
}

/// The adaptive SSE recalibration stage, kept from H1. Reconstructs the s0 SSE
/// interpolation locally over the shared stretch table; the SSE cells are the
/// only mutable estimator state H8 learns at encode/decode time.
struct MoonSse {
    sse: Box<[Probability]>,
    bucket_mask: u64,
    scratch: Option<SseScratch>,
}

struct SseScratch {
    sse_cell: usize,
    base_probability: i32,
}

impl MoonSse {
    fn new(sse_bucket_bits: u32) -> Self {
        let sse_buckets = 1_usize << sse_bucket_bits;
        Self {
            sse: vec![Probability::default(); sse_buckets * SSE_NODES].into_boxed_slice(),
            bucket_mask: (sse_buckets - 1) as u64,
            scratch: None,
        }
    }

    #[cfg(test)]
    fn declared_state_bytes(&self) -> usize {
        self.sse.len() * 2
    }

    /// Refine a base probability for one charged event, keyed by the event id.
    /// Must be followed by exactly one [`update`] with the observed bit.
    ///
    /// [`update`]: MoonSse::update
    #[must_use]
    fn predict(&mut self, stretch: &[i32; 65_536], id: u64, base_probability_of_one: u16) -> u16 {
        let hash = fnv1a64(fnv1a64(FNV_OFFSET, b"moon-h8-sse"), &id.to_le_bytes());
        let sse_bucket = (hash & self.bucket_mask) as usize;
        let base_stretch = stretch_of(stretch, base_probability_of_one);

        let span = 2 * STRETCH_CLAMP as u128;
        let offset = (base_stretch + STRETCH_CLAMP) as u128;
        let scaled = ((offset * ((SSE_NODES - 1) as u128)) << 16) / span;
        let mut node = (scaled >> 16) as usize;
        let mut fraction = (scaled & 0xffff) as u32;
        if node >= SSE_NODES - 1 {
            node = SSE_NODES - 2;
            fraction = 65_536;
        }
        let base_cell = sse_bucket * SSE_NODES + node;
        let low = u32::from(self.sse[base_cell].probability_of_one());
        let high = u32::from(self.sse[base_cell + 1].probability_of_one());
        let interpolated = (low * (65_536 - fraction) + high * fraction) >> 16;

        let base_probability = i32::from(base_probability_of_one);
        let final_probability = ((3 * interpolated + base_probability as u32) / 4)
            .clamp(u32::from(MIN_PROBABILITY), u32::from(MAX_PROBABILITY))
            as u16;
        self.scratch = Some(SseScratch {
            sse_cell: if fraction >= 32_768 {
                base_cell + 1
            } else {
                base_cell
            },
            base_probability,
        });
        final_probability
    }

    fn update(&mut self, bit: bool) {
        let Some(scratch) = self.scratch.take() else {
            debug_assert!(false, "moon H8 SSE update without a preceding predict");
            return;
        };
        let _ = scratch.base_probability;
        self.sse[scratch.sse_cell].update(bit, H8_RATE_SHIFT);
    }
}

/// Declared model-state bytes for an H8 model at the given SSE capacity: the
/// 96 MiB context table, the adaptive SSE table, and the frozen static weight
/// vector. Scratch registers and derived constant lookups (stretch table) are
/// excluded, mirroring the s0/H1 `declared_state_bytes` convention.
#[must_use]
pub fn h8_declared_state_bytes(_table: &LossTable, sse_bucket_bits: u32) -> usize {
    let sse_buckets = 1_usize << sse_bucket_bits;
    let sse_bytes = sse_buckets * SSE_NODES * 2;
    H1_CONTEXT_TABLE_BYTES + sse_bytes + H8_STATIC_WEIGHT_BYTES
}

/// The mutable H8 model state, reused unchanged by the encoder and decoder so
/// both evolve byte-for-byte identically. Contexts and SSE are adaptive; the
/// mixer is frozen.
pub struct H8Model {
    contexts: ContextTable,
    mixer: StaticMixer,
    sse: MoonSse,
    stretch: Box<[i32; 65_536]>,
    continuation: Probability,
    word: u64,
    last_byte: u8,
}

impl H8Model {
    pub fn new(table: &LossTable, sse_bucket_bits: u32) -> Result<Self, H8Error> {
        Ok(Self {
            contexts: ContextTable::new(),
            mixer: StaticMixer::from_embedded()?,
            sse: MoonSse::new(sse_bucket_bits),
            stretch: build_stretch(table),
            continuation: Probability::default(),
            word: 0,
            last_byte: 0,
        })
    }

    /// The eight context hashes for one bit — six direct byte orders, one
    /// sparse context (positions p-1 and p-3), and the rolling word context —
    /// identical to H1 so the two arms resolve the same adaptive contexts.
    fn context_hashes(&self, history: &[u8], node: u8) -> [u64; H8_CONTEXT_COUNT] {
        let mut hashes = [0_u64; H8_CONTEXT_COUNT];
        let position = history.len();
        for (slot, &order) in H8_BYTE_ORDERS.iter().enumerate() {
            let start = position.saturating_sub(order);
            let mut hash = fnv1a64(FNV_OFFSET, &[TAG_ORDER, order as u8]);
            hash = fnv1a64(hash, &history[start..position]);
            hashes[slot] = fnv1a64(hash, &[node]);
        }
        let mut sparse = fnv1a64(FNV_OFFSET, &[TAG_SPARSE]);
        let near = position
            .checked_sub(1)
            .map(|index| history[index])
            .unwrap_or(0);
        let far = position
            .checked_sub(3)
            .map(|index| history[index])
            .unwrap_or(0);
        sparse = fnv1a64(sparse, &[near, far, node]);
        hashes[6] = sparse;
        let word = fnv1a64(FNV_OFFSET, &[TAG_WORD]);
        let word = fnv1a64(word, &self.word.to_le_bytes());
        hashes[7] = fnv1a64(word, &[node]);
        hashes
    }

    /// Resolve the eight contexts, returning cell indices to update after the
    /// bit, each cell's current probability of a one, and its confidence
    /// bucket for the frozen mixer.
    #[allow(clippy::type_complexity)]
    fn resolve(
        &mut self,
        history: &[u8],
        node: u8,
    ) -> (
        [usize; H8_CONTEXT_COUNT],
        [u16; H8_CONTEXT_COUNT],
        [usize; H8_CONTEXT_COUNT],
    ) {
        let hashes = self.context_hashes(history, node);
        let mut indices = [0_usize; H8_CONTEXT_COUNT];
        let mut probabilities = [0_u16; H8_CONTEXT_COUNT];
        let mut confidence_buckets = [0_usize; H8_CONTEXT_COUNT];
        for (slot, &hash) in hashes.iter().enumerate() {
            let index = self.contexts.resolve(hash);
            let cell = self.contexts.cell(index);
            indices[slot] = index;
            probabilities[slot] = cell.probability_of_one();
            confidence_buckets[slot] = confidence_bucket(cell.confidence());
        }
        (indices, probabilities, confidence_buckets)
    }

    fn event_id(&self, node: u8) -> u64 {
        (u64::from(self.last_byte) << 8) | u64::from(node)
    }

    fn observe(&mut self, indices: &[usize; H8_CONTEXT_COUNT], bit: bool) {
        for &index in indices {
            self.contexts.observe(index, bit);
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
            let hashed = fnv1a64(seed, &[byte]);
            self.word = if hashed == 0 { FNV_OFFSET } else { hashed };
        } else {
            self.word = 0;
        }
    }

    /// The shared prediction step for one modeled byte-bit: the frozen mixer
    /// produces a base probability; the adaptive SSE recalibrates it. Prediction
    /// is independent of the bit value, so the decoder reproduces the identical
    /// charged probability.
    fn predict_byte_bit(
        &mut self,
        probabilities: &[u16; H8_CONTEXT_COUNT],
        confidence_buckets: &[usize; H8_CONTEXT_COUNT],
        event_id: u64,
    ) -> u16 {
        let base = self
            .mixer
            .predict(&self.stretch, probabilities, confidence_buckets);
        self.sse.predict(&self.stretch, event_id, base)
    }

    fn encode_byte(
        &mut self,
        byte: u8,
        history: &[u8],
        table: &LossTable,
        ledger: &mut Ledger,
        writer: &mut TapeWriter,
    ) -> Result<(), H8Error> {
        let mut node: u32 = 1;
        for shift in (0..8_u32).rev() {
            let bit = (byte >> shift) & 1 == 1;
            let (indices, probabilities, confidence_buckets) = self.resolve(history, node as u8);
            let event_id = self.event_id(node as u8);
            let charged = self.predict_byte_bit(&probabilities, &confidence_buckets, event_id);
            let loss = table
                .get(observed_probability(charged, bit))
                .ok_or(H8Error::InvalidProbability)?;
            ledger
                .add_modeled_event(loss)
                .ok_or(H8Error::LedgerOverflow)?;
            writer.push_bit(bit)?;
            self.sse.update(bit);
            self.observe(&indices, bit);
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
    ) -> Result<u8, H8Error> {
        let mut node: u32 = 1;
        for _ in 0..8 {
            let (indices, probabilities, confidence_buckets) = self.resolve(history, node as u8);
            let event_id = self.event_id(node as u8);
            let bit = reader.read_bit()?;
            let charged = self.predict_byte_bit(&probabilities, &confidence_buckets, event_id);
            let loss = table
                .get(observed_probability(charged, bit))
                .ok_or(H8Error::InvalidProbability)?;
            ledger
                .add_modeled_event(loss)
                .ok_or(H8Error::LedgerOverflow)?;
            self.sse.update(bit);
            self.observe(&indices, bit);
            node = (node << 1) | u32::from(bit);
        }
        let byte = (node & 0xff) as u8;
        self.advance_byte(byte);
        Ok(byte)
    }

    fn encode_continuation_bit(
        &mut self,
        more: bool,
        table: &LossTable,
        ledger: &mut Ledger,
        writer: &mut TapeWriter,
    ) -> Result<(), H8Error> {
        let base = self.continuation.probability_of_one();
        let charged = self.sse.predict(&self.stretch, CONTINUATION_EVENT_ID, base);
        let loss = table
            .get(observed_probability(charged, more))
            .ok_or(H8Error::InvalidProbability)?;
        ledger
            .add_modeled_event(loss)
            .ok_or(H8Error::LedgerOverflow)?;
        writer.push_bit(more)?;
        self.sse.update(more);
        self.continuation.update(more, H8_RATE_SHIFT);
        Ok(())
    }

    fn decode_continuation_bit(
        &mut self,
        table: &LossTable,
        ledger: &mut Ledger,
        reader: &mut TapeReader<'_>,
    ) -> Result<bool, H8Error> {
        let more = reader.read_bit()?;
        let base = self.continuation.probability_of_one();
        let charged = self.sse.predict(&self.stretch, CONTINUATION_EVENT_ID, base);
        let loss = table
            .get(observed_probability(charged, more))
            .ok_or(H8Error::InvalidProbability)?;
        ledger
            .add_modeled_event(loss)
            .ok_or(H8Error::LedgerOverflow)?;
        self.sse.update(more);
        self.continuation.update(more, H8_RATE_SHIFT);
        Ok(more)
    }

    /// Declared model-state bytes for this concrete model (context table + SSE
    /// + frozen weights).
    #[cfg(test)]
    #[must_use]
    fn declared_state_bytes(&self) -> usize {
        self.contexts.declared_state_bytes()
            + self.sse.declared_state_bytes()
            + self.mixer.declared_state_bytes()
    }
}

/// Encode one item under the H8 arm at the base SSE capacity.
pub fn encode_h8_item(
    source: &[u8],
    table: &LossTable,
    item_index: u8,
) -> Result<(Tape, Ledger), H8Error> {
    encode_h8_item_with_bits(source, table, item_index, crate::s0::SSE_BASE_BUCKET_BITS)
}

/// Encode one item under the H8 arm at an explicit SSE capacity.
pub fn encode_h8_item_with_bits(
    source: &[u8],
    table: &LossTable,
    item_index: u8,
    sse_bucket_bits: u32,
) -> Result<(Tape, Ledger), H8Error> {
    let mut model = H8Model::new(table, sse_bucket_bits)?;
    let mut writer = TapeWriter::new(H8_ARM_ID, item_index);
    let mut ledger = Ledger::default();
    for (position, &byte) in source.iter().enumerate() {
        model.encode_continuation_bit(true, table, &mut ledger, &mut writer)?;
        model.encode_byte(byte, &source[..position], table, &mut ledger, &mut writer)?;
        if byte == b'\n' {
            ledger.add_record().ok_or(H8Error::LedgerOverflow)?;
        }
    }
    model.encode_continuation_bit(false, table, &mut ledger, &mut writer)?;
    Ok((writer.finish(), ledger))
}

/// Decode one item under the H8 arm at the base SSE capacity.
pub fn decode_h8_item(
    tape: &Tape,
    expected_ledger: Ledger,
    table: &LossTable,
    expected_item_index: u8,
) -> Result<Vec<u8>, H8Error> {
    decode_h8_item_with_bits(
        tape,
        expected_ledger,
        table,
        expected_item_index,
        crate::s0::SSE_BASE_BUCKET_BITS,
    )
}

/// Decode one item under the H8 arm at an explicit SSE capacity, checking arm
/// and item identity and independent ledger equality.
pub fn decode_h8_item_with_bits(
    tape: &Tape,
    expected_ledger: Ledger,
    table: &LossTable,
    expected_item_index: u8,
    sse_bucket_bits: u32,
) -> Result<Vec<u8>, H8Error> {
    if tape.arm_id() != H8_ARM_ID || tape.item_index() != expected_item_index {
        return Err(H8Error::TapeIdentityMismatch);
    }
    let mut model = H8Model::new(table, sse_bucket_bits)?;
    let mut ledger = Ledger::default();
    let mut reader = tape.reader();
    let mut output: Vec<u8> = Vec::new();
    loop {
        if !model.decode_continuation_bit(table, &mut ledger, &mut reader)? {
            break;
        }
        let byte = model.decode_byte(&output, table, &mut ledger, &mut reader)?;
        output.push(byte);
        if byte == b'\n' {
            ledger.add_record().ok_or(H8Error::LedgerOverflow)?;
        }
    }
    if !reader.is_finished() {
        return Err(H8Error::TrailingChargedData);
    }
    if ledger != expected_ledger {
        return Err(H8Error::LedgerDivergence {
            encoder: expected_ledger,
            decoder: ledger,
        });
    }
    Ok(output)
}

// ----- offline training (used by the trainer bin, not the encode/decode path) -----

/// Initial weight vector seeding offline training: every input starts at the
/// balanced `WEIGHT_ONE / (inputs)` weight, matching the moon mixer's seed.
#[must_use]
pub fn initial_static_weights() -> Vec<i32> {
    vec![H8_WEIGHT_INIT; H8_STATIC_WEIGHT_COUNT]
}

/// Learn the frozen static mixer weights from one public month-A slice by a
/// single deterministic online-logistic pass: resolve H8's exact adaptive
/// contexts over the bytes, mix with the current weights, apply the pinned
/// gradient toward each observed bit, and advance the (adaptive) contexts. The
/// final weights are the shipped frozen vector. Byte-for-byte deterministic:
/// identical input yields an identical vector.
///
/// Reads only the bytes it is given (the trainer bin passes the pinned month-A
/// slice); it never touches month B or any licensed corpus.
#[must_use]
pub fn train_static_weights(month_a: &[u8], table: &LossTable) -> Vec<i32> {
    let stretch = build_stretch(table);
    let mut contexts = ContextTable::new();
    let mut weights = initial_static_weights();
    let mut word: u64 = 0;
    let mut last_byte: u8 = 0;

    for (position, &byte) in month_a.iter().enumerate() {
        let history = &month_a[..position];
        let mut node: u32 = 1;
        for shift in (0..8_u32).rev() {
            let bit = (byte >> shift) & 1 == 1;
            let (indices, probabilities, confidence_buckets) =
                resolve_for_training(&mut contexts, history, node as u8, word);
            let (mixed_q24, inputs) = mix(&weights, &stretch, &probabilities, &confidence_buckets);
            let mixed_probability = squash(&stretch, mixed_q24);
            apply_gradient(&mut weights, &inputs, mixed_probability, bit);
            for &index in &indices {
                contexts.observe(index, bit);
            }
            node = (node << 1) | u32::from(bit);
        }
        // Advance the rolling word context exactly as the model does.
        let _ = &mut node;
        if is_word_byte(byte) {
            let seed = if word == 0 {
                fnv1a64(FNV_OFFSET, &[TAG_WORD_ACCUM])
            } else {
                word
            };
            let hashed = fnv1a64(seed, &[byte]);
            word = if hashed == 0 { FNV_OFFSET } else { hashed };
        } else {
            word = 0;
        }
        last_byte = byte;
    }
    let _ = last_byte;
    weights
}

/// Context resolution for the trainer, matching [`H8Model::resolve`] and
/// [`H8Model::context_hashes`] exactly but over a borrowed context table and
/// rolling word (the trainer does not build a full model).
#[allow(clippy::type_complexity)]
fn resolve_for_training(
    contexts: &mut ContextTable,
    history: &[u8],
    node: u8,
    word: u64,
) -> (
    [usize; H8_CONTEXT_COUNT],
    [u16; H8_CONTEXT_COUNT],
    [usize; H8_CONTEXT_COUNT],
) {
    let position = history.len();
    let mut hashes = [0_u64; H8_CONTEXT_COUNT];
    for (slot, &order) in H8_BYTE_ORDERS.iter().enumerate() {
        let start = position.saturating_sub(order);
        let mut hash = fnv1a64(FNV_OFFSET, &[TAG_ORDER, order as u8]);
        hash = fnv1a64(hash, &history[start..position]);
        hashes[slot] = fnv1a64(hash, &[node]);
    }
    let mut sparse = fnv1a64(FNV_OFFSET, &[TAG_SPARSE]);
    let near = position
        .checked_sub(1)
        .map(|index| history[index])
        .unwrap_or(0);
    let far = position
        .checked_sub(3)
        .map(|index| history[index])
        .unwrap_or(0);
    sparse = fnv1a64(sparse, &[near, far, node]);
    hashes[6] = sparse;
    let word_hash = fnv1a64(FNV_OFFSET, &[TAG_WORD]);
    let word_hash = fnv1a64(word_hash, &word.to_le_bytes());
    hashes[7] = fnv1a64(word_hash, &[node]);

    let mut indices = [0_usize; H8_CONTEXT_COUNT];
    let mut probabilities = [0_u16; H8_CONTEXT_COUNT];
    let mut confidence_buckets = [0_usize; H8_CONTEXT_COUNT];
    for (slot, &hash) in hashes.iter().enumerate() {
        let index = contexts.resolve(hash);
        let cell = contexts.cell(index);
        indices[slot] = index;
        probabilities[slot] = cell.probability_of_one();
        confidence_buckets[slot] = confidence_bucket(cell.confidence());
    }
    (indices, probabilities, confidence_buckets)
}

/// Serialize a weight vector into the committed weight-file layout (little-
/// endian header + weights). Deterministic; the trainer writes exactly this.
#[must_use]
pub fn serialize_weight_file(weights: &[i32]) -> Vec<u8> {
    assert_eq!(
        weights.len(),
        H8_STATIC_WEIGHT_COUNT,
        "weight vector must have the pinned length"
    );
    let mut bytes = Vec::with_capacity(H8_WEIGHT_FILE_BYTES);
    bytes.extend_from_slice(&WEIGHT_FILE_MAGIC);
    bytes.extend_from_slice(&H8_PROCEDURE_VERSION.to_le_bytes());
    bytes.extend_from_slice(&(H8_CONFIDENCE_BUCKETS as u32).to_le_bytes());
    bytes.extend_from_slice(&(H8_CONTEXT_COUNT as u32).to_le_bytes());
    bytes.extend_from_slice(&(H8_STATIC_WEIGHT_COUNT as u32).to_le_bytes());
    for &weight in weights {
        bytes.extend_from_slice(&weight.to_le_bytes());
    }
    bytes
}

/// Parse and validate the committed weight-file layout into a fixed-size weight
/// array. Fails closed on magic, version, dimension, or length mismatch.
fn parse_weight_file(bytes: &[u8]) -> Result<[i32; H8_STATIC_WEIGHT_COUNT], H8Error> {
    if bytes.len() != H8_WEIGHT_FILE_BYTES {
        return Err(H8Error::WeightFileMalformed);
    }
    if bytes[0..4] != WEIGHT_FILE_MAGIC {
        return Err(H8Error::WeightFileMalformed);
    }
    let read_u32 = |offset: usize| -> u32 {
        u32::from_le_bytes([
            bytes[offset],
            bytes[offset + 1],
            bytes[offset + 2],
            bytes[offset + 3],
        ])
    };
    if read_u32(4) != H8_PROCEDURE_VERSION
        || read_u32(8) != H8_CONFIDENCE_BUCKETS as u32
        || read_u32(12) != H8_CONTEXT_COUNT as u32
        || read_u32(16) != H8_STATIC_WEIGHT_COUNT as u32
    {
        return Err(H8Error::WeightFileMalformed);
    }
    let mut weights = [0_i32; H8_STATIC_WEIGHT_COUNT];
    for (index, weight) in weights.iter_mut().enumerate() {
        let offset = WEIGHT_FILE_HEADER_BYTES + index * 4;
        *weight = i32::from_le_bytes([
            bytes[offset],
            bytes[offset + 1],
            bytes[offset + 2],
            bytes[offset + 3],
        ]);
    }
    Ok(weights)
}

/// H8 encode/decode error. Every variant is terminal for the item; the caller
/// discards partially charged state.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum H8Error {
    InvalidProbability,
    LedgerOverflow,
    TapeIdentityMismatch,
    TrailingChargedData,
    WeightFileMalformed,
    LedgerDivergence { encoder: Ledger, decoder: Ledger },
    Tape(TapeError),
}

impl From<TapeError> for H8Error {
    fn from(error: TapeError) -> Self {
        Self::Tape(error)
    }
}

impl Display for H8Error {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "moon H8 error: {self:?}")
    }
}

impl Error for H8Error {}

#[cfg(test)]
mod tests {
    use super::*;

    // Pinned once from the deterministic encoder; the tape is a pure function
    // of the source bytes, the arm/item identity, and the frozen weights.
    const PINNED_TAPE_SHA256: &str =
        "4dce3ff0b9a08456da5ac830c832125181bdb6832dba3624c2efe65f6dbb22be";

    fn regime_snippets() -> Vec<(&'static str, Vec<u8>)> {
        let mut snippets: Vec<(&'static str, Vec<u8>)> = Vec::new();

        let mut duplicated = Vec::new();
        for _ in 0..40 {
            duplicated.extend_from_slice(b"{\"level\":\"info\",\"msg\":\"ready\"}\n");
        }
        snippets.push(("high-duplication", duplicated));

        let mut varied = Vec::new();
        for index in 0..60_u32 {
            let mix = index.wrapping_mul(2_654_435_761);
            varied.extend_from_slice(
                format!(
                    "{{\"id\":{},\"session\":\"s{}\",\"tag\":\"{:08x}\",\"path\":\"/a/{}/{}\"}}\n",
                    100_000 + index,
                    index % 997,
                    mix,
                    index % 521,
                    index % 733
                )
                .as_bytes(),
            );
        }
        snippets.push(("high-cardinality", varied));

        let mut logs = Vec::new();
        for index in 0..50_u32 {
            logs.extend_from_slice(
                format!(
                    "2026-07-22 10:{:02}:{:02} WARN worker[{}] retrying\n",
                    index % 60,
                    (index * 7) % 60,
                    index % 8
                )
                .as_bytes(),
            );
        }
        snippets.push(("line-log", logs));

        snippets.push(("tiny", b"{}\n".to_vec()));
        snippets.push(("binary", (0..=255_u8).cycle().take(300).collect()));
        snippets.push(("no-newline", b"{\"tail\":true}".to_vec()));
        snippets.push(("empty", Vec::new()));

        snippets
    }

    #[test]
    fn round_trips_exactly_across_every_regime() {
        let table = LossTable::generate();
        for (name, source) in regime_snippets() {
            let (tape, ledger) = encode_h8_item(&source, &table, 1).unwrap();
            let decoded = decode_h8_item(&tape, ledger, &table, 1).unwrap();
            assert_eq!(decoded, source, "regime {name} did not round-trip");
            assert_eq!(ledger.raw_literal_bytes, 0, "H8 charges no literals");
        }
    }

    #[test]
    fn repeat_runs_are_byte_identical_in_tape_and_ledger() {
        let table = LossTable::generate();
        let source = regime_snippets().remove(1).1;
        let (tape_a, ledger_a) = encode_h8_item(&source, &table, 2).unwrap();
        let (tape_b, ledger_b) = encode_h8_item(&source, &table, 2).unwrap();
        assert_eq!(tape_a.to_bytes(), tape_b.to_bytes());
        assert_eq!(ledger_a, ledger_b);
    }

    #[test]
    fn decode_fails_closed_on_a_tampered_ledger() {
        let table = LossTable::generate();
        let source = b"{\"a\":1}\n{\"a\":2}\n{\"a\":1}\n".to_vec();
        let (tape, ledger) = encode_h8_item(&source, &table, 0).unwrap();
        let mut wrong = ledger;
        wrong.modeled_loss_q24 += 1;
        assert!(matches!(
            decode_h8_item(&tape, wrong, &table, 0),
            Err(H8Error::LedgerDivergence { .. })
        ));
    }

    #[test]
    fn decode_rejects_a_foreign_arm_or_item_identity() {
        let table = LossTable::generate();
        let source = b"hello world\n".to_vec();
        let (tape, ledger) = encode_h8_item(&source, &table, 3).unwrap();
        assert_eq!(
            decode_h8_item(&tape, ledger, &table, 4),
            Err(H8Error::TapeIdentityMismatch)
        );
    }

    #[test]
    fn refined_sse_bits_change_only_the_charged_probability() {
        let table = LossTable::generate();
        let source = regime_snippets().remove(2).1;
        let (base_tape, base_ledger) = encode_h8_item_with_bits(&source, &table, 0, 17).unwrap();
        let (refined_tape, refined_ledger) =
            encode_h8_item_with_bits(&source, &table, 0, 18).unwrap();
        // Larger SSE capacity refines the charged probability only: it never
        // changes the tape bits, the event structure, or the literals.
        assert_eq!(base_tape.to_bytes(), refined_tape.to_bytes());
        assert_eq!(
            base_ledger.modeled_binary_events,
            refined_ledger.modeled_binary_events
        );
        assert_eq!(base_ledger.records, refined_ledger.records);
        assert_eq!(
            base_ledger.raw_literal_bytes,
            refined_ledger.raw_literal_bytes
        );
        assert_eq!(
            decode_h8_item_with_bits(&refined_tape, refined_ledger, &table, 0, 18).unwrap(),
            source
        );
    }

    #[test]
    fn declared_state_bytes_account_for_context_sse_and_frozen_weights() {
        let table = LossTable::generate();
        let model = H8Model::new(&table, crate::s0::SSE_BASE_BUCKET_BITS).unwrap();
        let standalone = h8_declared_state_bytes(&table, crate::s0::SSE_BASE_BUCKET_BITS);
        assert_eq!(model.declared_state_bytes(), standalone);
        // The 96 MiB context table dominates; the frozen weights are tiny.
        assert_eq!(
            model.contexts.declared_state_bytes(),
            H1_CONTEXT_TABLE_BYTES
        );
        assert_eq!(model.mixer.declared_state_bytes(), H8_STATIC_WEIGHT_BYTES);
        // Frozen weights are tiny by construction (< 0.1 MiB): the whole point.
        const _: () = assert!(H8_STATIC_WEIGHT_BYTES < 100 * 1024);
        // Regression pin of the exact figure the receipts report.
        assert_eq!(standalone, 109_314_564);
        // The refined SSE capacity only grows the SSE table.
        let refined = h8_declared_state_bytes(&table, crate::s0::SSE_REFINED_BUCKET_BITS);
        assert!(refined > standalone);
    }

    #[test]
    fn projection_is_exact_and_scores_through_the_frozen_ledger() {
        let table = LossTable::generate();
        let source = regime_snippets().remove(0).1;
        let (_, ledger) = encode_h8_item(&source, &table, 0).unwrap();
        let projection = ledger.project_item(source.len() as u64).unwrap();
        assert!(projection.payload_bytes < source.len() as u64);
    }

    #[test]
    fn a_flipped_payload_byte_is_rejected_by_the_tape_digest() {
        let table = LossTable::generate();
        let source = regime_snippets().remove(0).1;
        let (tape, _) = encode_h8_item(&source, &table, 0).unwrap();
        let mut bytes = tape.to_bytes();
        let target = bytes.len() / 2;
        bytes[target] ^= 0x01;
        assert_eq!(Tape::from_bytes(&bytes), Err(TapeError::DigestMismatch));
    }

    #[test]
    fn one_extra_charged_bit_past_end_of_stream_fails_closed() {
        use sha2::{Digest, Sha256};
        let table = LossTable::generate();
        let source = b"{\"a\":1}\n{\"a\":2}\n".to_vec();
        let (tape, ledger) = encode_h8_item(&source, &table, 0).unwrap();
        let bytes = tape.to_bytes();

        const HEADER: usize = 14; // MAGIC(4) + arm(1) + item(1) + bit_count(8)
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
            decode_h8_item(&tampered, ledger, &table, 0),
            Err(H8Error::TrailingChargedData)
        );
    }

    #[test]
    fn known_answer_tape_sha256_is_pinned() {
        use sha2::{Digest, Sha256};
        let table = LossTable::generate();
        let source = b"{\"level\":\"info\",\"msg\":\"ready\",\"n\":1}\n\
                       {\"level\":\"info\",\"msg\":\"ready\",\"n\":2}\n"
            .to_vec();
        let (tape, _) = encode_h8_item(&source, &table, 0).unwrap();
        let sha: String = Sha256::digest(tape.to_bytes())
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect();
        assert_eq!(sha, PINNED_TAPE_SHA256, "pinned tape SHA-256 changed");
    }

    #[test]
    fn weight_file_sha256_and_shape_are_pinned() {
        use sha2::{Digest, Sha256};
        // The embedded artifact parses under the exact pinned dimensions.
        let mixer = StaticMixer::from_embedded().unwrap();
        assert_eq!(mixer.declared_state_bytes(), H8_STATIC_WEIGHT_BYTES);
        assert_eq!(EMBEDDED_WEIGHTS.len(), H8_WEIGHT_FILE_BYTES);
        let sha: String = Sha256::digest(EMBEDDED_WEIGHTS)
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect();
        assert_eq!(sha, H8_WEIGHT_FILE_SHA256, "shipped weight file changed");
    }

    #[test]
    fn a_tampered_weight_file_is_rejected() {
        let mut bytes = EMBEDDED_WEIGHTS.to_vec();
        // Corrupt a weight byte: the SHA pin no longer holds, and if a stale
        // artifact ever changed shape the header check below also fails closed.
        let last = bytes.len() - 1;
        bytes[last] ^= 0xff;
        // The shape still parses (only a weight changed), but it no longer
        // matches the pinned SHA-256 — the guarantee the pin exists to give.
        assert!(parse_weight_file(&bytes).is_ok());
        use sha2::{Digest, Sha256};
        let sha: String = Sha256::digest(&bytes)
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect();
        assert_ne!(sha, H8_WEIGHT_FILE_SHA256);

        // A dimension/magic corruption is rejected by the parser itself.
        let mut bad_magic = EMBEDDED_WEIGHTS.to_vec();
        bad_magic[0] ^= 0x01;
        assert_eq!(
            parse_weight_file(&bad_magic),
            Err(H8Error::WeightFileMalformed)
        );
        let mut truncated = EMBEDDED_WEIGHTS.to_vec();
        truncated.pop();
        assert_eq!(
            parse_weight_file(&truncated),
            Err(H8Error::WeightFileMalformed)
        );
    }

    #[test]
    fn offline_training_is_deterministic_and_round_trips_serialization() {
        let table = LossTable::generate();
        // A small in-memory corpus stands in for the month-A slice: the point
        // is that the procedure is byte-for-byte deterministic, independent of
        // any out-of-tree corpus.
        let mut corpus = Vec::new();
        for index in 0..200_u32 {
            corpus.extend_from_slice(
                format!(
                    "{{\"id\":{},\"type\":\"PushEvent\",\"n\":{}}}\n",
                    1000 + index,
                    index % 13
                )
                .as_bytes(),
            );
        }
        let first = train_static_weights(&corpus, &table);
        let second = train_static_weights(&corpus, &table);
        assert_eq!(first, second, "training is not deterministic");
        assert_eq!(first.len(), H8_STATIC_WEIGHT_COUNT);
        // Serialization round-trips through the committed layout.
        let file = serialize_weight_file(&first);
        assert_eq!(file.len(), H8_WEIGHT_FILE_BYTES);
        let parsed = parse_weight_file(&file).unwrap();
        assert_eq!(parsed.as_slice(), first.as_slice());
        // Training actually moved weights off their initial seed.
        assert_ne!(first, initial_static_weights());
    }

    #[test]
    fn confidence_buckets_are_monotone_and_saturate() {
        assert_eq!(confidence_bucket(0), 0);
        assert_eq!(confidence_bucket(1), 1);
        let mut previous = 0;
        for exponent in 0..20_u32 {
            let bucket = confidence_bucket(1 << exponent);
            assert!(bucket >= previous);
            previous = bucket;
        }
        assert_eq!(confidence_bucket(u32::MAX), H8_CONFIDENCE_BUCKETS - 1);
    }
}
