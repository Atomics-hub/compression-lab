//! Moon-local N-input integer logistic mixer for the H1 floor arm.
//!
//! Development-only prescreen infrastructure. This is the real context mixer
//! that makes H1 a fair floor arm: it sums per-context predictions in the
//! log-odds (stretch) domain so agreeing evidence compounds and a
//! confidently-wrong aliased cell can be learned down, which a linear average
//! in the probability domain cannot do. It reconstructs the s0 stretch/squash
//! transform locally from the frozen [`LossTable`] read-only (the s0
//! `build_stretch`/`squash` are private to `m5`), and pins every mixing
//! constant. All arithmetic is integer `i64`; no float, no `HashMap`, fully
//! deterministic. Its output probability feeds the unmodified s0 `M5Mixer` as
//! the base, so the s0 adaptive+SSE stage becomes a recalibration on top.

use crate::s0::{LossTable, MAX_PROBABILITY, MIN_PROBABILITY};

/// Context inputs (the eight shared-table cells) plus one constant-bias input.
pub const MOON_MIXER_INPUTS: usize = 9;
/// Mixing-context buckets: a Q16 weight vector per bucket.
pub const MOON_MIXER_BUCKET_BITS: u32 = 12;
pub const MOON_MIXER_BUCKETS: usize = 1 << MOON_MIXER_BUCKET_BITS;
/// Declared mutable state: `i32` weights, one vector of `MOON_MIXER_INPUTS`
/// per bucket. The derived stretch lookup is a fixed constant table (like the
/// loss table itself) and is not charged, mirroring s0 `M5Mixer`.
pub const MOON_MIXER_WEIGHT_BYTES: usize = MOON_MIXER_BUCKETS * MOON_MIXER_INPUTS * 4;

/// Unit weight in Q16; the per-input initial weight is `WEIGHT_ONE / inputs`.
const WEIGHT_ONE: i32 = 1 << 16;
const WEIGHT_INIT: i32 = WEIGHT_ONE / MOON_MIXER_INPUTS as i32;
/// Weights are clamped to +-2^20 (matches the s0 mixer weight limit).
const WEIGHT_LIMIT: i32 = 1 << 20;
/// Gradient step shift: `delta = (error_q16 * stretch_q24) >> LEARN_SHIFT`
/// (matches the s0 mixer's `LEARN_SHIFT`).
const LEARN_SHIFT: u32 = 34;
/// Stretch values are clamped to +-8.0 log2-odds in Q24 before mixing.
const STRETCH_CLAMP: i64 = 8 << 24;
/// The constant-bias input's stretch value (1.0 log2-odds in Q24); its weight
/// learns the base rate per bucket.
const BIAS_STRETCH: i64 = 1 << 24;

const _: () = assert!(MOON_MIXER_BUCKETS.is_power_of_two());
const _: () = assert!(MOON_MIXER_WEIGHT_BYTES == 4096 * 9 * 4);
const _: () = assert!(WEIGHT_INIT > 0);

struct Scratch {
    base: usize,
    stretches: [i64; MOON_MIXER_INPUTS],
    mixed_probability: i32,
}

/// The moon logistic mixer state.
pub struct MoonMixer {
    stretch: Box<[i32; 65_536]>,
    weights: Box<[i32]>,
    scratch: Option<Scratch>,
}

impl MoonMixer {
    /// Build the mixer with pinned initial weights and a local stretch table.
    #[must_use]
    pub fn new(table: &LossTable) -> Self {
        Self {
            stretch: build_stretch(table),
            weights: vec![WEIGHT_INIT; MOON_MIXER_BUCKETS * MOON_MIXER_INPUTS].into_boxed_slice(),
            scratch: None,
        }
    }

    /// Declared mutable state bytes (the weight table only).
    #[must_use]
    pub fn declared_state_bytes(&self) -> usize {
        self.weights.len() * 4
    }

    /// Select the mixing-context bucket from the byte-bit-tree node XORed with
    /// the low bits of the previous byte. Fixed formula, bounded to the bucket
    /// count.
    fn bucket(node: u8, last_byte: u8) -> usize {
        (((node as usize) << 4) ^ (last_byte as usize)) & (MOON_MIXER_BUCKETS - 1)
    }

    fn stretch_of(&self, probability_of_one: u16) -> i64 {
        i64::from(self.stretch[usize::from(probability_of_one)])
            .clamp(-STRETCH_CLAMP, STRETCH_CLAMP)
    }

    /// Mix the eight context-cell probabilities plus the constant bias into one
    /// probability of a one. Must be followed by exactly one [`update`] with
    /// the observed bit.
    ///
    /// [`update`]: MoonMixer::update
    #[must_use]
    pub fn predict(&mut self, node: u8, last_byte: u8, probabilities: &[u16; 8]) -> u16 {
        let base = Self::bucket(node, last_byte) * MOON_MIXER_INPUTS;
        let mut stretches = [0_i64; MOON_MIXER_INPUTS];
        let mut dot = 0_i64;
        for (input, &probability) in probabilities.iter().enumerate() {
            let stretch = self.stretch_of(probability);
            stretches[input] = stretch;
            dot += i64::from(self.weights[base + input]) * stretch;
        }
        stretches[8] = BIAS_STRETCH;
        dot += i64::from(self.weights[base + 8]) * BIAS_STRETCH;

        let mixed_q24 = (dot >> 16).clamp(-STRETCH_CLAMP, STRETCH_CLAMP);
        let mixed_probability = self.squash(mixed_q24);
        self.scratch = Some(Scratch {
            base,
            stretches,
            mixed_probability,
        });
        (mixed_probability as u32).clamp(u32::from(MIN_PROBABILITY), u32::from(MAX_PROBABILITY))
            as u16
    }

    /// Apply the pinned gradient step for the event predicted immediately
    /// before, preserving charge-before-update: the weights change only after
    /// the bit is observed.
    pub fn update(&mut self, bit: bool) {
        let Some(scratch) = self.scratch.take() else {
            debug_assert!(false, "moon mixer update without a preceding predict");
            return;
        };
        let error = i64::from(if bit { 65_536 } else { 0 } - scratch.mixed_probability);
        for input in 0..MOON_MIXER_INPUTS {
            let delta = ((error * scratch.stretches[input]) >> LEARN_SHIFT) as i32;
            let weight = &mut self.weights[scratch.base + input];
            *weight = (*weight + delta).clamp(-WEIGHT_LIMIT, WEIGHT_LIMIT);
        }
    }

    /// Smallest probability whose stretch reaches `target`, by binary search
    /// over the monotone stretch table (ties resolve to the smallest `p`).
    /// Identical rule to the s0 mixer's squash.
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

/// `stretch(p) = log2(p / (65536 - p))` in Q24, derived exactly from the frozen
/// loss table: `loss(q) = -log2(q / 65536) * 2^24`, so the log-odds is
/// `loss(complement) - loss(p)`. This reconstructs the s0 `m5::build_stretch`
/// locally (that function is private to the frozen module) with no s0 edits.
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stretch_is_monotone_and_antisymmetric() {
        let table = LossTable::generate();
        let mixer = MoonMixer::new(&table);
        assert_eq!(mixer.stretch[32_768], 0);
        for probability in 2..65_536_usize {
            assert!(mixer.stretch[probability] >= mixer.stretch[probability - 1]);
        }
        for probability in [64_usize, 1_000, 20_000, 32_768, 45_536, 65_472] {
            assert_eq!(
                mixer.stretch[probability],
                -mixer.stretch[65_536 - probability]
            );
        }
    }

    #[test]
    fn declared_state_is_the_weight_table_only() {
        let table = LossTable::generate();
        let mixer = MoonMixer::new(&table);
        assert_eq!(mixer.declared_state_bytes(), MOON_MIXER_WEIGHT_BYTES);
        assert_eq!(MOON_MIXER_WEIGHT_BYTES, 147_456);
    }

    #[test]
    fn agreeing_high_inputs_compound_and_learning_saturates() {
        let table = LossTable::generate();
        let mut mixer = MoonMixer::new(&table);
        let probabilities = [64_000_u16; 8];
        let early = mixer.predict(3, 7, &probabilities);
        mixer.update(true);
        for _ in 0..3_000 {
            let _ = mixer.predict(3, 7, &probabilities);
            mixer.update(true);
        }
        let learned = mixer.predict(3, 7, &probabilities);
        mixer.update(true);
        // Eight agreeing high inputs, after learning, drive the estimate toward
        // near-certainty — compounding a linear probability average cannot do.
        assert!(learned > early);
        assert!(
            learned > 65_000,
            "did not compound to near-certainty: {learned}"
        );
    }

    #[test]
    fn a_confidently_wrong_input_is_learned_down() {
        let table = LossTable::generate();
        let mut mixer = MoonMixer::new(&table);
        // Seven inputs vote for a one; the eighth is a confidently-wrong cell
        // that always votes for a zero. The mixer must learn to distrust it.
        let probabilities = [
            64_000, 64_000, 64_000, 64_000, 64_000, 64_000, 64_000, 1_536,
        ];
        for _ in 0..5_000 {
            let _ = mixer.predict(9, 11, &probabilities);
            mixer.update(true);
        }
        let learned = mixer.predict(9, 11, &probabilities);
        mixer.update(true);
        assert!(
            learned > 60_000,
            "the confidently-wrong input was not distrusted: {learned}"
        );
    }

    #[test]
    fn prediction_is_deterministic_across_identical_sequences() {
        fn run() -> Vec<u16> {
            let table = LossTable::generate();
            let mut mixer = MoonMixer::new(&table);
            let mut outputs = Vec::new();
            for value in 0..2_000_u32 {
                let probs = [
                    (value % 65_535 + 1) as u16,
                    ((value * 7) % 65_535 + 1) as u16,
                    ((value * 13) % 65_535 + 1) as u16,
                    ((value * 17) % 65_535 + 1) as u16,
                    ((value * 19) % 65_535 + 1) as u16,
                    ((value * 23) % 65_535 + 1) as u16,
                    ((value * 29) % 65_535 + 1) as u16,
                    ((value * 31) % 65_535 + 1) as u16,
                ];
                outputs.push(mixer.predict((value % 251) as u8, (value % 253) as u8, &probs));
                mixer.update(value % 2 == 0);
            }
            outputs
        }
        assert_eq!(run(), run());
    }
}
