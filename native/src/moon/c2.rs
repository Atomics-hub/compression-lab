//! C2: structure-conditioned value prediction as pooled mixer inputs.
//!
//! Development-only Cycle 2 arm (Lane 2, the Pareto moonshot). C2 keeps the H1
//! floor arm's byte grammar, its eight shared hashed contexts, its rolling-word
//! accumulator, its continuation-bit counters, and its logistic mixing path
//! **exactly** — it never splits an H1 context and never charges a decision or
//! dictionary bit. On top of that floor it adds four *additional* pooled
//! prediction views, fed through the same log-odds mixer as new inputs:
//!
//! * `field-name-hash x value-byte-order-1`,
//! * `field-name-hash x value-byte-order-2`,
//! * `path-hash x position-within-value`,
//! * a digit-run view (the previous digits of the current numeric run predict
//!   the next digit).
//!
//! The views are computed from a deterministic streaming JSON structure tracker
//! (a light state machine like `diagnose::classify`, **reset at every newline**
//! so a malformed line cannot desync later ones). All four draw their cells from
//! one shared, hashed, bounded pooled table — never per-field lanes. Every view
//! is prediction-only, integer-only, live-adaptive, and decoder-reproducible;
//! when the structure says the next byte is not inside a value the view feeds a
//! neutral probability that the mixer treats as no evidence. C2 is isolated from
//! H1 so the published Cycle-1 floor stays byte-for-byte frozen; its own tape is
//! the literal modeled-bit stream under a disjoint arm id, exact on redecode and
//! fail-closed on corruption, exhaustion, trailing data, and identity mismatch.

use crate::s0::{
    Ledger, LossTable, M5Mixer, Probability, Tape, TapeError, TapeReader, TapeWriter,
    MAX_PROBABILITY, MIN_PROBABILITY,
};
use std::error::Error;
use std::fmt::{Display, Formatter};

use super::table::{ContextTable, H1_CONTEXT_TABLE_BYTES};

/// Tape arm identity for the C2 value-context arm. Disjoint from every other
/// arm id so a tape can never be decoded under the wrong kernel.
pub const C2_ARM_ID: u8 = 106;
/// H1's eight shared hashed contexts, reused unchanged as the mixer's base.
pub const C2_CONTEXT_COUNT: usize = 8;
/// Byte orders of the six direct H1 contexts (identical to H1).
pub const C2_BYTE_ORDERS: [usize; 6] = [1, 2, 3, 4, 6, 8];
/// The four new structure-conditioned pooled views added as mixer inputs.
pub const C2_VALUE_VIEW_COUNT: usize = 4;
/// Non-bias mixer inputs: the eight base contexts plus the four value views.
pub const C2_CONTEXT_INPUTS: usize = C2_CONTEXT_COUNT + C2_VALUE_VIEW_COUNT;
/// Total mixer inputs, including the constant-bias input.
pub const C2_MIXER_INPUTS: usize = C2_CONTEXT_INPUTS + 1;
/// Mixing-context buckets (identical scheme and size to H1's moon mixer).
pub const C2_MIXER_BUCKET_BITS: u32 = 12;
pub const C2_MIXER_BUCKETS: usize = 1 << C2_MIXER_BUCKET_BITS;
/// Declared mutable state of the C2 mixer: one `i32` weight vector per bucket.
pub const C2_MIXER_WEIGHT_BYTES: usize = C2_MIXER_BUCKETS * C2_MIXER_INPUTS * 4;
/// The shared, hashed, bounded pooled table backing all four value views. Same
/// open-addressed counter table H1 uses, at the same 96 MiB capacity.
pub const C2_POOLED_TABLE_BYTES: usize = H1_CONTEXT_TABLE_BYTES;

/// Probability update rate shift for the continuation model (identical to H1's
/// event layer `RATE_SHIFT`; C2 keeps H1's continuation counters exactly).
const C2_RATE_SHIFT: u32 = 5;

// Disjoint FNV-1a namespaces for the base H1 contexts (byte-identical to H1 so
// the base contexts land on the same cells H1 would resolve).
const TAG_ORDER: u8 = 0x01;
const TAG_SPARSE: u8 = 0xa5;
const TAG_WORD: u8 = 0x5a;
const TAG_WORD_ACCUM: u8 = 0x33;

// Disjoint namespaces for the four new pooled value views and the structure
// tracker, so a view never collides with a base context or another view.
const TAG_FIELD_VALUE_O1: u8 = 0xc1;
const TAG_FIELD_VALUE_O2: u8 = 0xc2;
const TAG_PATH_POSITION: u8 = 0xc3;
const TAG_DIGIT_RUN: u8 = 0xc4;
const TAG_OBJECT: u8 = 0xd1;
const TAG_ARRAY: u8 = 0xd2;
const TAG_ARRAY_ELEMENT: u8 = 0xd3;

// Structure-tracker seeds, all nonzero and disjoint.
const PATH_BASE: u64 = 0x9e37_79b9_7f4a_7c15;
const FIELD_BASE: u64 = 0xc2b2_ae3d_27d4_eb4f;
const FIELD_SEED: u64 = 0x1656_67b1_9e37_79f9;
const KEY_SEED: u64 = 0x2545_f491_4f6c_dd1d;
const PATH_SEED: u64 = 0xff51_afd7_ed55_8ccd;
const DIGIT_SEED: u64 = 0xd6e8_feb8_6659_fd93;

/// Neutral probability of a one (one half in Q16). Its stretch is exactly zero,
/// so a gated-off view contributes no evidence and earns no weight gradient.
const NEUTRAL_PROBABILITY: u16 = 1 << 15;

/// Mixer event identity reserved for the per-byte continuation flag; disjoint
/// from every byte-bit identity (which are `< 2^16`).
const CONTINUATION_EVENT_ID: u64 = u64::MAX;

/// Bounded structure-nesting depth. Deeper nesting aliases onto the deepest
/// tracked level; the stack is fixed-size O(1) scratch, never declared state.
const C2_MAX_DEPTH: usize = 64;
/// Position-within-value bucket ceiling (positions saturate here).
const C2_POSITION_CEILING: u32 = 31;

const FNV_OFFSET: u64 = 14_695_981_039_346_656_037;
const FNV_PRIME: u64 = 1_099_511_628_211;

fn fnv1a64(seed: u64, bytes: &[u8]) -> u64 {
    bytes.iter().fold(seed, |hash, byte| {
        (hash ^ u64::from(*byte)).wrapping_mul(FNV_PRIME)
    })
}

fn is_word_byte(byte: u8) -> bool {
    byte.is_ascii_alphanumeric() || byte == b'_'
}

fn is_number_continuation(byte: u8) -> bool {
    byte.is_ascii_digit() || matches!(byte, b'.' | b'e' | b'E' | b'+' | b'-')
}

fn observed_probability(probability_of_one: u16, bit: bool) -> u32 {
    if bit {
        u32::from(probability_of_one)
    } else {
        65_536 - u32::from(probability_of_one)
    }
}

// ---------------------------------------------------------------------------
// Streaming JSON structure tracker.
//
// A bounded, deterministic, integer-only state machine derived from prior bytes
// only. It resets at every newline so a malformed line cannot desync later
// lines. It is fixed-size O(1) scratch (never declared model state), mirroring
// H1's `word`/`last_byte` registers. Its getters describe the *next* byte to be
// coded, so the encoder and decoder — which have identical history — compute
// identical value-view contexts.
// ---------------------------------------------------------------------------

/// A fixed-capacity path stack of container-path hashes and kinds.
#[derive(Clone)]
struct PathStack {
    hashes: [u64; C2_MAX_DEPTH],
    is_object: [bool; C2_MAX_DEPTH],
    depth: usize,
}

impl PathStack {
    fn new() -> Self {
        Self {
            hashes: [0; C2_MAX_DEPTH],
            is_object: [false; C2_MAX_DEPTH],
            depth: 0,
        }
    }

    fn reset(&mut self) {
        self.depth = 0;
    }

    fn top_hash(&self) -> u64 {
        if self.depth == 0 {
            PATH_BASE
        } else {
            self.hashes[(self.depth - 1).min(C2_MAX_DEPTH - 1)]
        }
    }

    fn current_is_object(&self) -> bool {
        if self.depth == 0 {
            false
        } else {
            self.is_object[(self.depth - 1).min(C2_MAX_DEPTH - 1)]
        }
    }

    fn push(&mut self, tag: u8, is_object: bool) {
        let child = fnv1a64(self.top_hash(), &[tag]);
        if self.depth < C2_MAX_DEPTH {
            self.hashes[self.depth] = child;
            self.is_object[self.depth] = is_object;
        }
        self.depth = self.depth.saturating_add(1);
    }

    fn pop(&mut self) {
        self.depth = self.depth.saturating_sub(1);
    }
}

#[derive(Clone)]
struct C2Structure {
    path: PathStack,
    field_hash: u64,
    key_accum: u64,
    expect_key: bool,
    expect_value: bool,
    in_string: bool,
    string_is_key: bool,
    escaped: bool,
    in_number: bool,
    in_literal: bool,
    value_active: bool,
    value_pos: u32,
    value_prev1: u8,
    value_prev2: u8,
    digit_len: u32,
    digit_hash: u64,
}

impl C2Structure {
    fn new() -> Self {
        Self {
            path: PathStack::new(),
            field_hash: FIELD_BASE,
            key_accum: KEY_SEED,
            expect_key: false,
            expect_value: false,
            in_string: false,
            string_is_key: false,
            escaped: false,
            in_number: false,
            in_literal: false,
            value_active: false,
            value_pos: 0,
            value_prev1: 0,
            value_prev2: 0,
            digit_len: 0,
            digit_hash: DIGIT_SEED,
        }
    }

    fn reset_line(&mut self) {
        self.path.reset();
        self.field_hash = FIELD_BASE;
        self.key_accum = KEY_SEED;
        self.expect_key = false;
        self.expect_value = false;
        self.in_string = false;
        self.string_is_key = false;
        self.escaped = false;
        self.in_number = false;
        self.in_literal = false;
        self.end_value();
    }

    fn begin_value(&mut self) {
        self.value_active = true;
        self.value_pos = 0;
        self.value_prev1 = 0;
        self.value_prev2 = 0;
    }

    fn push_value_byte(&mut self, byte: u8) {
        self.value_prev2 = self.value_prev1;
        self.value_prev1 = byte;
        self.value_pos = self.value_pos.saturating_add(1);
    }

    fn end_value(&mut self) {
        self.value_active = false;
        self.value_pos = 0;
        self.value_prev1 = 0;
        self.value_prev2 = 0;
    }

    fn commit_field(&mut self) {
        self.field_hash = fnv1a64(FIELD_SEED, &self.key_accum.to_le_bytes());
    }

    fn string_content_byte(&mut self, byte: u8) {
        if self.string_is_key {
            self.key_accum = fnv1a64(self.key_accum, &[byte]);
        } else {
            self.push_value_byte(byte);
        }
    }

    fn after_container(&mut self) {
        self.expect_key = false;
        self.expect_value = false;
    }

    /// Advance the tracker by one already-known byte, then update the digit run.
    fn advance(&mut self, byte: u8) {
        if self.in_number {
            if is_number_continuation(byte) {
                self.push_value_byte(byte);
                self.finish(byte);
                return;
            }
            self.in_number = false;
            self.end_value();
        }
        if self.in_literal {
            if byte.is_ascii_lowercase() {
                self.push_value_byte(byte);
                self.finish(byte);
                return;
            }
            self.in_literal = false;
            self.end_value();
        }
        if self.in_string {
            if self.escaped {
                self.escaped = false;
                self.string_content_byte(byte);
            } else {
                match byte {
                    b'\\' => {
                        self.escaped = true;
                        self.string_content_byte(byte);
                    }
                    b'"' => {
                        self.in_string = false;
                        if self.string_is_key {
                            self.commit_field();
                        } else {
                            self.end_value();
                        }
                    }
                    _ => self.string_content_byte(byte),
                }
            }
            self.finish(byte);
            return;
        }
        match byte {
            b'\n' => self.reset_line(),
            b' ' | b'\t' | b'\r' => {}
            b'{' => {
                self.path.push(TAG_OBJECT, true);
                self.expect_key = true;
                self.expect_value = false;
            }
            b'[' => {
                self.path.push(TAG_ARRAY, false);
                self.field_hash = fnv1a64(FIELD_SEED, &[TAG_ARRAY_ELEMENT]);
                self.expect_value = true;
            }
            b'}' | b']' => {
                self.path.pop();
                self.after_container();
            }
            b':' => {
                self.expect_key = false;
                self.expect_value = true;
            }
            b',' => {
                if self.path.current_is_object() {
                    self.expect_key = true;
                    self.expect_value = false;
                } else {
                    self.expect_value = true;
                }
            }
            b'"' => {
                self.in_string = true;
                self.string_is_key = self.path.current_is_object() && self.expect_key;
                if self.string_is_key {
                    self.key_accum = KEY_SEED;
                } else {
                    self.begin_value();
                }
                self.expect_value = false;
            }
            b'0'..=b'9' | b'-' => {
                self.in_number = true;
                self.begin_value();
                self.push_value_byte(byte);
                self.expect_value = false;
            }
            b't' | b'f' | b'n' => {
                self.in_literal = true;
                self.begin_value();
                self.push_value_byte(byte);
                self.expect_value = false;
            }
            _ => self.expect_value = false,
        }
        self.finish(byte);
    }

    /// Update the digit-run accumulator with the just-processed byte.
    fn finish(&mut self, byte: u8) {
        if byte.is_ascii_digit() {
            self.digit_len = self.digit_len.saturating_add(1);
            let seed = if self.digit_len == 1 {
                DIGIT_SEED
            } else {
                self.digit_hash
            };
            self.digit_hash = fnv1a64(seed, &[byte]);
        } else {
            self.digit_len = 0;
            self.digit_hash = DIGIT_SEED;
        }
    }

    /// Whether the next byte is expected to lie inside a JSON value span.
    fn next_in_value(&self) -> bool {
        self.in_number
            || self.in_literal
            || (self.in_string && !self.string_is_key)
            || self.expect_value
    }

    fn path_hash(&self) -> u64 {
        let hashed = fnv1a64(PATH_SEED, &self.path.top_hash().to_le_bytes());
        fnv1a64(hashed, &self.field_hash.to_le_bytes())
    }
}

// ---------------------------------------------------------------------------
// C2 logistic mixer.
//
// The identical mixing path H1's inputs use — an N-input integer logistic mixer
// summing predictions in the stretch (log-odds) domain, reconstructed from the
// frozen loss table, with H1's pinned learning rate, weight clamp, and squash —
// widened from H1's nine inputs to thirteen so the four structure-conditioned
// views join the eight base contexts and the bias in one mix. No float, no
// HashMap, fully deterministic.
// ---------------------------------------------------------------------------

const WEIGHT_ONE: i32 = 1 << 16;
const WEIGHT_INIT: i32 = WEIGHT_ONE / C2_MIXER_INPUTS as i32;
const WEIGHT_LIMIT: i32 = 1 << 20;
const LEARN_SHIFT: u32 = 34;
const STRETCH_CLAMP: i64 = 8 << 24;
const BIAS_STRETCH: i64 = 1 << 24;

const _: () = assert!(C2_MIXER_BUCKETS.is_power_of_two());
const _: () = assert!(WEIGHT_INIT > 0);
const _: () = assert!(C2_MIXER_WEIGHT_BYTES == 4096 * 13 * 4);
const _: () = assert!(C2_POOLED_TABLE_BYTES == 96 * 1024 * 1024);

struct MixerScratch {
    base: usize,
    stretches: [i64; C2_MIXER_INPUTS],
    mixed_probability: i32,
}

struct C2Mixer {
    stretch: Box<[i32; 65_536]>,
    weights: Box<[i32]>,
    scratch: Option<MixerScratch>,
}

impl C2Mixer {
    fn new(table: &LossTable) -> Self {
        Self {
            stretch: build_stretch(table),
            weights: vec![WEIGHT_INIT; C2_MIXER_BUCKETS * C2_MIXER_INPUTS].into_boxed_slice(),
            scratch: None,
        }
    }

    #[cfg(test)]
    fn declared_state_bytes(&self) -> usize {
        self.weights.len() * 4
    }

    fn bucket(node: u8, last_byte: u8) -> usize {
        (((node as usize) << 4) ^ (last_byte as usize)) & (C2_MIXER_BUCKETS - 1)
    }

    fn stretch_of(&self, probability_of_one: u16) -> i64 {
        i64::from(self.stretch[usize::from(probability_of_one)])
            .clamp(-STRETCH_CLAMP, STRETCH_CLAMP)
    }

    /// Mix the twelve context inputs plus the constant bias into one probability
    /// of a one. Must be followed by exactly one [`C2Mixer::update`].
    fn predict(&mut self, node: u8, last_byte: u8, inputs: &[u16; C2_CONTEXT_INPUTS]) -> u16 {
        let base = Self::bucket(node, last_byte) * C2_MIXER_INPUTS;
        let mut stretches = [0_i64; C2_MIXER_INPUTS];
        let mut dot = 0_i64;
        for (input, &probability) in inputs.iter().enumerate() {
            let stretch = self.stretch_of(probability);
            stretches[input] = stretch;
            dot += i64::from(self.weights[base + input]) * stretch;
        }
        stretches[C2_CONTEXT_INPUTS] = BIAS_STRETCH;
        dot += i64::from(self.weights[base + C2_CONTEXT_INPUTS]) * BIAS_STRETCH;

        let mixed_q24 = (dot >> 16).clamp(-STRETCH_CLAMP, STRETCH_CLAMP);
        let mixed_probability = self.squash(mixed_q24);
        self.scratch = Some(MixerScratch {
            base,
            stretches,
            mixed_probability,
        });
        (mixed_probability as u32).clamp(u32::from(MIN_PROBABILITY), u32::from(MAX_PROBABILITY))
            as u16
    }

    fn update(&mut self, bit: bool) {
        let Some(scratch) = self.scratch.take() else {
            debug_assert!(false, "C2 mixer update without a preceding predict");
            return;
        };
        let error = i64::from(if bit { 65_536 } else { 0 } - scratch.mixed_probability);
        for input in 0..C2_MIXER_INPUTS {
            let delta = ((error * scratch.stretches[input]) >> LEARN_SHIFT) as i32;
            let weight = &mut self.weights[scratch.base + input];
            *weight = (*weight + delta).clamp(-WEIGHT_LIMIT, WEIGHT_LIMIT);
        }
    }

    fn squash(&self, target: i64) -> i32 {
        let mut low = 1_u32;
        let mut high = 65_535_u32;
        while low < high {
            let middle = (low + high) / 2;
            if i64::from(self.stretch[middle as usize]) >= target {
                high = middle;
            } else {
                low = middle + 1;
            }
        }
        low as i32
    }
}

/// `stretch(p) = log2(p / (65536 - p))` in Q24, reconstructed exactly from the
/// frozen loss table (identical to the H1 moon mixer's local reconstruction).
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

/// Declared model-state bytes for a C2 model: H1's 96 MiB base context table,
/// the shared 96 MiB pooled value-view table, the C2 mixer weight table, and the
/// frozen s0 mixer and SSE tables. Scratch registers (the continuation model,
/// the rolling word hash, the fixed-size structure tracker) and derived constant
/// lookups (the stretch table) are excluded, mirroring H1's convention.
#[must_use]
pub fn c2_declared_state_bytes(table: &LossTable, sse_bucket_bits: u32) -> usize {
    let (mixer_bytes, sse_bytes) =
        M5Mixer::with_sse_bucket_bits(table, sse_bucket_bits).declared_state_bytes();
    H1_CONTEXT_TABLE_BYTES + C2_POOLED_TABLE_BYTES + C2_MIXER_WEIGHT_BYTES + mixer_bytes + sse_bytes
}

struct C2Model {
    contexts: ContextTable,
    pooled: ContextTable,
    mixer: C2Mixer,
    recalibrate: Box<M5Mixer>,
    continuation: Probability,
    structure: C2Structure,
    word: u64,
    last_byte: u8,
}

impl C2Model {
    fn new(table: &LossTable, sse_bucket_bits: u32) -> Self {
        Self {
            contexts: ContextTable::new(),
            pooled: ContextTable::new(),
            mixer: C2Mixer::new(table),
            recalibrate: Box::new(M5Mixer::with_sse_bucket_bits(table, sse_bucket_bits)),
            continuation: Probability::default(),
            structure: C2Structure::new(),
            word: 0,
            last_byte: 0,
        }
    }

    /// H1's eight context hashes for one bit, byte-identical to the floor arm.
    fn base_context_hashes(&self, history: &[u8], node: u8) -> [u64; C2_CONTEXT_COUNT] {
        let mut hashes = [0_u64; C2_CONTEXT_COUNT];
        let position = history.len();
        for (slot, &order) in C2_BYTE_ORDERS.iter().enumerate() {
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

    fn resolve_base(
        &mut self,
        history: &[u8],
        node: u8,
    ) -> ([usize; C2_CONTEXT_COUNT], [u16; C2_CONTEXT_COUNT]) {
        let hashes = self.base_context_hashes(history, node);
        let mut indices = [0_usize; C2_CONTEXT_COUNT];
        let mut probabilities = [0_u16; C2_CONTEXT_COUNT];
        for (slot, &hash) in hashes.iter().enumerate() {
            let index = self.contexts.resolve(hash);
            indices[slot] = index;
            probabilities[slot] = self.contexts.cell(index).probability_of_one();
        }
        (indices, probabilities)
    }

    /// Resolve the four structure-conditioned views from the shared pooled
    /// table for one bit. A view that the structure gates off resolves no cell
    /// and feeds the neutral probability, which the mixer treats as no evidence.
    fn resolve_views(
        &mut self,
        node: u8,
    ) -> (
        [Option<usize>; C2_VALUE_VIEW_COUNT],
        [u16; C2_VALUE_VIEW_COUNT],
    ) {
        let in_value = self.structure.next_in_value();
        let field = self.structure.field_hash;
        let path = self.structure.path_hash();
        let prev1 = self.structure.value_prev1;
        let prev2 = self.structure.value_prev2;
        let position = self.structure.value_pos.min(C2_POSITION_CEILING) as u8;
        let digit_active = self.structure.digit_len > 0;
        let digit_hash = self.structure.digit_hash;

        let mut indices = [None; C2_VALUE_VIEW_COUNT];
        let mut probabilities = [NEUTRAL_PROBABILITY; C2_VALUE_VIEW_COUNT];

        if in_value {
            let field_value_o1 = view_hash(TAG_FIELD_VALUE_O1, field, &[prev1, node]);
            let field_value_o2 = view_hash(TAG_FIELD_VALUE_O2, field, &[prev1, prev2, node]);
            let path_position = view_hash(TAG_PATH_POSITION, path, &[position, node]);
            for (slot, hash) in [field_value_o1, field_value_o2, path_position]
                .into_iter()
                .enumerate()
            {
                let index = self.pooled.resolve(hash);
                indices[slot] = Some(index);
                probabilities[slot] = self.pooled.cell(index).probability_of_one();
            }
        }
        if digit_active {
            let combined = fnv1a64(
                fnv1a64(FNV_OFFSET, &field.to_le_bytes()),
                &digit_hash.to_le_bytes(),
            );
            let digit_run = view_hash(TAG_DIGIT_RUN, combined, &[node]);
            let index = self.pooled.resolve(digit_run);
            indices[3] = Some(index);
            probabilities[3] = self.pooled.cell(index).probability_of_one();
        }
        (indices, probabilities)
    }

    fn event_id(&self, node: u8) -> u64 {
        (u64::from(self.last_byte) << 8) | u64::from(node)
    }

    /// The shared prediction step for one modeled byte-bit: the C2 logistic
    /// mixer combines the twelve context inputs into a base, which the frozen s0
    /// mixer recalibrates. Independent of the bit value, so the decoder
    /// reproduces the identical charged probability.
    fn predict_byte_bit(
        &mut self,
        base_probabilities: &[u16; C2_CONTEXT_COUNT],
        view_probabilities: &[u16; C2_VALUE_VIEW_COUNT],
        node: u8,
        event_id: u64,
    ) -> u16 {
        let mut inputs = [0_u16; C2_CONTEXT_INPUTS];
        inputs[..C2_CONTEXT_COUNT].copy_from_slice(base_probabilities);
        inputs[C2_CONTEXT_COUNT..].copy_from_slice(view_probabilities);
        let last_byte = self.last_byte;
        let mixed = self.mixer.predict(node, last_byte, &inputs);
        self.recalibrate.predict(event_id, mixed)
    }

    /// Paired updates for one modeled byte-bit, preserving charge-before-update.
    fn update_byte_bit(
        &mut self,
        base_indices: &[usize; C2_CONTEXT_COUNT],
        view_indices: &[Option<usize>; C2_VALUE_VIEW_COUNT],
        bit: bool,
    ) {
        self.recalibrate.update(bit);
        self.mixer.update(bit);
        for &index in base_indices {
            self.contexts.observe(index, bit);
        }
        for index in view_indices.iter().flatten() {
            self.pooled.observe(*index, bit);
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
        self.structure.advance(byte);
    }

    fn encode_byte(
        &mut self,
        byte: u8,
        history: &[u8],
        table: &LossTable,
        ledger: &mut Ledger,
        writer: &mut TapeWriter,
    ) -> Result<(), C2Error> {
        let mut node: u32 = 1;
        for shift in (0..8_u32).rev() {
            let bit = (byte >> shift) & 1 == 1;
            let (base_indices, base_probs) = self.resolve_base(history, node as u8);
            let (view_indices, view_probs) = self.resolve_views(node as u8);
            let event_id = self.event_id(node as u8);
            let charged = self.predict_byte_bit(&base_probs, &view_probs, node as u8, event_id);
            charge(charged, bit, table, ledger)?;
            writer.push_bit(bit)?;
            self.update_byte_bit(&base_indices, &view_indices, bit);
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
    ) -> Result<u8, C2Error> {
        let mut node: u32 = 1;
        for _ in 0..8 {
            let bit = reader.read_bit()?;
            let (base_indices, base_probs) = self.resolve_base(history, node as u8);
            let (view_indices, view_probs) = self.resolve_views(node as u8);
            let event_id = self.event_id(node as u8);
            let charged = self.predict_byte_bit(&base_probs, &view_probs, node as u8, event_id);
            charge(charged, bit, table, ledger)?;
            self.update_byte_bit(&base_indices, &view_indices, bit);
            node = (node << 1) | u32::from(bit);
        }
        let byte = (node & 0xff) as u8;
        self.advance_byte(byte);
        Ok(byte)
    }

    /// Charge one continuation bit exactly as H1 does: through the frozen s0
    /// mixer keyed by the continuation identity against the H1 continuation
    /// counter. C2 keeps H1's continuation counters byte-for-byte.
    fn encode_continuation(
        &mut self,
        more: bool,
        table: &LossTable,
        ledger: &mut Ledger,
        writer: &mut TapeWriter,
    ) -> Result<(), C2Error> {
        let base = self.continuation.probability_of_one();
        let charged = self.recalibrate.predict(CONTINUATION_EVENT_ID, base);
        charge(charged, more, table, ledger)?;
        writer.push_bit(more)?;
        self.recalibrate.update(more);
        self.continuation.update(more, C2_RATE_SHIFT);
        Ok(())
    }

    fn decode_continuation(
        &mut self,
        table: &LossTable,
        ledger: &mut Ledger,
        reader: &mut TapeReader<'_>,
    ) -> Result<bool, C2Error> {
        let more = reader.read_bit()?;
        let base = self.continuation.probability_of_one();
        let charged = self.recalibrate.predict(CONTINUATION_EVENT_ID, base);
        charge(charged, more, table, ledger)?;
        self.recalibrate.update(more);
        self.continuation.update(more, C2_RATE_SHIFT);
        Ok(more)
    }
}

fn view_hash(tag: u8, primary: u64, trailer: &[u8]) -> u64 {
    let mut hash = fnv1a64(FNV_OFFSET, &[tag]);
    hash = fnv1a64(hash, &primary.to_le_bytes());
    fnv1a64(hash, trailer)
}

fn charge(
    probability: u16,
    bit: bool,
    table: &LossTable,
    ledger: &mut Ledger,
) -> Result<(), C2Error> {
    let loss = table
        .get(observed_probability(probability, bit))
        .ok_or(C2Error::InvalidProbability)?;
    ledger
        .add_modeled_event(loss)
        .ok_or(C2Error::LedgerOverflow)?;
    Ok(())
}

/// Encode one item under the C2 arm at the base SSE capacity.
pub fn encode_c2_item(
    source: &[u8],
    table: &LossTable,
    item_index: u8,
) -> Result<(Tape, Ledger), C2Error> {
    encode_c2_item_with_bits(source, table, item_index, crate::s0::SSE_BASE_BUCKET_BITS)
}

/// Encode one item under the C2 arm at an explicit SSE capacity.
pub fn encode_c2_item_with_bits(
    source: &[u8],
    table: &LossTable,
    item_index: u8,
    sse_bucket_bits: u32,
) -> Result<(Tape, Ledger), C2Error> {
    let mut model = C2Model::new(table, sse_bucket_bits);
    let mut writer = TapeWriter::new(C2_ARM_ID, item_index);
    let mut ledger = Ledger::default();
    for (position, &byte) in source.iter().enumerate() {
        model.encode_continuation(true, table, &mut ledger, &mut writer)?;
        model.encode_byte(byte, &source[..position], table, &mut ledger, &mut writer)?;
        if byte == b'\n' {
            ledger.add_record().ok_or(C2Error::LedgerOverflow)?;
        }
    }
    model.encode_continuation(false, table, &mut ledger, &mut writer)?;
    Ok((writer.finish(), ledger))
}

/// Decode one item under the C2 arm at the base SSE capacity.
pub fn decode_c2_item(
    tape: &Tape,
    expected_ledger: Ledger,
    table: &LossTable,
    expected_item_index: u8,
) -> Result<Vec<u8>, C2Error> {
    decode_c2_item_with_bits(
        tape,
        expected_ledger,
        table,
        expected_item_index,
        crate::s0::SSE_BASE_BUCKET_BITS,
    )
}

/// Decode one item under the C2 arm at an explicit SSE capacity, checking arm
/// and item identity and independent ledger equality.
pub fn decode_c2_item_with_bits(
    tape: &Tape,
    expected_ledger: Ledger,
    table: &LossTable,
    expected_item_index: u8,
    sse_bucket_bits: u32,
) -> Result<Vec<u8>, C2Error> {
    if tape.arm_id() != C2_ARM_ID || tape.item_index() != expected_item_index {
        return Err(C2Error::TapeIdentityMismatch);
    }
    let mut model = C2Model::new(table, sse_bucket_bits);
    let mut ledger = Ledger::default();
    let mut reader = tape.reader();
    let mut output: Vec<u8> = Vec::new();
    loop {
        if !model.decode_continuation(table, &mut ledger, &mut reader)? {
            break;
        }
        let byte = model.decode_byte(&output, table, &mut ledger, &mut reader)?;
        output.push(byte);
        if byte == b'\n' {
            ledger.add_record().ok_or(C2Error::LedgerOverflow)?;
        }
    }
    if !reader.is_finished() {
        return Err(C2Error::TrailingChargedData);
    }
    if ledger != expected_ledger {
        return Err(C2Error::LedgerDivergence {
            encoder: expected_ledger,
            decoder: ledger,
        });
    }
    Ok(output)
}

/// C2 encode/decode error. Every variant is terminal for the item; the caller
/// discards partially charged state.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum C2Error {
    InvalidProbability,
    LedgerOverflow,
    TapeIdentityMismatch,
    TrailingChargedData,
    LedgerDivergence { encoder: Ledger, decoder: Ledger },
    Tape(TapeError),
}

impl From<TapeError> for C2Error {
    fn from(error: TapeError) -> Self {
        Self::Tape(error)
    }
}

impl Display for C2Error {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "moon C2 error: {self:?}")
    }
}

impl Error for C2Error {}

#[cfg(test)]
mod tests {
    use super::*;

    // Pinned once from the deterministic encoder; the tape is the literal
    // modeled-bit stream, a pure function of the source bytes and arm/item
    // identity, so this SHA is stable across mixer and view changes.
    const PINNED_TAPE_SHA256: &str =
        "0e776257a835568539ded650c4f7c2f067db4a02094d035a4a15b849d996e346";

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
        snippets.push((
            "nested",
            b"{\"a\":{\"b\":[1,2,3],\"c\":\"deadbeef00\"},\"d\":true}\n".to_vec(),
        ));

        snippets
    }

    #[test]
    fn round_trips_exactly_across_every_regime() {
        let table = LossTable::generate();
        for (name, source) in regime_snippets() {
            let (tape, ledger) = encode_c2_item(&source, &table, 1).unwrap();
            let decoded = decode_c2_item(&tape, ledger, &table, 1).unwrap();
            assert_eq!(decoded, source, "regime {name} did not round-trip");
            // No decision bits and no charged dictionary state: C2 charges zero
            // literals, exactly like the H1 floor.
            assert_eq!(ledger.raw_literal_bytes, 0, "C2 charges no literals");
        }
    }

    #[test]
    fn repeat_runs_are_byte_identical_in_tape_and_ledger() {
        let table = LossTable::generate();
        let source = regime_snippets().remove(1).1;
        let (tape_a, ledger_a) = encode_c2_item(&source, &table, 2).unwrap();
        let (tape_b, ledger_b) = encode_c2_item(&source, &table, 2).unwrap();
        assert_eq!(tape_a.to_bytes(), tape_b.to_bytes());
        assert_eq!(ledger_a, ledger_b);
    }

    #[test]
    fn decode_fails_closed_on_a_tampered_ledger() {
        let table = LossTable::generate();
        let source = b"{\"a\":1}\n{\"a\":2}\n{\"a\":1}\n".to_vec();
        let (tape, ledger) = encode_c2_item(&source, &table, 0).unwrap();
        let mut wrong = ledger;
        wrong.modeled_loss_q24 += 1;
        assert!(matches!(
            decode_c2_item(&tape, wrong, &table, 0),
            Err(C2Error::LedgerDivergence { .. })
        ));
    }

    #[test]
    fn decode_rejects_a_foreign_arm_or_item_identity() {
        let table = LossTable::generate();
        let source = b"hello world\n".to_vec();
        let (tape, ledger) = encode_c2_item(&source, &table, 3).unwrap();
        assert_eq!(
            decode_c2_item(&tape, ledger, &table, 4),
            Err(C2Error::TapeIdentityMismatch)
        );
    }

    #[test]
    fn a_flipped_payload_byte_is_rejected_by_the_tape_digest() {
        let table = LossTable::generate();
        let source = regime_snippets().remove(0).1;
        let (tape, _) = encode_c2_item(&source, &table, 0).unwrap();
        let mut bytes = tape.to_bytes();
        let target = bytes.len() / 2;
        bytes[target] ^= 0x01;
        assert_eq!(Tape::from_bytes(&bytes), Err(TapeError::DigestMismatch));
    }

    #[test]
    fn a_truncated_tape_fails_closed() {
        let table = LossTable::generate();
        let source = regime_snippets().remove(1).1;
        let (tape, _) = encode_c2_item(&source, &table, 0).unwrap();
        let bytes = tape.to_bytes();
        // Drop the final byte: the digest no longer covers the payload.
        let truncated = &bytes[..bytes.len() - 1];
        assert!(Tape::from_bytes(truncated).is_err());
    }

    #[test]
    fn one_extra_charged_bit_past_end_of_stream_fails_closed() {
        use sha2::{Digest, Sha256};
        let table = LossTable::generate();
        let source = b"{\"a\":1}\n{\"a\":2}\n".to_vec();
        let (tape, ledger) = encode_c2_item(&source, &table, 0).unwrap();
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
            decode_c2_item(&tampered, ledger, &table, 0),
            Err(C2Error::TrailingChargedData)
        );
    }

    #[test]
    fn declared_state_accounts_for_both_tables_the_mixer_and_sse() {
        let table = LossTable::generate();
        let (mixer_bytes, sse_bytes) = M5Mixer::new(&table).declared_state_bytes();
        let standalone = c2_declared_state_bytes(&table, crate::s0::SSE_BASE_BUCKET_BITS);
        assert_eq!(
            standalone,
            H1_CONTEXT_TABLE_BYTES
                + C2_POOLED_TABLE_BYTES
                + C2_MIXER_WEIGHT_BYTES
                + mixer_bytes
                + sse_bytes
        );
        // Regression pin of the exact figure the receipts report, and the <=256
        // MiB declared-state ceiling the charter binds.
        assert_eq!(standalone, 220_676_096);
        assert!(standalone <= 256 * 1024 * 1024);
        // The C2 mixer widens H1's nine inputs to thirteen.
        assert_eq!(C2_MIXER_INPUTS, 13);
        assert_eq!(C2_MIXER_WEIGHT_BYTES, 212_992);
        // The mixer instance's own accounting agrees with the declared constant.
        assert_eq!(
            C2Mixer::new(&table).declared_state_bytes(),
            C2_MIXER_WEIGHT_BYTES
        );
        // The refined SSE capacity only grows the SSE table.
        let refined = c2_declared_state_bytes(&table, crate::s0::SSE_REFINED_BUCKET_BITS);
        assert!(refined > standalone);
    }

    #[test]
    fn known_answer_tape_sha256_is_pinned() {
        use sha2::{Digest, Sha256};
        let table = LossTable::generate();
        let source = b"{\"level\":\"info\",\"msg\":\"ready\",\"n\":1}\n\
                       {\"level\":\"info\",\"msg\":\"ready\",\"n\":2}\n"
            .to_vec();
        let (tape, _) = encode_c2_item(&source, &table, 0).unwrap();
        let sha: String = Sha256::digest(tape.to_bytes())
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect();
        assert_eq!(sha, PINNED_TAPE_SHA256, "pinned C2 tape SHA-256 changed");
    }

    #[test]
    fn structure_tracker_resets_on_newline_and_is_deterministic() {
        // A malformed first line must not desync the well-formed second line.
        let mut first = C2Structure::new();
        let mut second = C2Structure::new();
        for &byte in b"{\"a\":\n" {
            first.advance(byte);
        }
        // The second tracker starts fresh at the line boundary the first reached.
        for &byte in b"{\"b\":\"c\"}\n" {
            first.advance(byte);
            second.advance(byte);
        }
        assert_eq!(first.field_hash, second.field_hash);
        assert_eq!(first.path.depth, second.path.depth);
        assert_eq!(first.digit_hash, second.digit_hash);
    }

    #[test]
    fn structure_tracker_marks_value_bytes_and_digit_runs() {
        let mut structure = C2Structure::new();
        // Walk to just before the '1' value byte of {"id":123}.
        for &byte in b"{\"id\":" {
            structure.advance(byte);
        }
        // After the colon the next byte is expected inside a value.
        assert!(structure.next_in_value());
        structure.advance(b'1');
        // A digit run is now active and predicts the next digit.
        assert!(structure.digit_len > 0);
        assert!(structure.next_in_value());
    }

    #[test]
    fn gated_views_are_neutral_and_carry_no_evidence() {
        // A neutral view probability squashes to a zero stretch, so it moves
        // neither the mix nor its weight.
        let table = LossTable::generate();
        let mixer = C2Mixer::new(&table);
        assert_eq!(mixer.stretch[usize::from(NEUTRAL_PROBABILITY)], 0);
    }

    #[test]
    fn refined_sse_bits_hold_the_tape_and_event_stream() {
        let table = LossTable::generate();
        let source = regime_snippets().remove(2).1;
        let (base_tape, base_ledger) = encode_c2_item_with_bits(&source, &table, 0, 17).unwrap();
        let (refined_tape, refined_ledger) =
            encode_c2_item_with_bits(&source, &table, 0, 18).unwrap();
        assert_eq!(base_tape.to_bytes(), refined_tape.to_bytes());
        assert_eq!(
            base_ledger.modeled_binary_events,
            refined_ledger.modeled_binary_events
        );
        assert_eq!(base_ledger.records, refined_ledger.records);
        assert_eq!(
            decode_c2_item_with_bits(&refined_tape, refined_ledger, &table, 0, 18).unwrap(),
            source
        );
    }
}
