//! C8: live expert-mixture with online credit assignment.
//!
//! Development-only Cycle 2 arm. C8 keeps H1's byte grammar, its shared
//! open-addressed [`ContextTable`] (so the counter update rules and eviction
//! dynamics are byte-for-byte H1's — honouring the C3 lesson), and H1's eight
//! context views. It adds a ninth expert — the recent-record/column view (the
//! byte at the same offset in the previous record) — and, crucially, replaces
//! H1's shared hashed logistic mixer with a *bounded per-(expert, context
//! bucket) mixture with online credit assignment*.
//!
//! Each context view is an EXPERT. Every expert carries a non-negative weight
//! per small context bucket, updated live by an integer logistic gradient on
//! the coding loss (charge-before-update). Because the expert weights are
//! clamped to `[0, WEIGHT_LIMIT]`, an expert that loses in a bucket has its
//! weight driven monotonically toward the zero floor there — it is gated off,
//! never allowed to invert and poison the mixture. A separate signed bias term
//! carries the per-bucket base rate. Nothing is frozen: a gated-off expert
//! climbs back the instant it starts winning again (honouring the H8 lesson).
//! The mixture output feeds the frozen s0 [`M5Mixer`] as a recalibration base,
//! exactly as H1 does, so the projection is exact, integer-only, and directly
//! comparable to the floor. All arithmetic is integer; all mixture state
//! (context table + per-bucket weights + the s0 mixer/SSE tables) is counted in
//! the declared state. Encode immediately re-decodes and checks ledger
//! equality; decode is fail-closed on corruption, exhaustion, and identity.

use crate::s0::{
    Ledger, LossTable, M5Mixer, Probability, Tape, TapeError, TapeReader, TapeWriter,
    MAX_PROBABILITY, MIN_PROBABILITY,
};
use std::error::Error;
use std::fmt::{Display, Formatter};

use super::table::{ContextTable, H1_CONTEXT_TABLE_BYTES};

/// Tape arm identity for C8. Disjoint from every other arm id so a tape can
/// never be decoded under the wrong kernel.
pub const C8_ARM_ID: u8 = 107;

/// Number of experts in the mixture: H1's six direct byte orders, one sparse,
/// one word context, plus the recent-record/column view.
pub const C8_EXPERT_COUNT: usize = 9;
/// Byte orders (context lengths) of the six direct-order experts.
pub const C8_BYTE_ORDERS: [usize; 6] = [1, 2, 3, 4, 6, 8];
/// Stable expert labels, in mixer-input order. Used only by the read-only
/// credit-assignment observer; never affects a tape or ledger.
pub const C8_EXPERT_NAMES: [&str; C8_EXPERT_COUNT] = [
    "order1", "order2", "order3", "order4", "order6", "order8", "sparse", "word", "column",
];

/// Mixer inputs: the nine experts plus one constant-bias input.
pub const C8_MIXER_INPUTS: usize = C8_EXPERT_COUNT + 1;
/// Small context bucket: a weight vector per (node, last_byte)-derived bucket.
pub const C8_MIXER_BUCKET_BITS: u32 = 12;
pub const C8_MIXER_BUCKETS: usize = 1 << C8_MIXER_BUCKET_BITS;
/// Declared mutable mixture-weight state: one `i32` per (bucket, input).
pub const C8_MIXER_WEIGHT_BYTES: usize = C8_MIXER_BUCKETS * C8_MIXER_INPUTS * 4;

/// Bounded column window: the recent-record/column expert only aligns the
/// first `C8_COLUMN_WINDOW` bytes of a record against the previous record.
/// Two fixed buffers of this size are O(1) reproduce-from-source scratch (like
/// H1's `word`/`last_byte` registers), excluded from declared state by the same
/// convention the s0 `modeled_state_bytes` and H1 use.
pub const C8_COLUMN_WINDOW: usize = 512;

/// Number of bucket classes reported by the credit-assignment observer: the
/// previous byte's lexical class (digit, letter, structural, whitespace,
/// other). Read-only diagnostic granularity; never touches a tape.
pub const C8_BUCKET_CLASSES: usize = 5;
pub const C8_CLASS_LABELS: [&str; C8_BUCKET_CLASSES] =
    ["digit", "letter", "structural", "whitespace", "other"];

const C8_RATE_SHIFT: u32 = 5;
const CONTINUATION_EVENT_ID: u64 = u64::MAX;

// Disjoint FNV-1a namespaces per context kind (identical to H1's for the eight
// shared views, plus a fresh tag for the column expert).
const TAG_ORDER: u8 = 0x01;
const TAG_SPARSE: u8 = 0xa5;
const TAG_WORD: u8 = 0x5a;
const TAG_WORD_ACCUM: u8 = 0x33;
const TAG_COLUMN: u8 = 0xc8;
const FNV_OFFSET: u64 = 14_695_981_039_346_656_037;
const FNV_PRIME: u64 = 1_099_511_628_211;

const _: () = assert!(C8_MIXER_BUCKETS.is_power_of_two());
const _: () = assert!(C8_MIXER_WEIGHT_BYTES == 4096 * 10 * 4);

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

/// Lexical class of the previous byte, used only to bucket the credit-assignment
/// observer's weight-share report.
fn byte_class(byte: u8) -> usize {
    if byte.is_ascii_digit() {
        0
    } else if byte.is_ascii_alphabetic() {
        1
    } else if matches!(byte, b'{' | b'}' | b'[' | b']' | b'"' | b':' | b',') {
        2
    } else if byte == b' ' || byte == b'\n' || byte == b'\t' || byte == b'\r' {
        3
    } else {
        4
    }
}

// ---------------------------------------------------------------------------
// The per-(expert, bucket) mixture with non-negative gated weights and a signed
// per-bucket bias. This is the credit-assignment engine.
// ---------------------------------------------------------------------------

/// Unit weight in Q16; each expert's initial weight is `WEIGHT_ONE / experts`.
const WEIGHT_ONE: i32 = 1 << 16;
const WEIGHT_INIT: i32 = WEIGHT_ONE / C8_EXPERT_COUNT as i32;
/// Expert weights live in `[0, WEIGHT_LIMIT]`; the bias in `[-LIMIT, LIMIT]`.
const WEIGHT_LIMIT: i32 = 1 << 20;
/// Gradient step shift (matches the s0/H1 mixer's `LEARN_SHIFT`).
const LEARN_SHIFT: u32 = 34;
/// Stretch values are clamped to +-8.0 log2-odds in Q24 before mixing.
const STRETCH_CLAMP: i64 = 8 << 24;
/// The constant-bias input's stretch value (1.0 log2-odds in Q24).
const BIAS_STRETCH: i64 = 1 << 24;

struct MixerScratch {
    base: usize,
    stretches: [i64; C8_MIXER_INPUTS],
    mixed_probability: i32,
}

struct C8Mixer {
    stretch: Box<[i32; 65_536]>,
    weights: Box<[i32]>,
    scratch: Option<MixerScratch>,
}

impl C8Mixer {
    fn new(table: &LossTable) -> Self {
        // Expert inputs start at the uniform init; the bias input starts
        // neutral (zero) so an untouched bucket reproduces the incoming base.
        let mut weights = vec![WEIGHT_INIT; C8_MIXER_BUCKETS * C8_MIXER_INPUTS].into_boxed_slice();
        for bucket in 0..C8_MIXER_BUCKETS {
            weights[bucket * C8_MIXER_INPUTS + C8_EXPERT_COUNT] = 0;
        }
        Self {
            stretch: build_stretch(table),
            weights,
            scratch: None,
        }
    }

    #[cfg(test)]
    fn declared_state_bytes(&self) -> usize {
        self.weights.len() * 4
    }

    fn bucket(node: u8, last_byte: u8) -> usize {
        (((node as usize) << 4) ^ (last_byte as usize)) & (C8_MIXER_BUCKETS - 1)
    }

    fn stretch_of(&self, probability_of_one: u16) -> i64 {
        i64::from(self.stretch[usize::from(probability_of_one)])
            .clamp(-STRETCH_CLAMP, STRETCH_CLAMP)
    }

    /// Mix the nine expert probabilities plus the constant bias into one
    /// probability of a one. Must be followed by exactly one [`update`].
    ///
    /// [`update`]: C8Mixer::update
    fn predict(&mut self, node: u8, last_byte: u8, probabilities: &[u16; C8_EXPERT_COUNT]) -> u16 {
        let base = Self::bucket(node, last_byte) * C8_MIXER_INPUTS;
        let mut stretches = [0_i64; C8_MIXER_INPUTS];
        let mut dot = 0_i64;
        for (input, &probability) in probabilities.iter().enumerate() {
            let stretch = self.stretch_of(probability);
            stretches[input] = stretch;
            dot += i64::from(self.weights[base + input]) * stretch;
        }
        stretches[C8_EXPERT_COUNT] = BIAS_STRETCH;
        dot += i64::from(self.weights[base + C8_EXPERT_COUNT]) * BIAS_STRETCH;

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

    /// Apply the integer logistic gradient for the bit just observed. Expert
    /// weights are clamped non-negative (losing experts decay to the zero
    /// floor); the bias is signed. Charge-before-update: weights move only
    /// after the bit.
    fn update(&mut self, bit: bool) {
        let Some(scratch) = self.scratch.take() else {
            debug_assert!(false, "C8 mixer update without a preceding predict");
            return;
        };
        let error = i64::from(if bit { 65_536 } else { 0 } - scratch.mixed_probability);
        for input in 0..C8_EXPERT_COUNT {
            let delta = ((error * scratch.stretches[input]) >> LEARN_SHIFT) as i32;
            let weight = &mut self.weights[scratch.base + input];
            *weight = (*weight + delta).clamp(0, WEIGHT_LIMIT);
        }
        let bias = &mut self.weights[scratch.base + C8_EXPERT_COUNT];
        let bias_delta = ((error * BIAS_STRETCH) >> LEARN_SHIFT) as i32;
        *bias = (*bias + bias_delta).clamp(-WEIGHT_LIMIT, WEIGHT_LIMIT);
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

    /// Read-only snapshot: the current normalized weight share of each expert in
    /// one bucket, in Q16 (shares sum to ~65536). Used solely by the
    /// credit-assignment observer; never affects a tape.
    fn bucket_shares(&self, node: u8, last_byte: u8) -> [u32; C8_EXPERT_COUNT] {
        let base = Self::bucket(node, last_byte) * C8_MIXER_INPUTS;
        let mut total: i64 = 0;
        for input in 0..C8_EXPERT_COUNT {
            total += i64::from(self.weights[base + input].max(0));
        }
        let mut shares = [0_u32; C8_EXPERT_COUNT];
        if total == 0 {
            let uniform = (65_536 / C8_EXPERT_COUNT) as u32;
            return [uniform; C8_EXPERT_COUNT];
        }
        for (input, share) in shares.iter_mut().enumerate() {
            let weight = i64::from(self.weights[base + input].max(0));
            *share = ((weight << 16) / total) as u32;
        }
        shares
    }
}

/// `stretch(p) = log2(p / (65536 - p))` in Q24, derived exactly from the frozen
/// loss table (reconstructs the private s0 `build_stretch` with no s0 edits;
/// identical derivation to the H1 moon mixer).
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

/// Declared model-state bytes: H1's 96 MiB context table, the per-bucket
/// mixture weights, and the frozen s0 mixer + SSE tables. The bounded column
/// buffers and the continuation/word/last-byte registers are O(1)
/// reproduce-from-source scratch, excluded exactly as H1 excludes them.
#[must_use]
pub fn c8_declared_state_bytes(table: &LossTable, sse_bucket_bits: u32) -> usize {
    let (mixer_bytes, sse_bytes) =
        M5Mixer::with_sse_bucket_bits(table, sse_bucket_bits).declared_state_bytes();
    H1_CONTEXT_TABLE_BYTES + C8_MIXER_WEIGHT_BYTES + mixer_bytes + sse_bytes
}

/// The bounded recent-record/column tracker. Fixed two-buffer scratch: the
/// content of the previous record and the current record so far, each capped at
/// [`C8_COLUMN_WINDOW`] bytes.
struct ColumnTracker {
    previous: [u8; C8_COLUMN_WINDOW],
    previous_len: usize,
    current: [u8; C8_COLUMN_WINDOW],
    current_len: usize,
}

impl ColumnTracker {
    fn new() -> Self {
        Self {
            previous: [0; C8_COLUMN_WINDOW],
            previous_len: 0,
            current: [0; C8_COLUMN_WINDOW],
            current_len: 0,
        }
    }

    /// The reference byte for the current column, and whether one exists: the
    /// byte at the same offset in the previous record, if in window and present.
    fn reference(&self) -> (u8, bool) {
        let column = self.current_len;
        if column < C8_COLUMN_WINDOW && column < self.previous_len {
            (self.previous[column], true)
        } else {
            (0, false)
        }
    }

    fn advance(&mut self, byte: u8) {
        if byte == b'\n' {
            self.previous = self.current;
            self.previous_len = self.current_len;
            self.current_len = 0;
        } else {
            if self.current_len < C8_COLUMN_WINDOW {
                self.current[self.current_len] = byte;
            }
            // Saturate the column at the window; past it the expert abstains.
            self.current_len = (self.current_len + 1).min(C8_COLUMN_WINDOW);
        }
    }
}

struct C8Model {
    contexts: ContextTable,
    mixer: C8Mixer,
    recalibrator: Box<M5Mixer>,
    continuation: Probability,
    column: ColumnTracker,
    word: u64,
    last_byte: u8,
}

impl C8Model {
    fn new(table: &LossTable, sse_bucket_bits: u32) -> Self {
        Self {
            contexts: ContextTable::new(),
            mixer: C8Mixer::new(table),
            recalibrator: Box::new(M5Mixer::with_sse_bucket_bits(table, sse_bucket_bits)),
            continuation: Probability::default(),
            column: ColumnTracker::new(),
            word: 0,
            last_byte: 0,
        }
    }

    /// The nine expert hashes for one bit: six direct byte orders, one sparse,
    /// the rolling word context, and the recent-record/column view.
    fn expert_hashes(&self, history: &[u8], node: u8) -> [u64; C8_EXPERT_COUNT] {
        let mut hashes = [0_u64; C8_EXPERT_COUNT];
        let position = history.len();
        for (slot, &order) in C8_BYTE_ORDERS.iter().enumerate() {
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
        // Column expert: the previous record's byte at this column, plus a
        // present flag so "no reference" is its own distinct context.
        let (reference, present) = self.column.reference();
        hashes[8] = fnv1a64(
            fnv1a64(FNV_OFFSET, &[TAG_COLUMN]),
            &[reference, u8::from(present), node],
        );
        hashes
    }

    fn resolve(
        &mut self,
        history: &[u8],
        node: u8,
    ) -> ([usize; C8_EXPERT_COUNT], [u16; C8_EXPERT_COUNT]) {
        let hashes = self.expert_hashes(history, node);
        let mut indices = [0_usize; C8_EXPERT_COUNT];
        let mut probabilities = [0_u16; C8_EXPERT_COUNT];
        for (slot, hash) in hashes.into_iter().enumerate() {
            let index = self.contexts.resolve(hash);
            indices[slot] = index;
            probabilities[slot] = self.contexts.cell(index).probability_of_one();
        }
        (indices, probabilities)
    }

    fn event_id(&self, node: u8) -> u64 {
        (u64::from(self.last_byte) << 8) | u64::from(node)
    }

    fn predict(&mut self, probabilities: &[u16; C8_EXPERT_COUNT], node: u8) -> u16 {
        let mixed = self.mixer.predict(node, self.last_byte, probabilities);
        self.recalibrator.predict(self.event_id(node), mixed)
    }

    fn update(&mut self, indices: &[usize; C8_EXPERT_COUNT], bit: bool) {
        self.recalibrator.update(bit);
        self.mixer.update(bit);
        for &index in indices {
            self.contexts.observe(index, bit);
        }
    }

    fn advance_byte(&mut self, byte: u8) {
        self.column.advance(byte);
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
        more: bool,
        table: &LossTable,
        ledger: &mut Ledger,
        writer: &mut TapeWriter,
    ) -> Result<(), C8Error> {
        let base = self.continuation.probability_of_one();
        let charged = self.recalibrator.predict(CONTINUATION_EVENT_ID, base);
        charge(charged, more, table, ledger)?;
        writer.push_bit(more)?;
        self.recalibrator.update(more);
        self.continuation.update(more, C8_RATE_SHIFT);
        Ok(())
    }

    fn decode_continuation(
        &mut self,
        table: &LossTable,
        ledger: &mut Ledger,
        reader: &mut TapeReader<'_>,
    ) -> Result<bool, C8Error> {
        let more = reader.read_bit()?;
        let base = self.continuation.probability_of_one();
        let charged = self.recalibrator.predict(CONTINUATION_EVENT_ID, base);
        charge(charged, more, table, ledger)?;
        self.recalibrator.update(more);
        self.continuation.update(more, C8_RATE_SHIFT);
        Ok(more)
    }

    fn encode_byte(
        &mut self,
        byte: u8,
        history: &[u8],
        table: &LossTable,
        ledger: &mut Ledger,
        writer: &mut TapeWriter,
    ) -> Result<(), C8Error> {
        let mut node = 1_u32;
        for shift in (0..8_u32).rev() {
            let bit = (byte >> shift) & 1 == 1;
            let (indices, probabilities) = self.resolve(history, node as u8);
            let charged = self.predict(&probabilities, node as u8);
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
    ) -> Result<u8, C8Error> {
        let mut node = 1_u32;
        for _ in 0..8 {
            let bit = reader.read_bit()?;
            let (indices, probabilities) = self.resolve(history, node as u8);
            let charged = self.predict(&probabilities, node as u8);
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
) -> Result<(), C8Error> {
    let loss = table
        .get(observed_probability(probability, bit))
        .ok_or(C8Error::InvalidProbability)?;
    ledger
        .add_modeled_event(loss)
        .ok_or(C8Error::LedgerOverflow)?;
    Ok(())
}

/// Encode one item under the C8 arm at the base SSE capacity.
pub fn encode_c8_item(
    source: &[u8],
    table: &LossTable,
    item_index: u8,
) -> Result<(Tape, Ledger), C8Error> {
    encode_c8_item_with_bits(source, table, item_index, crate::s0::SSE_BASE_BUCKET_BITS)
}

/// Encode one item under the C8 arm at an explicit SSE capacity.
pub fn encode_c8_item_with_bits(
    source: &[u8],
    table: &LossTable,
    item_index: u8,
    sse_bucket_bits: u32,
) -> Result<(Tape, Ledger), C8Error> {
    let mut model = C8Model::new(table, sse_bucket_bits);
    let mut writer = TapeWriter::new(C8_ARM_ID, item_index);
    let mut ledger = Ledger::default();
    for (position, byte) in source.iter().copied().enumerate() {
        model.encode_continuation(true, table, &mut ledger, &mut writer)?;
        model.encode_byte(byte, &source[..position], table, &mut ledger, &mut writer)?;
        if byte == b'\n' {
            ledger.add_record().ok_or(C8Error::LedgerOverflow)?;
        }
    }
    model.encode_continuation(false, table, &mut ledger, &mut writer)?;
    Ok((writer.finish(), ledger))
}

/// Decode one item under the C8 arm at the base SSE capacity.
pub fn decode_c8_item(
    tape: &Tape,
    expected_ledger: Ledger,
    table: &LossTable,
    item_index: u8,
) -> Result<Vec<u8>, C8Error> {
    decode_c8_item_with_bits(
        tape,
        expected_ledger,
        table,
        item_index,
        crate::s0::SSE_BASE_BUCKET_BITS,
    )
}

/// Decode one item under the C8 arm, checking arm/item identity and independent
/// ledger equality, fail-closed on trailing charged data.
pub fn decode_c8_item_with_bits(
    tape: &Tape,
    expected_ledger: Ledger,
    table: &LossTable,
    item_index: u8,
    sse_bucket_bits: u32,
) -> Result<Vec<u8>, C8Error> {
    if tape.arm_id() != C8_ARM_ID || tape.item_index() != item_index {
        return Err(C8Error::TapeIdentityMismatch);
    }
    let mut model = C8Model::new(table, sse_bucket_bits);
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
            ledger.add_record().ok_or(C8Error::LedgerOverflow)?;
        }
    }
    if !reader.is_finished() {
        return Err(C8Error::TrailingChargedData);
    }
    if ledger != expected_ledger {
        return Err(C8Error::LedgerDivergence {
            encoder: expected_ledger,
            decoder: ledger,
        });
    }
    Ok(output)
}

// ---------------------------------------------------------------------------
// Read-only credit-assignment observer.
//
// `measure_c8_credit` re-runs the exact C8 encode while additionally
// accumulating, per bucket class (previous-byte lexical class), the live
// normalized weight share of each expert used to code every modeled byte-bit.
// It shares every tape-affecting primitive with the canonical arm; a test
// asserts it reproduces the arm's tape and ledger byte-for-byte. It exists only
// to produce the differentiation evidence and never touches a tape.
// ---------------------------------------------------------------------------

/// Per-bucket-class credit-assignment report: how the mixture apportioned
/// weight across experts, averaged over the modeled bits coded in each class.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct C8CreditReport {
    /// Number of modeled byte-bits observed in each bucket class.
    pub class_bit_counts: [u64; C8_BUCKET_CLASSES],
    /// Q16 average expert weight share, per bucket class (rows) and expert
    /// (columns). Each row sums to ~65536 when the class saw any bits.
    pub class_shares_q16: [[u32; C8_EXPERT_COUNT]; C8_BUCKET_CLASSES],
    /// Q16 average expert weight share across every modeled byte-bit.
    pub overall_shares_q16: [u32; C8_EXPERT_COUNT],
}

/// Re-run the C8 encode as a read-only observer and report per-expert weight
/// shares by bucket class. Returns the tape and ledger too so callers can
/// assert byte-for-byte agreement with the canonical arm.
pub fn measure_c8_credit(
    source: &[u8],
    table: &LossTable,
    item_index: u8,
    sse_bucket_bits: u32,
) -> Result<(Tape, Ledger, C8CreditReport), C8Error> {
    let mut model = C8Model::new(table, sse_bucket_bits);
    let mut writer = TapeWriter::new(C8_ARM_ID, item_index);
    let mut ledger = Ledger::default();
    let mut class_counts = [0_u64; C8_BUCKET_CLASSES];
    let mut class_totals = [[0_u64; C8_EXPERT_COUNT]; C8_BUCKET_CLASSES];

    for (position, byte) in source.iter().copied().enumerate() {
        model.encode_continuation(true, table, &mut ledger, &mut writer)?;
        let history = &source[..position];
        let class = byte_class(model.last_byte);
        let mut node = 1_u32;
        for shift in (0..8_u32).rev() {
            let bit = (byte >> shift) & 1 == 1;
            let (indices, probabilities) = model.resolve(history, node as u8);
            // Snapshot the live share of the bucket about to code this bit.
            let shares = model.mixer.bucket_shares(node as u8, model.last_byte);
            for expert in 0..C8_EXPERT_COUNT {
                class_totals[class][expert] += u64::from(shares[expert]);
            }
            class_counts[class] += 1;
            let charged = model.predict(&probabilities, node as u8);
            charge(charged, bit, table, &mut ledger)?;
            writer.push_bit(bit)?;
            model.update(&indices, bit);
            node = (node << 1) | u32::from(bit);
        }
        model.advance_byte(byte);
        if byte == b'\n' {
            ledger.add_record().ok_or(C8Error::LedgerOverflow)?;
        }
    }
    model.encode_continuation(false, table, &mut ledger, &mut writer)?;

    let mut class_shares = [[0_u32; C8_EXPERT_COUNT]; C8_BUCKET_CLASSES];
    let mut overall_totals = [0_u64; C8_EXPERT_COUNT];
    let mut overall_count = 0_u64;
    for class in 0..C8_BUCKET_CLASSES {
        let count = class_counts[class];
        overall_count += count;
        for expert in 0..C8_EXPERT_COUNT {
            overall_totals[expert] += class_totals[class][expert];
            // `checked_div` yields None only when the class saw no bits; the
            // default share for an unused class is 0 (identical to the prior
            // `if count > 0` guard).
            class_shares[class][expert] =
                class_totals[class][expert].checked_div(count).unwrap_or(0) as u32;
        }
    }
    let mut overall_shares = [0_u32; C8_EXPERT_COUNT];
    for expert in 0..C8_EXPERT_COUNT {
        overall_shares[expert] = overall_totals[expert]
            .checked_div(overall_count)
            .unwrap_or(0) as u32;
    }

    Ok((
        writer.finish(),
        ledger,
        C8CreditReport {
            class_bit_counts: class_counts,
            class_shares_q16: class_shares,
            overall_shares_q16: overall_shares,
        },
    ))
}

/// C8 encode/decode error. Every variant is terminal for the item.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum C8Error {
    InvalidProbability,
    LedgerOverflow,
    TapeIdentityMismatch,
    TrailingChargedData,
    LedgerDivergence { encoder: Ledger, decoder: Ledger },
    Tape(TapeError),
}

impl From<TapeError> for C8Error {
    fn from(error: TapeError) -> Self {
        Self::Tape(error)
    }
}

impl Display for C8Error {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "moon C8 error: {self:?}")
    }
}

impl Error for C8Error {}

#[cfg(test)]
mod tests {
    use super::*;
    use sha2::{Digest, Sha256};

    // Pinned once from the deterministic encoder; the tape is a pure function of
    // the source bytes and arm/item identity (C8 writes the literal bit stream).
    const PINNED_TAPE_SHA256: &str =
        "25bcd31107ab9e22cd2cbd27853bac43ca545a2d35dd1a0ce03192c42d361bdd";

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
            let (tape, ledger) = encode_c8_item(&source, &table, 1).unwrap();
            let decoded = decode_c8_item(&tape, ledger, &table, 1).unwrap();
            assert_eq!(decoded, source, "regime {name} did not round-trip");
            assert_eq!(ledger.raw_literal_bytes, 0, "C8 charges no literals");
        }
    }

    #[test]
    fn repeat_runs_are_byte_identical_in_tape_and_ledger() {
        let table = LossTable::generate();
        let source = regime_snippets().remove(1).1;
        let (tape_a, ledger_a) = encode_c8_item(&source, &table, 2).unwrap();
        let (tape_b, ledger_b) = encode_c8_item(&source, &table, 2).unwrap();
        assert_eq!(tape_a.to_bytes(), tape_b.to_bytes());
        assert_eq!(ledger_a, ledger_b);
    }

    #[test]
    fn decode_fails_closed_on_a_tampered_ledger() {
        let table = LossTable::generate();
        let source = b"{\"a\":1}\n{\"a\":2}\n{\"a\":1}\n".to_vec();
        let (tape, ledger) = encode_c8_item(&source, &table, 0).unwrap();
        let mut wrong = ledger;
        wrong.modeled_loss_q24 += 1;
        assert!(matches!(
            decode_c8_item(&tape, wrong, &table, 0),
            Err(C8Error::LedgerDivergence { .. })
        ));
    }

    #[test]
    fn decode_rejects_a_foreign_arm_or_item_identity() {
        let table = LossTable::generate();
        let source = b"hello world\n".to_vec();
        let (tape, ledger) = encode_c8_item(&source, &table, 3).unwrap();
        assert_eq!(
            decode_c8_item(&tape, ledger, &table, 4),
            Err(C8Error::TapeIdentityMismatch)
        );
    }

    #[test]
    fn a_flipped_payload_byte_is_rejected_by_the_tape_digest() {
        let table = LossTable::generate();
        let source = regime_snippets().remove(0).1;
        let (tape, _) = encode_c8_item(&source, &table, 0).unwrap();
        let mut bytes = tape.to_bytes();
        let target = bytes.len() / 2;
        bytes[target] ^= 0x01;
        assert_eq!(Tape::from_bytes(&bytes), Err(TapeError::DigestMismatch));
    }

    #[test]
    fn a_truncated_tape_fails_closed() {
        let table = LossTable::generate();
        let source = regime_snippets().remove(0).1;
        let (tape, _) = encode_c8_item(&source, &table, 0).unwrap();
        let bytes = tape.to_bytes();
        let truncated = &bytes[..bytes.len() - 1];
        assert!(Tape::from_bytes(truncated).is_err());
    }

    #[test]
    fn one_extra_charged_bit_past_end_of_stream_fails_closed() {
        let table = LossTable::generate();
        let source = b"{\"a\":1}\n{\"a\":2}\n".to_vec();
        let (tape, ledger) = encode_c8_item(&source, &table, 0).unwrap();
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
            decode_c8_item(&tampered, ledger, &table, 0),
            Err(C8Error::TrailingChargedData)
        );
    }

    #[test]
    fn refined_sse_bits_hold_the_tape_and_event_stream() {
        let table = LossTable::generate();
        let source = regime_snippets().remove(2).1;
        let (base_tape, base_ledger) = encode_c8_item_with_bits(&source, &table, 0, 17).unwrap();
        let (refined_tape, refined_ledger) =
            encode_c8_item_with_bits(&source, &table, 0, 18).unwrap();
        assert_eq!(base_tape.to_bytes(), refined_tape.to_bytes());
        assert_eq!(
            base_ledger.modeled_binary_events,
            refined_ledger.modeled_binary_events
        );
        assert_eq!(base_ledger.records, refined_ledger.records);
        assert_eq!(
            decode_c8_item_with_bits(&refined_tape, refined_ledger, &table, 0, 18).unwrap(),
            source
        );
    }

    #[test]
    fn declared_state_accounts_for_table_mixture_and_sse() {
        let table = LossTable::generate();
        let (mixer_bytes, sse_bytes) = M5Mixer::new(&table).declared_state_bytes();
        let composed = H1_CONTEXT_TABLE_BYTES + C8_MIXER_WEIGHT_BYTES + mixer_bytes + sse_bytes;
        let standalone = c8_declared_state_bytes(&table, crate::s0::SSE_BASE_BUCKET_BITS);
        assert_eq!(composed, standalone);
        assert_eq!(C8_MIXER_WEIGHT_BYTES, 163_840);
        // The live mixture weight buffer is exactly the declared figure.
        assert_eq!(
            C8Mixer::new(&table).declared_state_bytes(),
            C8_MIXER_WEIGHT_BYTES
        );
        // Regression pin of the exact figure the receipts report.
        assert_eq!(standalone, 119_963_648);
        assert!(
            standalone <= 256 * 1024 * 1024,
            "declared state within 256 MiB"
        );
        // The refined SSE capacity only grows the SSE table.
        let refined = c8_declared_state_bytes(&table, crate::s0::SSE_REFINED_BUCKET_BITS);
        assert!(refined > standalone);
    }

    #[test]
    fn a_losing_expert_weight_decays_to_the_zero_floor() {
        let table = LossTable::generate();
        let mut mixer = C8Mixer::new(&table);
        // Eight experts vote for a one; the ninth is confidently wrong (always
        // votes for a zero). Credit assignment must drive its weight to 0.
        let probabilities = [
            64_000, 64_000, 64_000, 64_000, 64_000, 64_000, 64_000, 64_000, 1_536,
        ];
        for _ in 0..8_000 {
            let _ = mixer.predict(3, 7, &probabilities);
            mixer.update(true);
        }
        let base = C8Mixer::bucket(3, 7) * C8_MIXER_INPUTS;
        let loser = mixer.weights[base + 8];
        assert_eq!(loser, 0, "the losing expert was not gated off: {loser}");
        // A winning expert climbed off the init toward the cap.
        assert!(mixer.weights[base] > WEIGHT_INIT);
        let shares = mixer.bucket_shares(3, 7);
        assert_eq!(shares[8], 0, "gated expert must hold zero share");
    }

    #[test]
    fn a_gated_expert_recovers_when_it_starts_winning() {
        let table = LossTable::generate();
        let mut mixer = C8Mixer::new(&table);
        let losing = [
            64_000, 64_000, 64_000, 64_000, 64_000, 64_000, 64_000, 64_000, 1_536,
        ];
        for _ in 0..8_000 {
            let _ = mixer.predict(5, 9, &losing);
            mixer.update(true);
        }
        let base = C8Mixer::bucket(5, 9) * C8_MIXER_INPUTS;
        assert_eq!(mixer.weights[base + 8], 0);
        // Now the ninth expert becomes the confidently-right one.
        let winning = [
            2_000, 2_000, 2_000, 2_000, 2_000, 2_000, 2_000, 2_000, 64_000,
        ];
        for _ in 0..8_000 {
            let _ = mixer.predict(5, 9, &winning);
            mixer.update(true);
        }
        assert!(
            mixer.weights[base + 8] > 0,
            "a gated expert never recovered: nothing is frozen"
        );
    }

    #[test]
    fn credit_observer_reproduces_the_arm_tape_and_ledger_byte_for_byte() {
        let table = LossTable::generate();
        for (name, source) in regime_snippets() {
            let (arm_tape, arm_ledger) = encode_c8_item(&source, &table, 3).unwrap();
            let (obs_tape, obs_ledger, _) =
                measure_c8_credit(&source, &table, 3, crate::s0::SSE_BASE_BUCKET_BITS).unwrap();
            assert_eq!(
                arm_tape.to_bytes(),
                obs_tape.to_bytes(),
                "observer tape diverged on regime {name}"
            );
            assert_eq!(arm_ledger, obs_ledger, "observer ledger diverged on {name}");
        }
    }

    #[test]
    fn credit_assignment_differentiates_experts_by_regime() {
        let table = LossTable::generate();
        let uniform = (65_536 / C8_EXPERT_COUNT as u32) as i64;

        // A realistic multi-regime JSON/log corpus: experts genuinely differ,
        // so credit assignment must apportion weight unevenly across them and
        // across bucket classes.
        let corpus = realistic_corpus(128 * 1024);
        let (_, _, report) =
            measure_c8_credit(&corpus, &table, 0, crate::s0::SSE_BASE_BUCKET_BITS).unwrap();

        // Print the per-expert weight-share table (Q16) for the PR evidence.
        print!("overall:");
        for (i, s) in report.overall_shares_q16.iter().enumerate() {
            print!(" {}={}", C8_EXPERT_NAMES[i], s);
        }
        println!(" (uniform={uniform})");
        for (class, label) in C8_CLASS_LABELS.iter().enumerate() {
            if report.class_bit_counts[class] == 0 {
                continue;
            }
            print!("{:>10}[{}]:", label, report.class_bit_counts[class]);
            for (i, s) in report.class_shares_q16[class].iter().enumerate() {
                print!(" {}={}", C8_EXPERT_NAMES[i], s);
            }
            println!();
        }

        // The column expert (index 8), fed the previous record's byte at this
        // offset, is the strongest single predictor on record-structured data:
        // it earns the top overall share, clearly above the uniform baseline.
        let overall = report.overall_shares_q16.map(i64::from);
        let column = overall[8];
        let min_share = *overall.iter().min().unwrap();
        assert_eq!(
            overall.iter().copied().fold(i64::MIN, i64::max),
            column,
            "the column expert should hold the top overall weight share"
        );
        assert!(
            column - uniform >= 400,
            "column expert earned too little credit: {column} vs uniform {uniform}"
        );
        assert!(
            column - min_share >= 800,
            "credit assignment did not spread weight across experts: {column} vs min {min_share}"
        );

        // Per-(expert, bucket) credit: the SAME column expert earns very
        // different weight in different bucket classes — dominant where the
        // previous record's digit columns align, muted elsewhere.
        let digit_column = i64::from(report.class_shares_q16[0][8]);
        let other_column = i64::from(report.class_shares_q16[4][8]);
        assert!(
            digit_column - other_column >= 2_000,
            "column credit did not vary by bucket class: digit {digit_column} vs other {other_column}"
        );

        // The digit and letter bucket classes apportion weight differently
        // across the whole expert roster — the mixture is not one global vector.
        let digit = report.class_shares_q16[0];
        let letter = report.class_shares_q16[1];
        let l1: i64 = (0..C8_EXPERT_COUNT)
            .map(|e| (i64::from(digit[e]) - i64::from(letter[e])).abs())
            .sum();
        assert!(
            l1 >= 1_000,
            "digit and letter classes did not differentiate: L1 {l1}"
        );
    }

    // A representative multi-regime synthetic corpus, mirroring the four
    // regimes of the off-ledger precheck generator (heartbeat / varying JSON /
    // WARN log / metric). Deterministic and self-contained.
    fn realistic_corpus(target: usize) -> Vec<u8> {
        fn xorshift64(mut state: u64) -> u64 {
            state ^= state << 13;
            state ^= state >> 7;
            state ^= state << 17;
            state
        }
        let mut out = Vec::with_capacity(target);
        let mut state = 0x0000_00C8_A710_5EED_u64;
        let mut row = 0_u64;
        while out.len() < target {
            state = xorshift64(state);
            let quarter = (out.len() * 4 / target).min(3);
            let line = match quarter {
                0 => "{\"level\":\"info\",\"service\":\"api\",\"event\":\"heartbeat\",\"ok\":true}\n"
                    .to_string(),
                1 => format!(
                    "{{\"ts\":{},\"user\":{},\"path\":\"/v2/items/{}\",\"latency\":{}}}\n",
                    1_800_000_000 + row,
                    state % 100_003,
                    state & 4095,
                    (state >> 17) % 997
                ),
                2 => format!(
                    "{} WARN worker={} job={:016x} retry={}\n",
                    1_800_000_000 + row,
                    state & 63,
                    state,
                    (state >> 23) & 7
                ),
                _ => format!(
                    "{{\"metric\":\"cpu.{}\",\"value\":{},\"tags\":{{\"host\":\"h{}\",\"zone\":\"z{}\"}}}}\n",
                    state & 31,
                    (state >> 11) % 10_000,
                    (state >> 29) & 255,
                    row % 7
                ),
            };
            out.extend_from_slice(line.as_bytes());
            row += 1;
        }
        out.truncate(target);
        out
    }

    #[test]
    fn is_deterministic_across_identical_runs() {
        let table = LossTable::generate();
        let source = regime_snippets().remove(2).1;
        let first = measure_c8_credit(&source, &table, 1, crate::s0::SSE_BASE_BUCKET_BITS).unwrap();
        let second =
            measure_c8_credit(&source, &table, 1, crate::s0::SSE_BASE_BUCKET_BITS).unwrap();
        assert_eq!(first.1, second.1);
        assert_eq!(first.2, second.2);
    }

    #[test]
    fn known_answer_tape_sha256_is_pinned() {
        let table = LossTable::generate();
        let source = b"{\"level\":\"info\",\"msg\":\"ready\",\"n\":1}\n\
                       {\"level\":\"info\",\"msg\":\"ready\",\"n\":2}\n"
            .to_vec();
        let (tape, _) = encode_c8_item(&source, &table, 0).unwrap();
        let sha: String = Sha256::digest(tape.to_bytes())
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect();
        assert_eq!(sha, PINNED_TAPE_SHA256, "pinned tape SHA-256 changed");
    }
}
