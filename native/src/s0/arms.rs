//! The composed decision and leave-one-out arms of the frozen matrix.
//!
//! Arm 6 (`full`) chains every mechanism: M2 decides first, escapes and
//! ineligible values proceed to M3, then to the terminal M4, with the M5
//! estimator refining every charged probability. Each leave-one-out arm
//! removes exactly its named mechanism and changes nothing else. All five
//! arms allocate the identical M1+M2+M3+M4 context space, so every absolute
//! context index is arm-invariant and unused blocks never charge events.

use super::chassis::{
    decode_chassis_item, decode_chassis_item_with_mixer,
    encode_chassis_item_with_mixer_and_segments, encode_chassis_item_with_segments, ChassisError,
    M1ValueCoder, SegmentSnapshot,
};
use super::m2::M2ValueCoder;
use super::m3::M3ValueCoder;
use super::m4::{m4_contexts, M4ValueCoder};
use super::m5::{M5Mixer, SSE_BASE_BUCKET_BITS};
use super::{Ledger, LossTable, Tape};

pub const FULL_ARM_ID: u8 = 6;
pub const FULL_MINUS_M3_ARM_ID: u8 = 7;
pub const FULL_MINUS_M4_ARM_ID: u8 = 8;
pub const FULL_MINUS_M5_ARM_ID: u8 = 9;

pub(super) fn full_chain() -> M2ValueCoder<M3ValueCoder<M4ValueCoder>> {
    M2ValueCoder::with_inner(M3ValueCoder::with_inner(M4ValueCoder::new()))
}

pub(super) fn minus_m3_chain() -> M2ValueCoder<M4ValueCoder> {
    M2ValueCoder::with_inner(M4ValueCoder::new())
}

pub(super) fn minus_m4_chain() -> M2ValueCoder<M3ValueCoder<M1ValueCoder>> {
    M2ValueCoder::with_inner(M3ValueCoder::with_inner(M1ValueCoder))
}

macro_rules! mixed_arm {
    (
        $encode:ident,
        $encode_segments:ident,
        $encode_bits:ident,
        $decode:ident,
        $decode_bits:ident,
        $arm:expr,
        $chain:expr
    ) => {
        pub fn $encode(
            source: &[u8],
            table: &LossTable,
            item_index: u8,
        ) -> Result<(Tape, Ledger), ChassisError> {
            let (tape, ledger, _) = $encode_segments(source, table, item_index, None)?;
            Ok((tape, ledger))
        }

        pub fn $encode_segments(
            source: &[u8],
            table: &LossTable,
            item_index: u8,
            segment_bytes: Option<u64>,
        ) -> Result<(Tape, Ledger, Vec<SegmentSnapshot>), ChassisError> {
            $encode_bits(
                source,
                table,
                item_index,
                segment_bytes,
                SSE_BASE_BUCKET_BITS,
            )
        }

        pub fn $encode_bits(
            source: &[u8],
            table: &LossTable,
            item_index: u8,
            segment_bytes: Option<u64>,
            sse_bucket_bits: u32,
        ) -> Result<(Tape, Ledger, Vec<SegmentSnapshot>), ChassisError> {
            encode_chassis_item_with_mixer_and_segments(
                source,
                table,
                m4_contexts()?,
                $arm,
                item_index,
                &mut $chain,
                Box::new(M5Mixer::with_sse_bucket_bits(table, sse_bucket_bits)),
                segment_bytes,
            )
        }

        pub fn $decode(
            tape: &Tape,
            expected_ledger: Ledger,
            table: &LossTable,
            expected_item_index: u8,
        ) -> Result<Vec<u8>, ChassisError> {
            $decode_bits(
                tape,
                expected_ledger,
                table,
                expected_item_index,
                SSE_BASE_BUCKET_BITS,
            )
        }

        pub fn $decode_bits(
            tape: &Tape,
            expected_ledger: Ledger,
            table: &LossTable,
            expected_item_index: u8,
            sse_bucket_bits: u32,
        ) -> Result<Vec<u8>, ChassisError> {
            decode_chassis_item_with_mixer(
                tape,
                expected_ledger,
                table,
                m4_contexts()?,
                $arm,
                expected_item_index,
                &mut $chain,
                Box::new(M5Mixer::with_sse_bucket_bits(table, sse_bucket_bits)),
            )
        }
    };
}

mixed_arm!(
    encode_full_item,
    encode_full_item_with_segments,
    encode_full_item_with_bits_and_segments,
    decode_full_item,
    decode_full_item_with_bits,
    FULL_ARM_ID,
    full_chain()
);
mixed_arm!(
    encode_full_minus_m3_item,
    encode_full_minus_m3_item_with_segments,
    encode_full_minus_m3_item_with_bits_and_segments,
    decode_full_minus_m3_item,
    decode_full_minus_m3_item_with_bits,
    FULL_MINUS_M3_ARM_ID,
    minus_m3_chain()
);
mixed_arm!(
    encode_full_minus_m4_item,
    encode_full_minus_m4_item_with_segments,
    encode_full_minus_m4_item_with_bits_and_segments,
    decode_full_minus_m4_item,
    decode_full_minus_m4_item_with_bits,
    FULL_MINUS_M4_ARM_ID,
    minus_m4_chain()
);

pub fn encode_full_minus_m5_item(
    source: &[u8],
    table: &LossTable,
    item_index: u8,
) -> Result<(Tape, Ledger), ChassisError> {
    let (tape, ledger, _) =
        encode_full_minus_m5_item_with_segments(source, table, item_index, None)?;
    Ok((tape, ledger))
}

pub fn encode_full_minus_m5_item_with_segments(
    source: &[u8],
    table: &LossTable,
    item_index: u8,
    segment_bytes: Option<u64>,
) -> Result<(Tape, Ledger, Vec<SegmentSnapshot>), ChassisError> {
    encode_chassis_item_with_segments(
        source,
        table,
        m4_contexts()?,
        FULL_MINUS_M5_ARM_ID,
        item_index,
        &mut full_chain(),
        segment_bytes,
    )
}

pub fn decode_full_minus_m5_item(
    tape: &Tape,
    expected_ledger: Ledger,
    table: &LossTable,
    expected_item_index: u8,
) -> Result<Vec<u8>, ChassisError> {
    decode_chassis_item(
        tape,
        expected_ledger,
        table,
        m4_contexts()?,
        FULL_MINUS_M5_ARM_ID,
        expected_item_index,
        &mut full_chain(),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn corpus() -> Vec<u8> {
        let mut source = Vec::new();
        for index in 0..12_u32 {
            source.extend_from_slice(
                format!(
                    "{{\"id\":{},\"ts\":\"2026-07-22T11:{:02}:00Z\",\"sid\":\"sess-{}\",\"path\":\"/api/orders/{}/lines\",\"raw\":\"#{}!\"}}\n",
                    500 + index,
                    index % 60,
                    index % 3,
                    index % 4,
                    index
                )
                .as_bytes(),
            );
        }
        source.extend_from_slice(b"\n{bad}\n{\"tail\":\"end\"}");
        source
    }

    fn tape_payload(tape: &Tape) -> Vec<u8> {
        let bytes = tape.to_bytes();
        bytes[6..bytes.len() - 32].to_vec()
    }

    #[test]
    fn all_composed_arms_round_trip_exactly_and_deterministically() {
        let table = LossTable::generate();
        let source = corpus();
        type Arm = (
            u8,
            fn(&[u8], &LossTable, u8) -> Result<(Tape, Ledger), ChassisError>,
            fn(&Tape, Ledger, &LossTable, u8) -> Result<Vec<u8>, ChassisError>,
        );
        let arms: [Arm; 4] = [
            (FULL_ARM_ID, encode_full_item, decode_full_item),
            (
                FULL_MINUS_M3_ARM_ID,
                encode_full_minus_m3_item,
                decode_full_minus_m3_item,
            ),
            (
                FULL_MINUS_M4_ARM_ID,
                encode_full_minus_m4_item,
                decode_full_minus_m4_item,
            ),
            (
                FULL_MINUS_M5_ARM_ID,
                encode_full_minus_m5_item,
                decode_full_minus_m5_item,
            ),
        ];
        for (arm, encode, decode) in arms {
            let (tape, ledger) = encode(&source, &table, 0).unwrap();
            assert_eq!(tape.arm_id(), arm);
            assert_eq!(
                decode(&tape, ledger, &table, 0).unwrap(),
                source,
                "arm {arm}"
            );
            let (repeat_tape, repeat_ledger) = encode(&source, &table, 0).unwrap();
            assert_eq!(repeat_tape.to_bytes(), tape.to_bytes(), "arm {arm}");
            assert_eq!(repeat_ledger, ledger, "arm {arm}");
            assert_eq!(
                decode(&tape, ledger, &table, 1),
                Err(ChassisError::TapeIdentityMismatch),
                "arm {arm}"
            );
        }
    }

    #[test]
    fn m5_changes_only_the_loss_of_the_full_grammar() {
        // full and full-minus-m5 share the exact grammar: identical tape
        // payloads and event counts, different charged loss.
        let table = LossTable::generate();
        let source = corpus();
        let (full_tape, full_ledger) = encode_full_item(&source, &table, 0).unwrap();
        let (minus_tape, minus_ledger) = encode_full_minus_m5_item(&source, &table, 0).unwrap();
        assert_eq!(tape_payload(&full_tape), tape_payload(&minus_tape));
        assert_eq!(full_ledger.records, minus_ledger.records);
        assert_eq!(
            full_ledger.modeled_binary_events,
            minus_ledger.modeled_binary_events
        );
        assert_eq!(
            full_ledger.raw_literal_bytes,
            minus_ledger.raw_literal_bytes
        );
        assert_ne!(full_ledger.modeled_loss_q24, minus_ledger.modeled_loss_q24);
    }

    #[test]
    fn leave_one_out_grammars_match_their_mechanism_arms() {
        // full-minus-m3 shares the m1-m2-m4 grammar; full-minus-m4 shares the
        // m1-m2-m3 grammar. Only the M5 loss refinement differs.
        let table = LossTable::generate();
        let source = corpus();

        let (minus_m3_tape, minus_m3_ledger) =
            encode_full_minus_m3_item(&source, &table, 0).unwrap();
        let (m4_tape, m4_ledger) =
            super::super::m4::encode_m1_m2_m4_item(&source, &table, 0).unwrap();
        assert_eq!(tape_payload(&minus_m3_tape), tape_payload(&m4_tape));
        assert_eq!(
            minus_m3_ledger.modeled_binary_events,
            m4_ledger.modeled_binary_events
        );
        assert_ne!(minus_m3_ledger.modeled_loss_q24, m4_ledger.modeled_loss_q24);

        let (minus_m4_tape, minus_m4_ledger) =
            encode_full_minus_m4_item(&source, &table, 0).unwrap();
        let (m3_tape, m3_ledger) =
            super::super::m3::encode_m1_m2_m3_item(&source, &table, 0).unwrap();
        // The m1-m2-m3 arm allocates a smaller context space, but unused
        // contexts never charge events, so the payloads still match.
        assert_eq!(tape_payload(&minus_m4_tape), tape_payload(&m3_tape));
        assert_eq!(
            minus_m4_ledger.modeled_binary_events,
            m3_ledger.modeled_binary_events
        );
        assert_ne!(minus_m4_ledger.modeled_loss_q24, m3_ledger.modeled_loss_q24);
    }

    #[test]
    fn full_arm_stays_within_the_event_budget_on_typical_records() {
        let table = LossTable::generate();
        let source = corpus();
        let (_, ledger) = encode_full_item(&source, &table, 0).unwrap();
        assert!(
            ledger.event_limit_passes(),
            "full arm exceeded 96 events per record: {} events, {} records",
            ledger.modeled_binary_events,
            ledger.records
        );
    }
}
