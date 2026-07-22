//! M1 arm entry points: the shared chassis with the default M1 value coder.

use super::chassis::{chassis_contexts, decode_chassis_item, encode_chassis_item, M1ValueCoder};
use super::{Ledger, LossTable, Tape};

pub use super::chassis::ChassisError as M1Error;

pub const M1_ARM_ID: u8 = 1;

pub fn encode_m1_item(
    source: &[u8],
    table: &LossTable,
    item_index: u8,
) -> Result<(Tape, Ledger), M1Error> {
    encode_chassis_item(
        source,
        table,
        chassis_contexts(0, &[])?,
        M1_ARM_ID,
        item_index,
        &mut M1ValueCoder,
    )
}

pub fn decode_m1_item(
    tape: &Tape,
    expected_ledger: Ledger,
    table: &LossTable,
    expected_item_index: u8,
) -> Result<Vec<u8>, M1Error> {
    decode_chassis_item(
        tape,
        expected_ledger,
        table,
        chassis_contexts(0, &[])?,
        M1_ARM_ID,
        expected_item_index,
        &mut M1ValueCoder,
    )
}

#[cfg(test)]
mod tests {
    use super::super::chassis::MAX_VALUE_BYTES;
    use super::*;

    #[test]
    fn mixed_item_round_trips_all_record_types_and_delimiters() {
        let table = LossTable::generate();
        let mut source = Vec::new();
        source.extend_from_slice(b"{\"a\":1,\"b\":\"x\"}\n");
        source.extend_from_slice(b"{\"a\":2,\"b\":\"y\"}\n");
        source.extend_from_slice(b"\n");
        source.extend_from_slice(b"{bad}\n");
        source.extend(std::iter::repeat_n(b'x', MAX_VALUE_BYTES + 1));
        source.push(b'\n');
        source.extend_from_slice(b"{\"a\":3,\"b\":\"z\"}");

        let (tape, ledger) = encode_m1_item(&source, &table, 0).unwrap();
        assert_eq!(ledger.records, 6);
        assert_eq!(decode_m1_item(&tape, ledger, &table, 0).unwrap(), source);

        let (second_tape, second_ledger) = encode_m1_item(&source, &table, 0).unwrap();
        assert_eq!(second_tape.to_bytes(), tape.to_bytes());
        assert_eq!(second_ledger, ledger);
    }

    #[test]
    fn empty_item_round_trips_without_an_uncharged_terminator() {
        let table = LossTable::generate();
        let (tape, ledger) = encode_m1_item(b"", &table, 1).unwrap();
        assert_eq!(ledger.records, 0);
        assert_eq!(ledger.modeled_binary_events, 1);
        assert_eq!(decode_m1_item(&tape, ledger, &table, 1).unwrap(), b"");
    }

    #[test]
    fn alternating_templates_exercise_charged_non_same_slot_hits() {
        let table = LossTable::generate();
        let source = b"{\"a\":1}\n{\"b\":2}\n{\"a\":3}\n{\"b\":4}\n";
        let (tape, ledger) = encode_m1_item(source, &table, 2).unwrap();
        assert_eq!(decode_m1_item(&tape, ledger, &table, 2).unwrap(), source);
        assert!(ledger.records == 4 && ledger.raw_literal_bytes > 0);
    }

    #[test]
    fn decoder_binds_tape_arm_and_item_identity() {
        let table = LossTable::generate();
        let (tape, ledger) = encode_m1_item(b"{}", &table, 2).unwrap();
        assert_eq!(
            decode_m1_item(&tape, ledger, &table, 1),
            Err(M1Error::TapeIdentityMismatch)
        );
    }
}
