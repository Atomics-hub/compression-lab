//! The frozen ten-arm dispatch of the S0 screen.
//!
//! Arm identifiers, names, and order are pinned to the frozen protocol. The
//! dispatcher only routes to the per-arm entry points; it never constructs a
//! coder chain or context space itself, so it cannot drift from the arms it
//! names. Segment snapshots are diagnostic-only and close at the first record
//! boundary at or after each [`SEGMENT_BYTES`] interval.

use super::arms::{
    encode_full_item_with_segments, encode_full_minus_m3_item_with_segments,
    encode_full_minus_m4_item_with_segments, encode_full_minus_m5_item_with_segments,
};
use super::chassis::{ChassisError, SegmentSnapshot};
use super::m1::encode_m1_item_with_segments;
use super::m2::encode_m1_m2_item_with_segments;
use super::m3::encode_m1_m2_m3_item_with_segments;
use super::m4::encode_m1_m2_m4_item_with_segments;
use super::m5::encode_m1_m2_m5_item_with_segments;
use super::raw::encode_raw_o3_item_with_segments;
use super::{
    decode_full_item, decode_full_minus_m3_item, decode_full_minus_m4_item,
    decode_full_minus_m5_item, decode_m1_item, decode_m1_m2_item, decode_m1_m2_m3_item,
    decode_m1_m2_m4_item, decode_m1_m2_m5_item, decode_raw_o3_item, Ledger, LossTable, Tape,
};

/// The frozen diagnostic segment interval: 16 MiB of consumed source.
pub const SEGMENT_BYTES: u64 = 16_777_216;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Arm {
    RawO3,
    M1Chassis,
    M1M2,
    M1M2M3,
    M1M2M4,
    M1M2M5,
    Full,
    FullMinusM3,
    FullMinusM4,
    FullMinusM5,
}

/// Every arm in the frozen measurement order.
pub const ARMS: [Arm; 10] = [
    Arm::RawO3,
    Arm::M1Chassis,
    Arm::M1M2,
    Arm::M1M2M3,
    Arm::M1M2M4,
    Arm::M1M2M5,
    Arm::Full,
    Arm::FullMinusM3,
    Arm::FullMinusM4,
    Arm::FullMinusM5,
];

impl Arm {
    #[must_use]
    pub fn id(self) -> u8 {
        match self {
            Arm::RawO3 => super::RAW_ARM_ID,
            Arm::M1Chassis => super::M1_ARM_ID,
            Arm::M1M2 => super::M2_ARM_ID,
            Arm::M1M2M3 => super::M3_ARM_ID,
            Arm::M1M2M4 => super::M4_ARM_ID,
            Arm::M1M2M5 => super::M5_ARM_ID,
            Arm::Full => super::FULL_ARM_ID,
            Arm::FullMinusM3 => super::FULL_MINUS_M3_ARM_ID,
            Arm::FullMinusM4 => super::FULL_MINUS_M4_ARM_ID,
            Arm::FullMinusM5 => super::FULL_MINUS_M5_ARM_ID,
        }
    }

    /// The frozen protocol arm identifier string.
    #[must_use]
    pub fn name(self) -> &'static str {
        match self {
            Arm::RawO3 => "raw-o3",
            Arm::M1Chassis => "m1-chassis",
            Arm::M1M2 => "m1-m2",
            Arm::M1M2M3 => "m1-m2-m3",
            Arm::M1M2M4 => "m1-m2-m4",
            Arm::M1M2M5 => "m1-m2-m5",
            Arm::Full => "full",
            Arm::FullMinusM3 => "full-minus-m3",
            Arm::FullMinusM4 => "full-minus-m4",
            Arm::FullMinusM5 => "full-minus-m5",
        }
    }

    #[must_use]
    pub fn from_name(name: &str) -> Option<Self> {
        ARMS.into_iter().find(|arm| arm.name() == name)
    }

    /// Only the full arm can trigger advance, refinement, or kill; the other
    /// nine are attribution-only diagnostics (with the independent
    /// full-minus-m4 quarantine gate applied by the runner).
    #[must_use]
    pub fn decides(self) -> bool {
        self == Arm::Full
    }

    /// The frozen per-record event budget applies to the full arm only.
    #[must_use]
    pub fn event_limit_applies(self) -> bool {
        self == Arm::Full
    }
}

pub fn encode_arm_item(
    arm: Arm,
    source: &[u8],
    table: &LossTable,
    item_index: u8,
    segment_bytes: Option<u64>,
) -> Result<(Tape, Ledger, Vec<SegmentSnapshot>), ChassisError> {
    let encode = match arm {
        Arm::RawO3 => encode_raw_o3_item_with_segments,
        Arm::M1Chassis => encode_m1_item_with_segments,
        Arm::M1M2 => encode_m1_m2_item_with_segments,
        Arm::M1M2M3 => encode_m1_m2_m3_item_with_segments,
        Arm::M1M2M4 => encode_m1_m2_m4_item_with_segments,
        Arm::M1M2M5 => encode_m1_m2_m5_item_with_segments,
        Arm::Full => encode_full_item_with_segments,
        Arm::FullMinusM3 => encode_full_minus_m3_item_with_segments,
        Arm::FullMinusM4 => encode_full_minus_m4_item_with_segments,
        Arm::FullMinusM5 => encode_full_minus_m5_item_with_segments,
    };
    encode(source, table, item_index, segment_bytes)
}

pub fn decode_arm_item(
    arm: Arm,
    tape: &Tape,
    expected_ledger: Ledger,
    table: &LossTable,
    expected_item_index: u8,
) -> Result<Vec<u8>, ChassisError> {
    let decode = match arm {
        Arm::RawO3 => decode_raw_o3_item,
        Arm::M1Chassis => decode_m1_item,
        Arm::M1M2 => decode_m1_m2_item,
        Arm::M1M2M3 => decode_m1_m2_m3_item,
        Arm::M1M2M4 => decode_m1_m2_m4_item,
        Arm::M1M2M5 => decode_m1_m2_m5_item,
        Arm::Full => decode_full_item,
        Arm::FullMinusM3 => decode_full_minus_m3_item,
        Arm::FullMinusM4 => decode_full_minus_m4_item,
        Arm::FullMinusM5 => decode_full_minus_m5_item,
    };
    decode(tape, expected_ledger, table, expected_item_index)
}

#[cfg(test)]
mod tests {
    use super::super::{
        encode_full_item, encode_full_minus_m3_item, encode_full_minus_m4_item,
        encode_full_minus_m5_item, encode_m1_item, encode_m1_m2_item, encode_m1_m2_m3_item,
        encode_m1_m2_m4_item, encode_m1_m2_m5_item, encode_raw_o3_item,
    };
    use super::*;

    fn corpus() -> Vec<u8> {
        let mut source = Vec::new();
        for index in 0..24_u32 {
            source.extend_from_slice(
                format!(
                    "{{\"id\":{},\"ts\":\"2026-07-22T09:{:02}:00Z\",\"sid\":\"sess-{}\",\"msg\":\"event {}\"}}\n",
                    9_000 + index,
                    index % 60,
                    index % 5,
                    index
                )
                .as_bytes(),
            );
        }
        source.extend_from_slice(b"\n{bad}\n{\"tail\":1}");
        source
    }

    #[test]
    fn arm_ids_names_and_order_match_the_frozen_protocol() {
        let expected: [(u8, &str); 10] = [
            (0, "raw-o3"),
            (1, "m1-chassis"),
            (2, "m1-m2"),
            (3, "m1-m2-m3"),
            (4, "m1-m2-m4"),
            (5, "m1-m2-m5"),
            (6, "full"),
            (7, "full-minus-m3"),
            (8, "full-minus-m4"),
            (9, "full-minus-m5"),
        ];
        for (index, (id, name)) in expected.into_iter().enumerate() {
            let arm = ARMS[index];
            assert_eq!(arm.id(), id);
            assert_eq!(arm.name(), name);
            assert_eq!(Arm::from_name(name), Some(arm));
            assert_eq!(arm.decides(), name == "full");
            assert_eq!(arm.event_limit_applies(), name == "full");
        }
        assert_eq!(Arm::from_name("m6"), None);
        assert_eq!(SEGMENT_BYTES, 16_777_216);
    }

    #[test]
    fn dispatch_matches_every_arm_entry_point_byte_for_byte() {
        let table = LossTable::generate();
        let source = corpus();
        type Entry = fn(&[u8], &LossTable, u8) -> Result<(Tape, Ledger), ChassisError>;
        let entries: [Entry; 10] = [
            encode_raw_o3_item,
            encode_m1_item,
            encode_m1_m2_item,
            encode_m1_m2_m3_item,
            encode_m1_m2_m4_item,
            encode_m1_m2_m5_item,
            encode_full_item,
            encode_full_minus_m3_item,
            encode_full_minus_m4_item,
            encode_full_minus_m5_item,
        ];
        for (arm, entry) in ARMS.into_iter().zip(entries) {
            let (entry_tape, entry_ledger) = entry(&source, &table, 2).unwrap();
            let (tape, ledger, snapshots) = encode_arm_item(arm, &source, &table, 2, None).unwrap();
            assert_eq!(tape.to_bytes(), entry_tape.to_bytes(), "{}", arm.name());
            assert_eq!(ledger, entry_ledger, "{}", arm.name());
            assert!(snapshots.is_empty(), "{}", arm.name());
            assert_eq!(
                decode_arm_item(arm, &tape, ledger, &table, 2).unwrap(),
                source,
                "{}",
                arm.name()
            );
            assert_eq!(
                decode_arm_item(arm, &tape, ledger, &table, 3),
                Err(ChassisError::TapeIdentityMismatch),
                "{}",
                arm.name()
            );
        }
    }

    #[test]
    fn segment_snapshots_never_change_the_tape_and_close_on_record_boundaries() {
        let table = LossTable::generate();
        let source = corpus();
        for arm in ARMS {
            let (plain_tape, plain_ledger, _) =
                encode_arm_item(arm, &source, &table, 0, None).unwrap();
            let (tape, ledger, snapshots) =
                encode_arm_item(arm, &source, &table, 0, Some(64)).unwrap();
            assert_eq!(tape.to_bytes(), plain_tape.to_bytes(), "{}", arm.name());
            assert_eq!(ledger, plain_ledger, "{}", arm.name());
            assert!(!snapshots.is_empty(), "{}", arm.name());

            // Snapshots land exactly on record boundaries, strictly increase,
            // and each closes at the first boundary at or after a multiple of
            // the interval.
            let mut boundaries = Vec::new();
            let mut offset = 0_u64;
            for record in super::super::split_records(&source) {
                offset += record.content.len() as u64 + u64::from(record.terminated);
                boundaries.push(offset);
            }
            let mut previous_bytes = 0;
            let mut previous_records = 0;
            for snapshot in &snapshots {
                assert!(
                    boundaries.contains(&snapshot.source_bytes),
                    "{}",
                    arm.name()
                );
                assert!(snapshot.source_bytes > previous_bytes, "{}", arm.name());
                assert!(snapshot.records > previous_records, "{}", arm.name());
                let interval_index = previous_bytes / 64;
                assert!(
                    snapshot.source_bytes >= (interval_index + 1) * 64,
                    "{}",
                    arm.name()
                );
                previous_bytes = snapshot.source_bytes;
                previous_records = snapshot.records;
            }

            // The final snapshot ledger never exceeds the finished ledger.
            let last = snapshots.last().unwrap();
            assert!(last.ledger.modeled_binary_events <= ledger.modeled_binary_events);
            assert!(last.ledger.modeled_loss_q24 <= ledger.modeled_loss_q24);
            assert!(last.ledger.raw_literal_bytes <= ledger.raw_literal_bytes);
        }
    }

    #[test]
    fn an_interval_beyond_the_source_produces_no_snapshots() {
        let table = LossTable::generate();
        let source = corpus();
        for arm in [Arm::RawO3, Arm::M1Chassis, Arm::Full] {
            let (_, _, snapshots) =
                encode_arm_item(arm, &source, &table, 0, Some(1 << 30)).unwrap();
            assert!(snapshots.is_empty(), "{}", arm.name());
            let (_, _, empty) = encode_arm_item(arm, b"", &table, 0, Some(64)).unwrap();
            assert!(empty.is_empty(), "{}", arm.name());
        }
    }

    #[test]
    fn one_record_spanning_many_intervals_closes_a_single_snapshot() {
        let table = LossTable::generate();
        // One 4,096-byte fallback record followed by two tiny records: every
        // 64-byte interval inside the first record collapses to its single
        // closing boundary, and the next snapshot waits for the first record
        // boundary at or after the next uncovered interval (4,160).
        let mut source = vec![b'x'; 4_096];
        source.push(b'\n');
        source.extend_from_slice(b"{\"a\":1}\n");
        source.extend_from_slice(&b"{\"a\":2}\n".repeat(8));
        let (_, _, snapshots) =
            encode_arm_item(Arm::M1Chassis, &source, &table, 0, Some(64)).unwrap();
        assert_eq!(snapshots.len(), 2);
        assert_eq!(snapshots[0].source_bytes, 4_097);
        assert_eq!(snapshots[0].records, 1);
        assert_eq!(snapshots[1].source_bytes, 4_161);
        assert_eq!(snapshots[1].records, 9);
    }
}
