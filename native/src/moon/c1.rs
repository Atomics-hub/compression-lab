//! C1: byte match model folded into the H1 floor as one extra mixer input.
//!
//! Development-only Cycle 2 arm (Lane 2, the Pareto moonshot). C1 keeps H1's
//! byte grammar, its eight hashed contexts, and the moon logistic
//! [`MoonMixer`] **verbatim**: the eight context cells still combine into a
//! single `base` prediction exactly as the H1 floor does. C1 then adds a
//! deterministic, bounded, byte-verified **match model** — a hash of the last
//! [`MATCH_MIN_LENGTH`] bytes to the most-recent prior occurrence, predicting
//! the next byte's bits with confidence that grows in verified match length —
//! and folds that single prediction into the coding path as **one additional
//! input** through a small log-odds [`MatchMixer`] that combines the moon
//! `base` with the match prediction the same way H1's inputs already combine
//! (stretch/squash domain, pinned constants), before the frozen s0
//! [`M5Mixer`] recalibrates. There are no decision bits and no charged
//! references: the match is prediction-only, so a wrong guess only costs the
//! coder the residual it always pays, never a structural penalty.
//!
//! All state is fixed-size and integer, every predictive path is array-indexed
//! (no `HashMap`), and the encoder and decoder walk byte-for-byte identically,
//! so tapes are cross-process deterministic. Encode immediately re-decodes and
//! checks ledger equality; decode is fail-closed on corruption, exhaustion,
//! identity mismatch, and trailing charged data. C1 is deliberately isolated
//! from H1 so the published Cycle 1 floor stays byte-for-byte frozen.

use crate::s0::{
    Ledger, LossTable, M5Mixer, Probability, Tape, TapeError, TapeReader, TapeWriter,
    MAX_PROBABILITY, MIN_PROBABILITY,
};
use std::error::Error;
use std::fmt::{Display, Formatter};

use super::mixer::{MoonMixer, MOON_MIXER_WEIGHT_BYTES};
use super::table::{ContextTable, H1_CONTEXT_TABLE_BYTES};

/// Tape arm identity for the C1 match-model arm. Disjoint from every other arm
/// id so a tape can never be decoded under the wrong kernel.
pub const C1_ARM_ID: u8 = 105;
/// Number of hashed contexts combined per modeled bit (identical to H1).
pub const C1_CONTEXT_COUNT: usize = 8;
/// Byte orders of the six direct contexts (identical to H1).
pub const C1_BYTE_ORDERS: [usize; 6] = [1, 2, 3, 4, 6, 8];
/// Probability update rate shift for the continuation model (matches H1).
const C1_RATE_SHIFT: u32 = 5;

// --- Match model bounds ---------------------------------------------------

/// Context length (bytes) hashed to index prior occurrences, and the verified
/// match length a fresh acquisition starts at. Chosen at 6: short enough that a
/// candidate is available and byte-verified before we are well inside a
/// length-`>= 8` repeat (the repeat mass the loss decomposition measured), and
/// long enough (48 bits keyed into 2^22 buckets) that spurious hash hits are
/// rare. A hash hit alone never asserts a match; the six bytes are always
/// byte-verified before use.
pub const MATCH_MIN_LENGTH: usize = 6;
/// Base-2 log of the match hash table size.
pub const MATCH_HASH_BITS: u32 = 22;
/// Match hash table entries (2^22). Each stores one absolute u32 position with
/// an overwrite-most-recent collision policy.
pub const MATCH_TABLE_ENTRIES: usize = 1 << MATCH_HASH_BITS;
/// Declared match hash table bytes (2^22 * 4 = 16 MiB).
pub const MATCH_TABLE_BYTES: usize = MATCH_TABLE_ENTRIES * 4;
/// Explicit back-reference window (bytes). Set to 32 MiB: larger than any
/// bounded public item (24 MiB), so no in-item repeat is dropped while the
/// window stays a finite, declared, deterministic bound. The already-resident
/// source/output buffer is the window store, so this bound costs no model
/// state beyond the hash table; a candidate farther back than this is ignored.
pub const MATCH_WINDOW_BYTES: usize = 1 << 25;
/// Number of verified-length buckets for the adaptive hit-probability map.
pub const MATCH_LEN_BUCKETS: usize = 64;
/// Declared adaptive hit-probability map bytes (64 * 2).
pub const MATCH_STATEMAP_BYTES: usize = MATCH_LEN_BUCKETS * 2;
/// Empty-slot sentinel for the position table (no item reaches u32::MAX bytes).
const NO_POS: u32 = u32::MAX;
/// EWMA rate shift for the adaptive per-length hit probability.
const MATCH_HIT_RATE_SHIFT: u32 = 5;
/// Per-length-bucket confidence prior slope (Q16). The prior rises with the
/// verified match length so a long match speaks confidently from its first
/// coded byte; the map still adapts around it.
const MATCH_PRIOR_STEP: i32 = 400;

// --- Match fold mixer bounds ----------------------------------------------

/// Mixing-context buckets for the match fold (reuses the moon bucketing width).
pub const FOLD_BUCKET_BITS: u32 = 12;
pub const FOLD_BUCKETS: usize = 1 << FOLD_BUCKET_BITS;
/// Fold inputs: the moon `base`, the match prediction, and a constant bias.
pub const FOLD_INPUTS: usize = 3;
/// Declared fold weight table bytes (4096 * 3 * 4).
pub const FOLD_WEIGHT_BYTES: usize = FOLD_BUCKETS * FOLD_INPUTS * 4;

// Fold arithmetic constants — identical family to the moon mixer, so the match
// prediction is folded exactly the way H1's inputs already combine.
const FOLD_WEIGHT_ONE: i32 = 1 << 16;
const FOLD_WEIGHT_LIMIT: i32 = 1 << 20;
const FOLD_LEARN_SHIFT: u32 = 34;
const FOLD_STRETCH_CLAMP: i64 = 8 << 24;
const FOLD_BIAS_STRETCH: i64 = 1 << 24;

// Disjoint FNV-1a namespaces per context kind (identical to H1).
const TAG_ORDER: u8 = 0x01;
const TAG_SPARSE: u8 = 0xa5;
const TAG_WORD: u8 = 0x5a;
const TAG_WORD_ACCUM: u8 = 0x33;
/// FNV namespace for the match k-gram hash, disjoint from the context tags.
const TAG_MATCH: u8 = 0xc1;

const CONTINUATION_EVENT_ID: u64 = u64::MAX;

const FNV_OFFSET: u64 = 14_695_981_039_346_656_037;
const FNV_PRIME: u64 = 1_099_511_628_211;

const _: () = assert!(MATCH_TABLE_ENTRIES.is_power_of_two());
const _: () = assert!(MATCH_TABLE_BYTES == 16 * 1024 * 1024);
const _: () = assert!(FOLD_BUCKETS.is_power_of_two());
const _: () = assert!(FOLD_WEIGHT_BYTES == 4096 * 3 * 4);
const _: () = assert!(MATCH_MIN_LENGTH >= 1);

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

/// `stretch(p) = log2(p / (65536 - p))` in Q24, derived exactly from the frozen
/// loss table (the same reconstruction the moon mixer uses). A derived constant
/// table, not charged model state — mirroring the moon-mixer convention.
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

// ---------------------------------------------------------------------------
// Match model
// ---------------------------------------------------------------------------

/// One live-match prediction for the current bit.
#[derive(Clone, Copy)]
struct MatchBit {
    /// Whether a live, byte-verified match predicts this bit (the bits coded so
    /// far in the current byte still agree with the predicted byte).
    valid: bool,
    /// The predicted bit value (meaningful only when `valid`).
    predicted_bit: bool,
    /// Probability-of-one to fold in (neutral `1 << 15` when not `valid`).
    probability: u16,
}

/// Deterministic bounded match model. It maps the hash of the last
/// [`MATCH_MIN_LENGTH`] bytes to the most-recent prior occurrence, byte-verifies
/// before trusting it, follows the matched region while it holds, and predicts
/// each next bit with an adaptive confidence keyed by verified match length.
///
/// All predictive reads are array indices; there is no `HashMap` on any path,
/// so encode and decode are cross-process identical.
struct MatchModel {
    /// Hash table: k-gram hash -> position of the byte that followed that
    /// k-gram. Overwrite-most-recent. `NO_POS` marks an empty slot.
    table: Box<[u32]>,
    /// Adaptive P(next bit equals the predicted bit) per verified-length bucket.
    hit_probability: [u16; MATCH_LEN_BUCKETS],
    /// Index in history whose byte predicts the current byte (valid iff
    /// `match_len > 0`).
    match_pos: usize,
    /// Verified match length in bytes (0 = no live match).
    match_len: usize,
    /// Per-byte snapshot: is a live match predicting the current byte?
    live: bool,
    /// Per-byte snapshot: the predicted byte value.
    predicted_byte: u8,
    /// Per-byte snapshot: the verified-length bucket for the current byte.
    len_bucket: usize,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
struct MatchAdvanceTrace {
    empty_slot: bool,
    prefix_verification_failed: bool,
    window_expired: bool,
    live_suppressed_acquisition: bool,
    acquired: bool,
}

impl MatchModel {
    fn new() -> Self {
        let mut hit_probability = [1_u16 << 15; MATCH_LEN_BUCKETS];
        for (bucket, slot) in hit_probability.iter_mut().enumerate() {
            let prior = (1_i32 << 15) + bucket as i32 * MATCH_PRIOR_STEP;
            *slot = prior.clamp(i32::from(MIN_PROBABILITY), i32::from(MAX_PROBABILITY)) as u16;
        }
        Self {
            table: vec![NO_POS; MATCH_TABLE_ENTRIES].into_boxed_slice(),
            hit_probability,
            match_pos: 0,
            match_len: 0,
            live: false,
            predicted_byte: 0,
            len_bucket: 0,
        }
    }

    #[cfg(test)]
    #[must_use]
    fn declared_state_bytes(&self) -> usize {
        self.table.len() * 4 + MATCH_STATEMAP_BYTES
    }

    fn key(bytes: &[u8]) -> usize {
        (fnv1a64(fnv1a64(FNV_OFFSET, &[TAG_MATCH]), bytes) as usize) & (MATCH_TABLE_ENTRIES - 1)
    }

    fn bucket(match_len: usize) -> usize {
        match_len.min(MATCH_LEN_BUCKETS - 1)
    }

    /// Snapshot the live-match state for the byte about to be coded at `pos`
    /// (history is `&buffer[..pos]`). Reads only prior bytes.
    fn begin_byte(&mut self, history: &[u8], pos: usize) {
        self.live = self.match_len > 0
            && self.match_pos < pos
            && pos - self.match_pos <= MATCH_WINDOW_BYTES;
        self.predicted_byte = if self.live {
            history[self.match_pos]
        } else {
            0
        };
        self.len_bucket = Self::bucket(self.match_len);
    }

    /// Predict the bit at tree node `node` (bit index `bit_index`, source shift
    /// `shift`). The match speaks only while the bits coded so far still agree
    /// with the predicted byte's high bits; otherwise it stays neutral.
    fn predict_bit(&self, node: u32, shift: u32, bit_index: u32) -> MatchBit {
        if !self.live {
            return MatchBit {
                valid: false,
                predicted_bit: false,
                probability: 1 << 15,
            };
        }
        let predicted = u32::from(self.predicted_byte);
        let expected_node = (1_u32 << bit_index) | (predicted >> (shift + 1));
        if node != expected_node {
            return MatchBit {
                valid: false,
                predicted_bit: false,
                probability: 1 << 15,
            };
        }
        let predicted_bit = (predicted >> shift) & 1 == 1;
        let hit = u32::from(self.hit_probability[self.len_bucket]);
        let probability_of_one = if predicted_bit { hit } else { 65_536 - hit };
        MatchBit {
            valid: true,
            predicted_bit,
            probability: probability_of_one
                .clamp(u32::from(MIN_PROBABILITY), u32::from(MAX_PROBABILITY))
                as u16,
        }
    }

    /// Learn the per-length hit probability after the bit is known. Only a bit
    /// the match actually predicted updates the map.
    fn update_bit(&mut self, prediction: MatchBit, bit: bool) {
        if !prediction.valid {
            return;
        }
        let target = if bit == prediction.predicted_bit {
            65_536
        } else {
            0
        };
        let current = i32::from(self.hit_probability[self.len_bucket]);
        let next = current + ((target - current) >> MATCH_HIT_RATE_SHIFT);
        self.hit_probability[self.len_bucket] =
            next.clamp(i32::from(MIN_PROBABILITY), i32::from(MAX_PROBABILITY)) as u16;
    }

    /// Advance the match state one byte. `history` is `&buffer[..=pos]` (it
    /// includes the byte just coded at `pos`). Continues or breaks the live
    /// match, updates the hash table (overwrite-most-recent), and — only when no
    /// match is live — byte-verifies and acquires a fresh candidate.
    fn advance(&mut self, history: &[u8]) {
        let _ = self.advance_traced(history);
    }

    /// Identical state transition to [`Self::advance`], with a read-only
    /// disposition describing why a fresh acquisition did or did not occur.
    fn advance_traced(&mut self, history: &[u8]) -> MatchAdvanceTrace {
        let mut trace = MatchAdvanceTrace::default();
        let pos = history.len() - 1;
        let k = MATCH_MIN_LENGTH;

        if self.match_len > 0 {
            if self.match_pos < pos && history[self.match_pos] == history[pos] {
                self.match_pos += 1;
                self.match_len += 1;
            } else {
                self.match_len = 0;
            }
        }

        if pos + 1 < k {
            return trace;
        }
        let key = Self::key(&history[pos + 1 - k..=pos]);
        let candidate = self.table[key];
        self.table[key] = (pos + 1) as u32;

        if self.match_len > 0 {
            trace.live_suppressed_acquisition = true;
        } else if candidate == NO_POS {
            trace.empty_slot = true;
        } else {
            let candidate = candidate as usize;
            if candidate >= k && candidate <= pos {
                let distance = (pos + 1) - candidate;
                if distance > MATCH_WINDOW_BYTES {
                    trace.window_expired = true;
                } else if Self::verify(history, candidate - 1, pos, k) {
                    self.match_pos = candidate;
                    self.match_len = k;
                    trace.acquired = true;
                } else {
                    trace.prefix_verification_failed = true;
                }
            } else {
                trace.prefix_verification_failed = true;
            }
        }
        trace
    }

    /// Byte-verify that the `k`-grams ending at `end_a` and `end_b` are equal.
    fn verify(history: &[u8], end_a: usize, end_b: usize, k: usize) -> bool {
        (0..k).all(|j| history[end_a - j] == history[end_b - j])
    }
}

// ---------------------------------------------------------------------------
// Match fold mixer
// ---------------------------------------------------------------------------

struct FoldScratch {
    base: usize,
    stretches: [i64; FOLD_INPUTS],
    mixed_probability: i32,
}

/// Two-real-input logistic fold that folds the match prediction into the moon
/// `base` in the log-odds domain — the same stretch/squash arithmetic and
/// pinned constants the moon mixer uses. It is initialised as an identity on
/// the base (full weight on `base`, zero on the match and the bias), so with no
/// live match it passes the H1 `base` through unchanged and only learns to
/// trust the match input as the match proves itself.
struct MatchMixer {
    stretch: Box<[i32; 65_536]>,
    weights: Box<[i32]>,
    scratch: Option<FoldScratch>,
}

impl MatchMixer {
    fn new(table: &LossTable) -> Self {
        let mut weights = vec![0_i32; FOLD_BUCKETS * FOLD_INPUTS].into_boxed_slice();
        for bucket in 0..FOLD_BUCKETS {
            weights[bucket * FOLD_INPUTS] = FOLD_WEIGHT_ONE;
        }
        Self {
            stretch: build_stretch(table),
            weights,
            scratch: None,
        }
    }

    #[cfg(test)]
    #[must_use]
    fn declared_state_bytes(&self) -> usize {
        self.weights.len() * 4
    }

    fn bucket(node: u8, last_byte: u8) -> usize {
        (((node as usize) << 4) ^ (last_byte as usize)) & (FOLD_BUCKETS - 1)
    }

    fn stretch_of(&self, probability_of_one: u16) -> i64 {
        i64::from(self.stretch[usize::from(probability_of_one)])
            .clamp(-FOLD_STRETCH_CLAMP, FOLD_STRETCH_CLAMP)
    }

    fn predict(&mut self, node: u8, last_byte: u8, base: u16, match_probability: u16) -> u16 {
        let bucket = Self::bucket(node, last_byte) * FOLD_INPUTS;
        let mut stretches = [0_i64; FOLD_INPUTS];
        stretches[0] = self.stretch_of(base);
        stretches[1] = self.stretch_of(match_probability);
        stretches[2] = FOLD_BIAS_STRETCH;
        let mut dot = 0_i64;
        for (input, &stretch) in stretches.iter().enumerate() {
            dot += i64::from(self.weights[bucket + input]) * stretch;
        }
        let mixed_q24 = (dot >> 16).clamp(-FOLD_STRETCH_CLAMP, FOLD_STRETCH_CLAMP);
        let mixed_probability = self.squash(mixed_q24);
        self.scratch = Some(FoldScratch {
            base: bucket,
            stretches,
            mixed_probability,
        });
        (mixed_probability as u32).clamp(u32::from(MIN_PROBABILITY), u32::from(MAX_PROBABILITY))
            as u16
    }

    fn update(&mut self, bit: bool) {
        let Some(scratch) = self.scratch.take() else {
            debug_assert!(false, "match fold update without a preceding predict");
            return;
        };
        let error = i64::from(if bit { 65_536 } else { 0 } - scratch.mixed_probability);
        for input in 0..FOLD_INPUTS {
            let delta = ((error * scratch.stretches[input]) >> FOLD_LEARN_SHIFT) as i32;
            let weight = &mut self.weights[scratch.base + input];
            *weight = (*weight + delta).clamp(-FOLD_WEIGHT_LIMIT, FOLD_WEIGHT_LIMIT);
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

/// Declared model-state bytes for a C1 model: the H1 shape (96 MiB context
/// table + moon mixer weights + frozen s0 mixer + SSE) plus the match hash
/// table, the adaptive hit-probability map, and the match fold weight table.
/// Scratch registers (match pointers, snapshots, continuation, rolling word
/// hash) and derived constant tables (stretch lookups) are excluded, mirroring
/// the s0 `modeled_state_bytes` convention.
#[must_use]
pub fn c1_declared_state_bytes(table: &LossTable, sse_bucket_bits: u32) -> usize {
    let (mixer_bytes, sse_bytes) =
        M5Mixer::with_sse_bucket_bits(table, sse_bucket_bits).declared_state_bytes();
    H1_CONTEXT_TABLE_BYTES
        + MOON_MIXER_WEIGHT_BYTES
        + mixer_bytes
        + sse_bytes
        + MATCH_TABLE_BYTES
        + MATCH_STATEMAP_BYTES
        + FOLD_WEIGHT_BYTES
}

/// The mutable C1 model state. Reused unchanged by the encoder and decoder so
/// both evolve byte-for-byte identically.
struct C1Model {
    contexts: ContextTable,
    moon: MoonMixer,
    fold: MatchMixer,
    mixer: Box<M5Mixer>,
    matcher: MatchModel,
    continuation: Probability,
    word: u64,
    last_byte: u8,
}

impl C1Model {
    fn new(table: &LossTable, sse_bucket_bits: u32) -> Self {
        Self {
            contexts: ContextTable::new(),
            moon: MoonMixer::new(table),
            fold: MatchMixer::new(table),
            mixer: Box::new(M5Mixer::with_sse_bucket_bits(table, sse_bucket_bits)),
            matcher: MatchModel::new(),
            continuation: Probability::default(),
            word: 0,
            last_byte: 0,
        }
    }

    /// The eight context hashes for one bit — byte-identical to the H1 floor.
    fn context_hashes(&self, history: &[u8], node: u8) -> [u64; C1_CONTEXT_COUNT] {
        let mut hashes = [0_u64; C1_CONTEXT_COUNT];
        let position = history.len();
        for (slot, &order) in C1_BYTE_ORDERS.iter().enumerate() {
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

    fn resolve(&mut self, history: &[u8], node: u8) -> ([usize; C1_CONTEXT_COUNT], [u16; 8]) {
        let hashes = self.context_hashes(history, node);
        let mut indices = [0_usize; C1_CONTEXT_COUNT];
        let mut probabilities = [0_u16; 8];
        for (slot, &hash) in hashes.iter().enumerate() {
            let index = self.contexts.resolve(hash);
            indices[slot] = index;
            probabilities[slot] = self.contexts.cell(index).probability_of_one();
        }
        (indices, probabilities)
    }

    fn event_id(&self, node: u8) -> u64 {
        (u64::from(self.last_byte) << 8) | u64::from(node)
    }

    fn observe(&mut self, indices: &[usize; C1_CONTEXT_COUNT], bit: bool) {
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

    /// Charged probability for one modeled byte-bit: moon `base` over the eight
    /// contexts, folded with the match prediction, then recalibrated by the s0
    /// mixer. Prediction is independent of the bit value, so the decoder
    /// reproduces the identical probability.
    fn predict_byte_bit(
        &mut self,
        probabilities: &[u16; C1_CONTEXT_COUNT],
        node: u8,
        event_id: u64,
        match_bit: MatchBit,
    ) -> u16 {
        let last_byte = self.last_byte;
        let base = self.moon.predict(node, last_byte, probabilities);
        let folded = self
            .fold
            .predict(node, last_byte, base, match_bit.probability);
        self.mixer.predict(event_id, folded)
    }

    fn update_byte_bit(
        &mut self,
        indices: &[usize; C1_CONTEXT_COUNT],
        match_bit: MatchBit,
        bit: bool,
    ) {
        self.mixer.update(bit);
        self.fold.update(bit);
        self.moon.update(bit);
        self.observe(indices, bit);
        self.matcher.update_bit(match_bit, bit);
    }

    fn encode_byte(
        &mut self,
        byte: u8,
        history: &[u8],
        pos: usize,
        table: &LossTable,
        ledger: &mut Ledger,
        writer: &mut TapeWriter,
    ) -> Result<C1ObservedByte, C1Error> {
        self.matcher.begin_byte(history, pos);
        let match_length = self.matcher.match_len as u32;
        let match_distance = if self.matcher.live {
            pos.saturating_sub(self.matcher.match_pos) as u32
        } else {
            0
        };
        let mut node: u32 = 1;
        let mut bit_loss_q24 = [0_u32; 8];
        let mut match_valid_mask = 0_u8;
        let mut match_correct_mask = 0_u8;
        for (slot, shift) in (0..8_u32).rev().enumerate() {
            let bit_index = 7 - shift;
            let bit = (byte >> shift) & 1 == 1;
            let (indices, probabilities) = self.resolve(history, node as u8);
            let match_bit = self.matcher.predict_bit(node, shift, bit_index);
            if match_bit.valid {
                match_valid_mask |= 1 << slot;
                if match_bit.predicted_bit == bit {
                    match_correct_mask |= 1 << slot;
                }
            }
            let event_id = self.event_id(node as u8);
            let charged = self.predict_byte_bit(&probabilities, node as u8, event_id, match_bit);
            bit_loss_q24[slot] = charge(charged, bit, table, ledger)?;
            writer.push_bit(bit)?;
            self.update_byte_bit(&indices, match_bit, bit);
            node = (node << 1) | u32::from(bit);
        }
        self.advance_byte(byte);
        Ok(C1ObservedByte {
            position: pos,
            byte,
            continuation_loss_q24: 0,
            bit_loss_q24,
            match_valid_mask,
            match_correct_mask,
            match_length_before: match_length,
            match_distance_before: match_distance,
            match_length_after: 0,
            match_distance_after: 0,
            match_broke: false,
            acquisition_initial: false,
            acquisition_after_break: false,
            acquisition_empty_slot: false,
            acquisition_prefix_verification_failed: false,
            acquisition_window_expired: false,
            acquisition_live_suppressed: false,
        })
    }

    fn decode_byte(
        &mut self,
        history: &[u8],
        pos: usize,
        table: &LossTable,
        ledger: &mut Ledger,
        reader: &mut TapeReader<'_>,
    ) -> Result<u8, C1Error> {
        self.matcher.begin_byte(history, pos);
        let mut node: u32 = 1;
        for shift in (0..8_u32).rev() {
            let bit_index = 7 - shift;
            let bit = reader.read_bit()?;
            let (indices, probabilities) = self.resolve(history, node as u8);
            let match_bit = self.matcher.predict_bit(node, shift, bit_index);
            let event_id = self.event_id(node as u8);
            let charged = self.predict_byte_bit(&probabilities, node as u8, event_id, match_bit);
            charge(charged, bit, table, ledger)?;
            self.update_byte_bit(&indices, match_bit, bit);
            node = (node << 1) | u32::from(bit);
        }
        let byte = (node & 0xff) as u8;
        self.advance_byte(byte);
        Ok(byte)
    }

    /// Continuation framing bit — identical to the H1 floor: charged through the
    /// s0 mixer only, never through the match fold or the match model.
    fn encode_continuation(
        &mut self,
        more: bool,
        table: &LossTable,
        ledger: &mut Ledger,
        writer: &mut TapeWriter,
    ) -> Result<u32, C1Error> {
        let base = self.continuation.probability_of_one();
        let charged = self.mixer.predict(CONTINUATION_EVENT_ID, base);
        let loss = charge(charged, more, table, ledger)?;
        writer.push_bit(more)?;
        self.mixer.update(more);
        self.continuation.update(more, C1_RATE_SHIFT);
        Ok(loss)
    }

    fn decode_continuation(
        &mut self,
        table: &LossTable,
        ledger: &mut Ledger,
        reader: &mut TapeReader<'_>,
    ) -> Result<bool, C1Error> {
        let more = reader.read_bit()?;
        let base = self.continuation.probability_of_one();
        let charged = self.mixer.predict(CONTINUATION_EVENT_ID, base);
        charge(charged, more, table, ledger)?;
        self.mixer.update(more);
        self.continuation.update(more, C1_RATE_SHIFT);
        Ok(more)
    }
}

fn charge(
    probability: u16,
    bit: bool,
    table: &LossTable,
    ledger: &mut Ledger,
) -> Result<u32, C1Error> {
    let loss = table
        .get(observed_probability(probability, bit))
        .ok_or(C1Error::InvalidProbability)?;
    ledger
        .add_modeled_event(loss)
        .ok_or(C1Error::LedgerOverflow)?;
    Ok(loss)
}

// ---------------------------------------------------------------------------
// Read-only residual observer
// ---------------------------------------------------------------------------

/// One streaming observation emitted by the canonical C1 encoder. None of
/// these fields is consulted by the coding path.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct C1ObservedByte {
    pub position: usize,
    pub byte: u8,
    pub continuation_loss_q24: u32,
    pub bit_loss_q24: [u32; 8],
    /// Bits for which the canonical one-candidate matcher remained live.
    pub match_valid_mask: u8,
    /// Live-match bits whose prediction equalled the observed bit.
    pub match_correct_mask: u8,
    pub match_length_before: u32,
    pub match_distance_before: u32,
    /// Canonical matcher state after this byte, which is the pre-state for the
    /// next byte when one exists.
    pub match_length_after: u32,
    pub match_distance_after: u32,
    pub match_broke: bool,
    pub acquisition_initial: bool,
    pub acquisition_after_break: bool,
    pub acquisition_empty_slot: bool,
    pub acquisition_prefix_verification_failed: bool,
    pub acquisition_window_expired: bool,
    pub acquisition_live_suppressed: bool,
}

impl C1ObservedByte {
    #[must_use]
    pub fn modeled_loss_q24(&self) -> u64 {
        self.bit_loss_q24.iter().map(|&loss| u64::from(loss)).sum()
    }
}

/// The one canonical C1 event generator. The optional observer receives events
/// only after all coder/model updates for that byte; it cannot influence them.
pub(super) fn encode_c1_item_with_bits_observer<F>(
    source: &[u8],
    table: &LossTable,
    item_index: u8,
    sse_bucket_bits: u32,
    mut observer: F,
) -> Result<(Tape, Ledger, u32), C1Error>
where
    F: FnMut(C1ObservedByte),
{
    let mut model = C1Model::new(table, sse_bucket_bits);
    let mut writer = TapeWriter::new(C1_ARM_ID, item_index);
    let mut ledger = Ledger::default();
    let mut outstanding_break = false;
    for (position, &byte) in source.iter().enumerate() {
        let continuation_loss_q24 =
            model.encode_continuation(true, table, &mut ledger, &mut writer)?;
        let mut event = model.encode_byte(
            byte,
            &source[..position],
            position,
            table,
            &mut ledger,
            &mut writer,
        )?;
        let acquisition = model.matcher.advance_traced(&source[..=position]);
        let after_len = model.matcher.match_len as u32;
        let after_distance = if model.matcher.match_len > 0 {
            position
                .saturating_add(1)
                .saturating_sub(model.matcher.match_pos) as u32
        } else {
            0
        };
        event.match_broke = event.match_length_before > 0
            && after_len != event.match_length_before.saturating_add(1);
        if event.match_broke {
            outstanding_break = true;
        }
        if acquisition.acquired {
            event.acquisition_after_break = outstanding_break;
            event.acquisition_initial = !outstanding_break;
            outstanding_break = false;
        }
        event.continuation_loss_q24 = continuation_loss_q24;
        event.acquisition_empty_slot = acquisition.empty_slot;
        event.acquisition_prefix_verification_failed = acquisition.prefix_verification_failed;
        event.acquisition_window_expired = acquisition.window_expired;
        event.acquisition_live_suppressed = acquisition.live_suppressed_acquisition;
        event.match_length_after = after_len;
        event.match_distance_after = after_distance;
        if byte == b'\n' {
            ledger.add_record().ok_or(C1Error::LedgerOverflow)?;
        }
        observer(event);
    }
    let terminal = model.encode_continuation(false, table, &mut ledger, &mut writer)?;
    Ok((writer.finish(), ledger, terminal))
}

/// Encode one item under the C1 arm at the base SSE capacity.
pub fn encode_c1_item(
    source: &[u8],
    table: &LossTable,
    item_index: u8,
) -> Result<(Tape, Ledger), C1Error> {
    encode_c1_item_with_bits(source, table, item_index, crate::s0::SSE_BASE_BUCKET_BITS)
}

/// Encode one item under the C1 arm at an explicit SSE capacity.
pub fn encode_c1_item_with_bits(
    source: &[u8],
    table: &LossTable,
    item_index: u8,
    sse_bucket_bits: u32,
) -> Result<(Tape, Ledger), C1Error> {
    encode_c1_item_with_bits_observer(source, table, item_index, sse_bucket_bits, |_| {})
        .map(|(tape, ledger, _terminal)| (tape, ledger))
}

/// Decode one item under the C1 arm at the base SSE capacity.
pub fn decode_c1_item(
    tape: &Tape,
    expected_ledger: Ledger,
    table: &LossTable,
    expected_item_index: u8,
) -> Result<Vec<u8>, C1Error> {
    decode_c1_item_with_bits(
        tape,
        expected_ledger,
        table,
        expected_item_index,
        crate::s0::SSE_BASE_BUCKET_BITS,
    )
}

/// Decode one item under the C1 arm, checking arm/item identity and independent
/// ledger equality, and fail-closed on trailing charged data.
pub fn decode_c1_item_with_bits(
    tape: &Tape,
    expected_ledger: Ledger,
    table: &LossTable,
    expected_item_index: u8,
    sse_bucket_bits: u32,
) -> Result<Vec<u8>, C1Error> {
    if tape.arm_id() != C1_ARM_ID || tape.item_index() != expected_item_index {
        return Err(C1Error::TapeIdentityMismatch);
    }
    let mut model = C1Model::new(table, sse_bucket_bits);
    let mut ledger = Ledger::default();
    let mut reader = tape.reader();
    let mut output: Vec<u8> = Vec::new();
    loop {
        if !model.decode_continuation(table, &mut ledger, &mut reader)? {
            break;
        }
        let position = output.len();
        let byte = model.decode_byte(&output, position, table, &mut ledger, &mut reader)?;
        output.push(byte);
        model.matcher.advance(&output);
        if byte == b'\n' {
            ledger.add_record().ok_or(C1Error::LedgerOverflow)?;
        }
    }
    if !reader.is_finished() {
        return Err(C1Error::TrailingChargedData);
    }
    if ledger != expected_ledger {
        return Err(C1Error::LedgerDivergence {
            encoder: expected_ledger,
            decoder: ledger,
        });
    }
    Ok(output)
}

/// C1 encode/decode error. Every variant is terminal for the item.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum C1Error {
    InvalidProbability,
    LedgerOverflow,
    TapeIdentityMismatch,
    TrailingChargedData,
    LedgerDivergence { encoder: Ledger, decoder: Ledger },
    Tape(TapeError),
}

impl From<TapeError> for C1Error {
    fn from(error: TapeError) -> Self {
        Self::Tape(error)
    }
}

impl Display for C1Error {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "moon C1 error: {self:?}")
    }
}

impl Error for C1Error {}

#[cfg(test)]
mod tests {
    use super::*;
    use sha2::{Digest, Sha256};

    // Pinned once from the deterministic encoder; the tape is a pure function of
    // the source bytes and arm/item identity.
    const PINNED_TAPE_SHA256: &str =
        "b1da055d669a07dd7289bac98f15d9bcb9962bec3fcc499b5c6936c102e1ee31";

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
            let (tape, ledger) = encode_c1_item(&source, &table, 1).unwrap();
            let decoded = decode_c1_item(&tape, ledger, &table, 1).unwrap();
            assert_eq!(decoded, source, "regime {name} did not round-trip");
            assert_eq!(ledger.raw_literal_bytes, 0, "C1 charges no literals");
        }
    }

    #[test]
    fn repeat_runs_are_byte_identical_in_tape_and_ledger() {
        let table = LossTable::generate();
        let source = regime_snippets().remove(0).1;
        let (tape_a, ledger_a) = encode_c1_item(&source, &table, 2).unwrap();
        let (tape_b, ledger_b) = encode_c1_item(&source, &table, 2).unwrap();
        assert_eq!(tape_a.to_bytes(), tape_b.to_bytes());
        assert_eq!(ledger_a, ledger_b);
    }

    #[test]
    fn decode_fails_closed_on_a_tampered_ledger() {
        let table = LossTable::generate();
        let source = b"{\"a\":1}\n{\"a\":2}\n{\"a\":1}\n".to_vec();
        let (tape, ledger) = encode_c1_item(&source, &table, 0).unwrap();
        let mut wrong = ledger;
        wrong.modeled_loss_q24 += 1;
        assert!(matches!(
            decode_c1_item(&tape, wrong, &table, 0),
            Err(C1Error::LedgerDivergence { .. })
        ));
    }

    #[test]
    fn decode_rejects_a_foreign_arm_or_item_identity() {
        let table = LossTable::generate();
        let source = b"hello world\n".to_vec();
        let (tape, ledger) = encode_c1_item(&source, &table, 3).unwrap();
        assert_eq!(
            decode_c1_item(&tape, ledger, &table, 4),
            Err(C1Error::TapeIdentityMismatch)
        );
    }

    #[test]
    fn a_flipped_payload_byte_is_rejected_by_the_tape_digest() {
        let table = LossTable::generate();
        let source = regime_snippets().remove(0).1;
        let (tape, _) = encode_c1_item(&source, &table, 0).unwrap();
        let mut bytes = tape.to_bytes();
        let target = bytes.len() / 2;
        bytes[target] ^= 0x01;
        assert_eq!(Tape::from_bytes(&bytes), Err(TapeError::DigestMismatch));
    }

    #[test]
    fn a_truncated_tape_is_rejected() {
        let table = LossTable::generate();
        let source = regime_snippets().remove(0).1;
        let (tape, _) = encode_c1_item(&source, &table, 0).unwrap();
        let mut bytes = tape.to_bytes();
        bytes.truncate(bytes.len() - 1);
        assert!(Tape::from_bytes(&bytes).is_err());
    }

    #[test]
    fn one_extra_charged_bit_past_end_of_stream_fails_closed() {
        let table = LossTable::generate();
        let source = b"{\"a\":1}\n{\"a\":2}\n".to_vec();
        let (tape, ledger) = encode_c1_item(&source, &table, 0).unwrap();
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
            decode_c1_item(&tampered, ledger, &table, 0),
            Err(C1Error::TrailingChargedData)
        );
    }

    #[test]
    fn refined_sse_bits_hold_the_tape_and_event_stream() {
        let table = LossTable::generate();
        let source = regime_snippets().remove(2).1;
        let (base_tape, base_ledger) = encode_c1_item_with_bits(&source, &table, 0, 17).unwrap();
        let (refined_tape, refined_ledger) =
            encode_c1_item_with_bits(&source, &table, 0, 18).unwrap();
        // The SSE capacity refines only the charged probability: it never
        // changes the tape bits or the event structure.
        assert_eq!(base_tape.to_bytes(), refined_tape.to_bytes());
        assert_eq!(
            base_ledger.modeled_binary_events,
            refined_ledger.modeled_binary_events
        );
        assert_eq!(base_ledger.records, refined_ledger.records);
        assert_eq!(
            decode_c1_item_with_bits(&refined_tape, refined_ledger, &table, 0, 18).unwrap(),
            source
        );
    }

    #[test]
    fn declared_state_accounts_for_match_table_statemap_and_fold() {
        let table = LossTable::generate();
        let model = C1Model::new(&table, crate::s0::SSE_BASE_BUCKET_BITS);
        assert_eq!(
            model.contexts.declared_state_bytes(),
            H1_CONTEXT_TABLE_BYTES
        );
        assert_eq!(model.moon.declared_state_bytes(), MOON_MIXER_WEIGHT_BYTES);
        assert_eq!(
            model.matcher.declared_state_bytes(),
            MATCH_TABLE_BYTES + MATCH_STATEMAP_BYTES
        );
        assert_eq!(model.fold.declared_state_bytes(), FOLD_WEIGHT_BYTES);
        let (mixer_bytes, sse_bytes) = model.mixer.declared_state_bytes();
        let composed = model.contexts.declared_state_bytes()
            + model.moon.declared_state_bytes()
            + mixer_bytes
            + sse_bytes
            + model.matcher.declared_state_bytes()
            + model.fold.declared_state_bytes();
        let standalone = c1_declared_state_bytes(&table, crate::s0::SSE_BASE_BUCKET_BITS);
        assert_eq!(composed, standalone);
        // The C1 additions over the H1 shape are exactly the match table, the
        // adaptive hit-probability map, and the fold weight table.
        assert_eq!(MATCH_TABLE_BYTES, 16_777_216);
        assert_eq!(MATCH_STATEMAP_BYTES, 128);
        assert_eq!(FOLD_WEIGHT_BYTES, 49_152);
        // Regression pin of the exact figure the receipts report.
        assert_eq!(standalone, 136_773_760);
        let refined = c1_declared_state_bytes(&table, crate::s0::SSE_REFINED_BUCKET_BITS);
        assert!(refined > standalone);
    }

    #[test]
    fn no_live_match_folds_the_base_through_unchanged() {
        // With no repeats at all, the match never fires: every fold sees a
        // neutral match input and the identity-initialised base weight, so the
        // arm still round-trips exactly and charges only through the base path.
        let table = LossTable::generate();
        let source: Vec<u8> = (0..=255_u8).collect();
        let (tape, ledger) = encode_c1_item(&source, &table, 0).unwrap();
        assert_eq!(decode_c1_item(&tape, ledger, &table, 0).unwrap(), source);
    }

    #[test]
    fn the_match_model_captures_repeat_mass_below_the_h1_floor() {
        // On a strongly repetitive stream the match model must fold in real
        // signal and drive C1's projected complete bytes below the H1 floor.
        use crate::moon::h1::encode_h1_item;
        let table = LossTable::generate();
        let mut source = Vec::new();
        for index in 0..4_000_u32 {
            source.extend_from_slice(
                format!(
                    "{{\"level\":\"info\",\"service\":\"api\",\"seq\":{}}}\n",
                    index % 8
                )
                .as_bytes(),
            );
        }
        let (_, c1_ledger) = encode_c1_item(&source, &table, 0).unwrap();
        let (_, h1_ledger) = encode_h1_item(&source, &table, 0).unwrap();
        let c1 = c1_ledger.project_item(source.len() as u64).unwrap();
        let h1 = h1_ledger.project_item(source.len() as u64).unwrap();
        assert!(
            c1.complete_bytes < h1.complete_bytes,
            "C1 {} not below H1 {}",
            c1.complete_bytes,
            h1.complete_bytes
        );
    }

    #[test]
    fn byte_verification_rejects_a_hash_collision() {
        // A candidate whose k-gram does not actually match must be rejected: the
        // verify guard compares the bytes, not just the hash.
        // Indices: A0 B1 C2 D3 E4 F5 X6 Y7 Z8 A9 B10 C11 D12 E13 F14.
        let history = b"ABCDEFXYZABCDEF".to_vec();
        // "ABCDEF" ends at index 5 and again at index 14: a real, verified match.
        assert!(MatchModel::verify(&history, 5, 14, MATCH_MIN_LENGTH));
        // The span ending at index 13 is "ZABCDE": the bytes differ, so a hash
        // collision landing here must be rejected.
        assert!(!MatchModel::verify(&history, 5, 13, MATCH_MIN_LENGTH));
    }

    #[test]
    fn encode_and_decode_are_cross_run_deterministic() {
        let table = LossTable::generate();
        let source = regime_snippets().remove(1).1;
        let first = encode_c1_item(&source, &table, 5).unwrap();
        let second = encode_c1_item(&source, &table, 5).unwrap();
        assert_eq!(first.0.to_bytes(), second.0.to_bytes());
        assert_eq!(first.1, second.1);
    }

    #[test]
    fn known_answer_tape_sha256_is_pinned() {
        let table = LossTable::generate();
        let source = b"{\"level\":\"info\",\"msg\":\"ready\",\"n\":1}\n\
                       {\"level\":\"info\",\"msg\":\"ready\",\"n\":2}\n"
            .to_vec();
        let (tape, _) = encode_c1_item(&source, &table, 0).unwrap();
        let sha: String = Sha256::digest(tape.to_bytes())
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect();
        assert_eq!(sha, PINNED_TAPE_SHA256, "pinned tape SHA-256 changed");
    }
}
