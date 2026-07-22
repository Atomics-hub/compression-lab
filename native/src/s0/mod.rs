//! Deterministic accounting kernel for the preregistered S0 JSON/log screen.
//!
//! This module is research infrastructure, not a production codec. It provides
//! integer-only prequential loss accounting, an exact event/literal tape, and
//! the frozen complete-byte projection. Corpus-specific grammar and models are
//! deliberately layered on top of these primitives.

mod chassis;
mod event;
mod fixed_log;
#[cfg(test)]
mod golden;
mod json;
mod ledger;
mod m1;
mod m2;
mod m3;
mod tape;
mod template;

pub use chassis::{
    chassis_contexts, decode_chassis_item, decode_m1_value, encode_chassis_item, encode_m1_value,
    lane_key, ChassisError, M1ValueCoder, RecordType, ValueCoder, M1_BINARY_CONTEXTS,
    M1_TREE_CONTEXTS, MAX_VALUE_BYTES,
};
pub use event::{ContextStore, EventDecoder, EventEncoder, EventError};
pub use fixed_log::{LossTable, Probability, MAX_PROBABILITY, MIN_PROBABILITY};
pub use json::{split_records, JsonLayout, JsonLayoutError, Record};
pub use ledger::{Decision, Ledger, Projection};
pub use m1::{decode_m1_item, encode_m1_item, M1Error, M1_ARM_ID};
pub use m2::{
    decode_m1_m2_item, encode_m1_m2_item, m2_contexts, M2ValueCoder, M2_ARM_ID, M2_BINARY_CONTEXTS,
    M2_DECLARED_STATE_BYTES, M2_LANES_PER_SLOT, M2_LANE_STATE_BYTES, M2_TREE_CONTEXTS,
};
pub use m3::{
    decode_m1_m2_m3_item, encode_m1_m2_m3_item, m3_contexts, M3ValueCoder, M3_ARM_ID,
    M3_BINARY_CONTEXTS, M3_DECLARED_SLOT_BYTES, M3_DECLARED_STATE_BYTES, M3_SESSION_SLOTS,
    M3_SLOT_VALUE_BYTES, M3_TREE_CONTEXTS,
};
pub use tape::{Tape, TapeError, TapeReader, TapeWriter};
pub use template::{InsertOutcome, TemplateError, TemplateHit, TemplateStore};
