const Q24_ONE: u128 = 1 << 24;
const BITS_PER_BYTE: u128 = 8;
const MEBIBYTE: u64 = 1 << 20;
const CODER_ALLOWANCE_NUMERATOR: u128 = 5;
const CODER_ALLOWANCE_DENOMINATOR: u128 = 1_000;
const AGGREGATE_BLOCK_ALLOWANCE: u64 = 6_272;
const AGGREGATE_STREAM_METADATA: u64 = 72;
const FIXED_FRAMING: u64 = 4_096;
const ITEM_STREAM_METADATA: u64 = 24;
const BLOCK_ALLOWANCE_PER_MEBIBYTE: u64 = 32;
const EVENT_LIMIT_PER_RECORD: u64 = 96;

pub const KANZI_COMPLETE_BYTES: u64 = 1_712_149;
pub const ADVANCE_MAXIMUM_BYTES: u64 = 1_455_326;
pub const REFINEMENT_MAXIMUM_BYTES: u64 = 1_540_934;

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct Ledger {
    pub records: u64,
    pub modeled_binary_events: u64,
    pub modeled_loss_q24: u64,
    pub raw_literal_bytes: u64,
}

impl Ledger {
    pub fn add_modeled_event(&mut self, loss_q24: u32) -> Option<()> {
        self.modeled_binary_events = self.modeled_binary_events.checked_add(1)?;
        self.modeled_loss_q24 = self.modeled_loss_q24.checked_add(u64::from(loss_q24))?;
        Some(())
    }

    pub fn add_raw_literals(&mut self, bytes: u64) -> Option<()> {
        self.raw_literal_bytes = self.raw_literal_bytes.checked_add(bytes)?;
        Some(())
    }

    pub fn add_record(&mut self) -> Option<()> {
        self.records = self.records.checked_add(1)?;
        Some(())
    }

    #[must_use]
    pub fn event_limit_passes(self) -> bool {
        self.records
            .checked_mul(EVENT_LIMIT_PER_RECORD)
            .is_some_and(|limit| self.modeled_binary_events <= limit)
    }

    fn charged_loss_q24(self) -> Option<u128> {
        let literal_loss = u128::from(self.raw_literal_bytes)
            .checked_mul(BITS_PER_BYTE)?
            .checked_mul(Q24_ONE)?;
        u128::from(self.modeled_loss_q24).checked_add(literal_loss)
    }

    fn payload_bytes(self) -> Option<u64> {
        let divisor = BITS_PER_BYTE * Q24_ONE;
        let payload = div_ceil(self.charged_loss_q24()?, divisor)?;
        u64::try_from(payload).ok()
    }

    pub fn project_aggregate(self) -> Option<Projection> {
        let payload_bytes = self.payload_bytes()?;
        project(
            payload_bytes,
            AGGREGATE_BLOCK_ALLOWANCE,
            AGGREGATE_STREAM_METADATA,
        )
    }

    pub fn project_item(self, source_bytes: u64) -> Option<Projection> {
        let blocks = source_bytes.checked_add(MEBIBYTE - 1)? / MEBIBYTE;
        let block_allowance = blocks.checked_mul(BLOCK_ALLOWANCE_PER_MEBIBYTE)?;
        project(self.payload_bytes()?, block_allowance, ITEM_STREAM_METADATA)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Projection {
    pub payload_bytes: u64,
    pub coder_allowance_bytes: u64,
    pub block_allowance_bytes: u64,
    pub stream_metadata_bytes: u64,
    pub fixed_framing_bytes: u64,
    pub complete_bytes: u64,
}

impl Projection {
    #[must_use]
    pub fn gain_basis_points(self) -> i64 {
        let difference = i128::from(KANZI_COMPLETE_BYTES) - i128::from(self.complete_bytes);
        let basis_points = (difference * 10_000).div_euclid(i128::from(KANZI_COMPLETE_BYTES));
        i64::try_from(basis_points).expect("basis-point result fits i64")
    }

    #[must_use]
    pub fn decision(self) -> Decision {
        if self.complete_bytes <= ADVANCE_MAXIMUM_BYTES {
            Decision::Advance
        } else if self.complete_bytes <= REFINEMENT_MAXIMUM_BYTES {
            Decision::RefineOnce
        } else {
            Decision::Kill
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Decision {
    Advance,
    RefineOnce,
    Kill,
}

fn project(
    payload_bytes: u64,
    block_allowance_bytes: u64,
    stream_metadata_bytes: u64,
) -> Option<Projection> {
    let coder_allowance_u128 = div_ceil(
        u128::from(payload_bytes).checked_mul(CODER_ALLOWANCE_NUMERATOR)?,
        CODER_ALLOWANCE_DENOMINATOR,
    )?;
    let coder_allowance_bytes = u64::try_from(coder_allowance_u128).ok()?;
    let complete_bytes = payload_bytes
        .checked_add(coder_allowance_bytes)?
        .checked_add(block_allowance_bytes)?
        .checked_add(stream_metadata_bytes)?
        .checked_add(FIXED_FRAMING)?;
    Some(Projection {
        payload_bytes,
        coder_allowance_bytes,
        block_allowance_bytes,
        stream_metadata_bytes,
        fixed_framing_bytes: FIXED_FRAMING,
        complete_bytes,
    })
}

fn div_ceil(numerator: u128, denominator: u128) -> Option<u128> {
    if denominator == 0 {
        return None;
    }
    numerator
        .checked_add(denominator - 1)
        .map(|value| value / denominator)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn literal_bytes_are_charged_at_exactly_eight_bits() {
        let ledger = Ledger {
            raw_literal_bytes: 123,
            ..Ledger::default()
        };
        assert_eq!(ledger.payload_bytes(), Some(123));
    }

    #[test]
    fn fractional_loss_and_coder_allowance_round_up() {
        let ledger = Ledger {
            modeled_loss_q24: 8 * (1 << 24) + 1,
            ..Ledger::default()
        };
        let projection = ledger.project_aggregate().unwrap();
        assert_eq!(projection.payload_bytes, 2);
        assert_eq!(projection.coder_allowance_bytes, 1);
        assert_eq!(projection.complete_bytes, 2 + 1 + 6_272 + 72 + 4_096);
    }

    #[test]
    fn item_projection_charges_each_started_source_mebibyte() {
        let ledger = Ledger::default();
        let projection = ledger.project_item((2 << 20) + 1).unwrap();
        assert_eq!(projection.block_allowance_bytes, 96);
        assert_eq!(projection.complete_bytes, 96 + 24 + 4_096);
    }

    #[test]
    fn event_limit_uses_exact_integer_aggregate() {
        let mut ledger = Ledger {
            records: 2,
            modeled_binary_events: 192,
            ..Ledger::default()
        };
        assert!(ledger.event_limit_passes());
        ledger.modeled_binary_events += 1;
        assert!(!ledger.event_limit_passes());
        assert!(Ledger::default().event_limit_passes());
    }

    #[test]
    fn decision_boundaries_match_the_frozen_protocol() {
        for (complete_bytes, expected, gain) in [
            (1_455_326, Decision::Advance, 1_500),
            (1_455_327, Decision::RefineOnce, 1_499),
            (1_540_934, Decision::RefineOnce, 1_000),
            (1_540_935, Decision::Kill, 999),
        ] {
            let projection = Projection {
                payload_bytes: 0,
                coder_allowance_bytes: 0,
                block_allowance_bytes: 0,
                stream_metadata_bytes: 0,
                fixed_framing_bytes: 0,
                complete_bytes,
            };
            assert_eq!(projection.decision(), expected);
            assert_eq!(projection.gain_basis_points(), gain);
        }
    }

    #[test]
    fn expansions_use_mathematical_floor_not_truncation() {
        let projection = Projection {
            payload_bytes: 0,
            coder_allowance_bytes: 0,
            block_allowance_bytes: 0,
            stream_metadata_bytes: 0,
            fixed_framing_bytes: 0,
            complete_bytes: KANZI_COMPLETE_BYTES + 1,
        };
        assert_eq!(projection.gain_basis_points(), -1);
    }
}
