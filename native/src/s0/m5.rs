//! M5: fixed-point predictor mixing plus one SSE stage.
//!
//! M5 never changes event grammar, event counts, or tape bits: it refines the
//! probability charged for each modeled binary event. Every rate, rounding
//! rule, table size, and bin is pinned here as an integer constant. The
//! stretch domain is Q24 log2-odds derived exactly from the frozen loss
//! table, so the whole estimator is integer-only and deterministic.

use super::chassis::{
    decode_chassis_item_with_mixer, encode_chassis_item_with_mixer, ChassisError, M1ValueCoder,
};
use super::m2::{m2_contexts, M2ValueCoder};
use super::template::{fnv1a64, fnv1a64_extend};
use super::{Ledger, LossTable, Probability, Tape, MAX_PROBABILITY, MIN_PROBABILITY};

pub const M5_ARM_ID: u8 = 5;

/// Mixing weights are Q16; the second input starts switched off.
const WEIGHT_ONE: i32 = 1 << 16;
const WEIGHT_LIMIT: i32 = 1 << 20;
/// Gradient step: `delta = (error_q16 * stretch_q24) >> LEARN_SHIFT`.
const LEARN_SHIFT: u32 = 34;
/// Adaptive-input and SSE probability update rate (same shift as the base
/// context models).
const M5_RATE_SHIFT: u32 = 5;
/// Stretch values are clamped to +-8.0 in Q24 log2-odds before mixing.
const STRETCH_CLAMP: i64 = 8 << 24;
/// SSE interpolates across 33 nodes spanning the clamped stretch range.
pub const SSE_NODES: usize = 33;

pub const MIXER_BUCKET_BITS: u32 = 20;
pub const MIXER_BUCKETS: usize = 1 << MIXER_BUCKET_BITS;
/// Base-manifest SSE sizing. The single predeclared refinement raises only
/// the SSE table maximum (16 MiB to 24 MiB), which admits one more bucket bit.
pub const SSE_BASE_BUCKET_BITS: u32 = 17;
pub const SSE_REFINED_BUCKET_BITS: u32 = 18;

pub const MIXER_TABLE_BYTES_MAXIMUM: usize = 16_777_216;
pub const SSE_TABLE_BYTES_MAXIMUM: usize = 16_777_216;
pub const SSE_TABLE_BYTES_REFINED_MAXIMUM: usize = 25_165_824;

/// Per-bucket mixer state: two Q16 weights plus the adaptive second input.
const MIXER_ENTRY_BYTES: usize = 4 + 4 + 2;
const _: () = assert!(MIXER_BUCKETS * MIXER_ENTRY_BYTES <= MIXER_TABLE_BYTES_MAXIMUM);
const _: () = assert!((1 << SSE_BASE_BUCKET_BITS) * SSE_NODES * 2 <= SSE_TABLE_BYTES_MAXIMUM);
const _: () =
    assert!((1 << SSE_REFINED_BUCKET_BITS) * SSE_NODES * 2 <= SSE_TABLE_BYTES_REFINED_MAXIMUM);
const _: () = assert!((1 << SSE_REFINED_BUCKET_BITS) * SSE_NODES * 2 > SSE_TABLE_BYTES_MAXIMUM);

struct Scratch {
    mixer_bucket: usize,
    stretch_base: i64,
    stretch_adaptive: i64,
    mixed_probability: i32,
    sse_cell: usize,
}

/// The complete M5 estimator state for one item and one arm side.
pub struct M5Mixer {
    stretch: Box<[i32; 65_536]>,
    weights_base: Box<[i32]>,
    weights_adaptive: Box<[i32]>,
    adaptive: Box<[Probability]>,
    sse: Box<[Probability]>,
    sse_bucket_mask: u64,
    scratch: Option<Scratch>,
}

impl M5Mixer {
    /// Build the estimator with the pinned base capacity.
    #[must_use]
    pub fn new(table: &LossTable) -> Self {
        Self::with_sse_bucket_bits(table, SSE_BASE_BUCKET_BITS)
    }

    /// The predeclared one-time capacity refinement changes only this
    /// parameter (and the context-table maximum handled elsewhere).
    #[must_use]
    pub fn with_sse_bucket_bits(table: &LossTable, sse_bucket_bits: u32) -> Self {
        let stretch = build_stretch(table);
        let sse_buckets = 1_usize << sse_bucket_bits;
        Self {
            stretch,
            weights_base: vec![WEIGHT_ONE; MIXER_BUCKETS].into_boxed_slice(),
            weights_adaptive: vec![0; MIXER_BUCKETS].into_boxed_slice(),
            adaptive: vec![Probability::default(); MIXER_BUCKETS].into_boxed_slice(),
            sse: vec![Probability::default(); sse_buckets * SSE_NODES].into_boxed_slice(),
            sse_bucket_mask: (sse_buckets - 1) as u64,
            scratch: None,
        }
    }

    /// Logical table bytes for the frozen accounting (mixer weights plus
    /// adaptive inputs, and the SSE cells). Actual RSS is measured by the
    /// runner.
    #[must_use]
    pub fn declared_state_bytes(&self) -> (usize, usize) {
        (MIXER_BUCKETS * MIXER_ENTRY_BYTES, self.sse.len() * 2)
    }

    /// Refine the base probability for one charged event. Must be followed by
    /// exactly one `update` with the observed bit.
    #[must_use]
    pub fn predict(&mut self, id: u64, base_probability_of_one: u16) -> u16 {
        let hash = fnv1a64_extend(fnv1a64(b"s0-m5-event"), &id.to_le_bytes());
        let mixer_bucket = (hash & (MIXER_BUCKETS as u64 - 1)) as usize;
        let sse_bucket = ((hash >> MIXER_BUCKET_BITS) & self.sse_bucket_mask) as usize;

        let stretch_base = self.stretch_of(base_probability_of_one);
        let stretch_adaptive = self.stretch_of(self.adaptive[mixer_bucket].probability_of_one());
        let mixed_q24 = ((i64::from(self.weights_base[mixer_bucket]) * stretch_base
            + i64::from(self.weights_adaptive[mixer_bucket]) * stretch_adaptive)
            >> 16)
            .clamp(-STRETCH_CLAMP, STRETCH_CLAMP);
        let mixed_probability = self.squash(mixed_q24);

        // Interpolated SSE over the clamped stretch range: locate the node
        // pair, blend their cells in 16-bit fixed point, and remember the
        // nearer cell for the update.
        let span = 2 * STRETCH_CLAMP as u128;
        let offset = (mixed_q24 + STRETCH_CLAMP) as u128;
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

        // Final estimate: three parts recalibrated SSE, one part mixer.
        let final_probability = ((3 * interpolated + mixed_probability as u32) / 4)
            .clamp(u32::from(MIN_PROBABILITY), u32::from(MAX_PROBABILITY))
            as u16;

        self.scratch = Some(Scratch {
            mixer_bucket,
            stretch_base,
            stretch_adaptive,
            mixed_probability,
            sse_cell: if fraction >= 32_768 {
                base_cell + 1
            } else {
                base_cell
            },
        });
        final_probability
    }

    /// Apply the pinned updates for the event predicted immediately before.
    pub fn update(&mut self, bit: bool) {
        let Some(scratch) = self.scratch.take() else {
            debug_assert!(false, "M5 update without a preceding predict");
            return;
        };
        let error = i64::from(if bit { 65_536 } else { 0 } - scratch.mixed_probability);
        let base_delta = ((error * scratch.stretch_base) >> LEARN_SHIFT) as i32;
        let adaptive_delta = ((error * scratch.stretch_adaptive) >> LEARN_SHIFT) as i32;
        let weights_base = &mut self.weights_base[scratch.mixer_bucket];
        *weights_base = (*weights_base + base_delta).clamp(-WEIGHT_LIMIT, WEIGHT_LIMIT);
        let weights_adaptive = &mut self.weights_adaptive[scratch.mixer_bucket];
        *weights_adaptive = (*weights_adaptive + adaptive_delta).clamp(-WEIGHT_LIMIT, WEIGHT_LIMIT);
        self.adaptive[scratch.mixer_bucket].update(bit, M5_RATE_SHIFT);
        self.sse[scratch.sse_cell].update(bit, M5_RATE_SHIFT);
    }

    fn stretch_of(&self, probability_of_one: u16) -> i64 {
        i64::from(self.stretch[usize::from(probability_of_one)])
            .clamp(-STRETCH_CLAMP, STRETCH_CLAMP)
    }

    /// Smallest probability whose stretch reaches `target`, by binary search
    /// over the monotone stretch table; clamped to the valid open interval.
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

/// `stretch(p) = log2(p / (65536 - p))` in Q24, derived exactly from the
/// frozen loss table: `loss(q) = -log2(q / 65536) * 2^24`, so the log-odds is
/// `loss(complement) - loss(p)`. Entries 0 and 65,535 reuse their neighbors
/// (those probabilities are unreachable through the clamped models).
fn build_stretch(table: &LossTable) -> Box<[i32; 65_536]> {
    let mut values = vec![0_i32; 65_536].into_boxed_slice();
    for probability in 1..65_536_u32 {
        let loss_one = table.get(probability).expect("in range");
        let loss_zero = table.get(65_536 - probability).expect("in range");
        values[probability as usize] = loss_zero as i32 - loss_one as i32;
    }
    values[0] = values[1];
    let boxed: Box<[i32; 65_536]> = values
        .try_into()
        .unwrap_or_else(|_| unreachable!("stretch table length is constant"));
    boxed
}

pub fn encode_m1_m2_m5_item(
    source: &[u8],
    table: &LossTable,
    item_index: u8,
) -> Result<(Tape, Ledger), ChassisError> {
    encode_chassis_item_with_mixer(
        source,
        table,
        m2_contexts()?,
        M5_ARM_ID,
        item_index,
        &mut M2ValueCoder::with_inner(M1ValueCoder),
        Box::new(M5Mixer::new(table)),
    )
}

pub fn decode_m1_m2_m5_item(
    tape: &Tape,
    expected_ledger: Ledger,
    table: &LossTable,
    expected_item_index: u8,
) -> Result<Vec<u8>, ChassisError> {
    decode_chassis_item_with_mixer(
        tape,
        expected_ledger,
        table,
        m2_contexts()?,
        M5_ARM_ID,
        expected_item_index,
        &mut M2ValueCoder::with_inner(M1ValueCoder),
        Box::new(M5Mixer::new(table)),
    )
}

#[cfg(test)]
mod tests {
    use super::super::m2::encode_m1_m2_item;
    use super::*;

    #[test]
    fn m5_changes_only_the_charged_loss_never_grammar_or_tape_bits() {
        let table = LossTable::generate();
        let mut source = Vec::new();
        for index in 0..30 {
            source.extend_from_slice(
                format!(
                    "{{\"id\":{},\"ts\":\"2026-07-22T10:00:{:02}Z\",\"msg\":\"m{}\"}}\n",
                    100 + index,
                    index % 60,
                    index % 4
                )
                .as_bytes(),
            );
        }
        source.extend_from_slice(b"\n{bad}\n{\"tail\":true}");

        let (m2_tape, m2_ledger) = encode_m1_m2_item(&source, &table, 0).unwrap();
        let (m5_tape, m5_ledger) = encode_m1_m2_m5_item(&source, &table, 0).unwrap();

        // Identical bit stream and literals: only the header arm byte and the
        // digest may differ.
        let m2_bytes = m2_tape.to_bytes();
        let m5_bytes = m5_tape.to_bytes();
        assert_eq!(m2_bytes.len(), m5_bytes.len());
        assert_eq!(
            m2_bytes[6..m2_bytes.len() - 32],
            m5_bytes[6..m5_bytes.len() - 32]
        );
        assert_eq!(m5_ledger.records, m2_ledger.records);
        assert_eq!(
            m5_ledger.modeled_binary_events,
            m2_ledger.modeled_binary_events
        );
        assert_eq!(m5_ledger.raw_literal_bytes, m2_ledger.raw_literal_bytes);
        assert_ne!(m5_ledger.modeled_loss_q24, m2_ledger.modeled_loss_q24);
    }

    #[test]
    fn m5_arm_round_trips_exactly_and_deterministically() {
        let table = LossTable::generate();
        let source = b"{\"a\":1,\"b\":\"x\"}\n{\"a\":2,\"b\":\"y\"}\n{\"a\":3,\"b\":\"x\"}\n";
        let (tape, ledger) = encode_m1_m2_m5_item(source, &table, 1).unwrap();
        assert_eq!(
            decode_m1_m2_m5_item(&tape, ledger, &table, 1).unwrap(),
            source
        );
        let (repeat_tape, repeat_ledger) = encode_m1_m2_m5_item(source, &table, 1).unwrap();
        assert_eq!(repeat_tape.to_bytes(), tape.to_bytes());
        assert_eq!(repeat_ledger, ledger);
    }

    #[test]
    fn decoder_ledger_equality_covers_the_refined_loss() {
        // Decoding with a mismatched estimator (none at all) must fail the
        // independent ledger equality, proving the loss is reproduced, not
        // copied.
        let table = LossTable::generate();
        let source = b"{\"a\":1}\n{\"a\":2}\n";
        let (tape, ledger) = encode_m1_m2_m5_item(source, &table, 2).unwrap();
        let result = super::super::chassis::decode_chassis_item(
            &tape,
            ledger,
            &table,
            m2_contexts().unwrap(),
            M5_ARM_ID,
            2,
            &mut M2ValueCoder::with_inner(M1ValueCoder),
        );
        assert!(matches!(
            result,
            Err(ChassisError::Event(
                super::super::EventError::LedgerDivergence { .. }
            ))
        ));
    }

    #[test]
    fn arm_and_item_identity_are_bound() {
        let table = LossTable::generate();
        let source = b"{\"a\":1}\n";
        let (tape, ledger) = encode_m1_m2_m5_item(source, &table, 3).unwrap();
        assert_eq!(
            decode_m1_m2_m5_item(&tape, ledger, &table, 4),
            Err(ChassisError::TapeIdentityMismatch)
        );
        let (m2_tape, m2_ledger) = encode_m1_m2_item(source, &table, 3).unwrap();
        assert_eq!(
            decode_m1_m2_m5_item(&m2_tape, m2_ledger, &table, 3),
            Err(ChassisError::TapeIdentityMismatch)
        );
    }

    #[test]
    fn stretch_and_squash_are_monotone_and_mutually_consistent() {
        let table = LossTable::generate();
        let mixer = M5Mixer::new(&table);
        assert_eq!(mixer.stretch[32_768], 0);
        for probability in 2..65_536_usize {
            assert!(mixer.stretch[probability] >= mixer.stretch[probability - 1]);
        }
        // Antisymmetry of log-odds around one half.
        for probability in [64_usize, 1_000, 20_000, 32_768, 45_536, 65_472] {
            assert_eq!(
                mixer.stretch[probability],
                -mixer.stretch[65_536 - probability]
            );
        }
        for probability in [64_u16, 1_000, 8_192, 32_768, 50_000, 65_472] {
            let target = i64::from(mixer.stretch[usize::from(probability)]);
            let recovered = mixer.squash(target);
            assert_eq!(
                i64::from(mixer.stretch[recovered as usize]),
                target,
                "squash lost the stretch value for {probability}"
            );
        }
    }

    #[test]
    fn table_budgets_respect_the_frozen_maxima() {
        let table = LossTable::generate();
        let base = M5Mixer::new(&table);
        let (mixer_bytes, sse_bytes) = base.declared_state_bytes();
        assert!(mixer_bytes <= MIXER_TABLE_BYTES_MAXIMUM);
        assert!(sse_bytes <= SSE_TABLE_BYTES_MAXIMUM);
        let refined = M5Mixer::with_sse_bucket_bits(&table, SSE_REFINED_BUCKET_BITS);
        let (_, refined_sse_bytes) = refined.declared_state_bytes();
        assert!(refined_sse_bytes > SSE_TABLE_BYTES_MAXIMUM);
        assert!(refined_sse_bytes <= SSE_TABLE_BYTES_REFINED_MAXIMUM);
    }

    #[test]
    fn estimator_learns_a_strongly_biased_context() {
        // After warmup on constant-one bits the estimator must be highly
        // confident. The squash ceiling (+-8 log2-odds) keeps the blended
        // estimate a hair under the saturated base clamp by design, so the
        // bound checks learned confidence, not clamp equality.
        let table = LossTable::generate();
        let mut mixer = M5Mixer::new(&table);
        let mut base = Probability::default();
        let mut early = 0_u16;
        for round in 0..2_000 {
            let refined = mixer.predict(42, base.probability_of_one());
            if round == 0 {
                early = refined;
            }
            mixer.update(true);
            base.update(true, 5);
        }
        let refined = mixer.predict(42, base.probability_of_one());
        mixer.update(true);
        assert!(early < 40_000, "first prediction was already saturated");
        assert!(refined > 65_000, "estimator failed to learn: {refined}");
    }
}
