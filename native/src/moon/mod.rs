//! Moonshot cycle-1 prescreen arms (Lane 2, the Pareto moonshot).
//!
//! Development-only prescreen infrastructure. These arms are new modules that
//! reuse the frozen s0 primitives (`Ledger`, `M5Mixer`, tape, loss table)
//! read-only via the sibling `s0` module; they never mutate s0 behavior or its
//! frozen results. Everything produced here carries a
//! `development_only_prescreen` evidence ceiling: no candidate, SOTA,
//! exact-codec, or ratio claims, and no licensed-item reads.

pub mod c1;
pub mod c2;
pub mod c3;
pub mod diagnose;
pub mod h1;
pub mod h6;
pub mod h8;
pub mod h9;
pub mod mixer;
pub mod reuse;
pub mod table;

pub use c1::{
    c1_declared_state_bytes, decode_c1_item, decode_c1_item_with_bits, encode_c1_item,
    encode_c1_item_with_bits, C1Error, C1_ARM_ID, C1_BYTE_ORDERS, C1_CONTEXT_COUNT,
    FOLD_WEIGHT_BYTES, MATCH_MIN_LENGTH as C1_MATCH_MIN_LENGTH, MATCH_STATEMAP_BYTES,
    MATCH_TABLE_BYTES, MATCH_WINDOW_BYTES as C1_MATCH_WINDOW_BYTES,
};
pub use c2::{
    c2_declared_state_bytes, decode_c2_item, decode_c2_item_with_bits, encode_c2_item,
    encode_c2_item_with_bits, C2Error, C2_ARM_ID, C2_BYTE_ORDERS, C2_CONTEXT_COUNT,
    C2_MIXER_INPUTS, C2_MIXER_WEIGHT_BYTES, C2_POOLED_TABLE_BYTES, C2_VALUE_VIEW_COUNT,
};
pub use c3::{
    c3_declared_state_bytes, decode_c3_item, decode_c3_item_with_bits, encode_c3_item,
    encode_c3_item_with_bits, encode_c3_item_with_bits_and_quarters, C3Error, C3QuarterSnapshot,
    C3_APM_STATE_BYTES, C3_ARM_ID, C3_BYTE_ORDERS, C3_CONTEXT_COUNT, C3_CONTEXT_TABLE_BYTES,
};

pub use diagnose::{
    decompose_h1, ByteClass, Decomposition, DiagnoseError, DIAGNOSIS_SCHEMA, MATCH_MIN_LENGTH,
    MATCH_WINDOW_BYTES,
};
pub use h1::{
    decode_h1_item, decode_h1_item_with_bits, encode_h1_item, encode_h1_item_traced,
    encode_h1_item_with_bits, h1_declared_state_bytes, H1ByteTrace, H1Error, H1LossTrace, H1Model,
    H1_ARM_ID, H1_BYTE_ORDERS, H1_CONTEXT_COUNT, H1_LOW_CONFIDENCE_THRESHOLD,
};
pub use h6::{
    decode_h6_item, decode_h6_item_with_bits, encode_h6_item, encode_h6_item_with_bits,
    h6_declared_state_bytes, H6Error, H6_ARM_ID, H6_DECISION_BUCKETS, H6_DECISION_STATE_BYTES,
};
pub use h8::{
    decode_h8_item, decode_h8_item_with_bits, encode_h8_item, encode_h8_item_with_bits,
    h8_declared_state_bytes, initial_static_weights, serialize_weight_file, train_static_weights,
    H8Error, H8_ARM_ID, H8_CONFIDENCE_BUCKETS, H8_CONTEXT_COUNT, H8_PROCEDURE_VERSION,
    H8_STATIC_WEIGHT_BYTES, H8_STATIC_WEIGHT_COUNT, H8_WEIGHT_FILE_BYTES, H8_WEIGHT_FILE_SHA256,
};
pub use h9::{
    decode_h9_item, decode_h9_item_with_bits, encode_h9_item, encode_h9_item_with_bits,
    h9_declared_state_bytes, H9Error, H9_ARM_ID, H9_RULE_BUDGET, H9_SYMBOL_ALPHABET,
};
pub use mixer::{MoonMixer, MOON_MIXER_BUCKETS, MOON_MIXER_INPUTS, MOON_MIXER_WEIGHT_BYTES};
pub use reuse::{LineCache, ReferenceCoder, REFERENCE_TREE_BYTES, REFERENCE_TREE_NODES};
pub use table::{
    Cell, ContextTable, H1_CELL_BYTES, H1_CONTEXT_CELLS, H1_CONTEXT_TABLE_BYTES, H1_PROBE_DEPTH,
};
