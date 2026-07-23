//! Moonshot cycle-1 prescreen arms (Lane 2, the Pareto moonshot).
//!
//! Development-only prescreen infrastructure. These arms are new modules that
//! reuse the frozen s0 primitives (`Ledger`, `M5Mixer`, tape, loss table)
//! read-only via the sibling `s0` module; they never mutate s0 behavior or its
//! frozen results. Everything produced here carries a
//! `development_only_prescreen` evidence ceiling: no candidate, SOTA,
//! exact-codec, or ratio claims, and no licensed-item reads.

pub mod h1;
pub mod h6;
pub mod mixer;
pub mod reuse;
pub mod table;

pub use h1::{
    decode_h1_item, decode_h1_item_with_bits, encode_h1_item, encode_h1_item_with_bits,
    h1_declared_state_bytes, H1Error, H1Model, H1_ARM_ID, H1_BYTE_ORDERS, H1_CONTEXT_COUNT,
};
pub use h6::{
    decode_h6_item, decode_h6_item_with_bits, encode_h6_item, encode_h6_item_with_bits,
    h6_declared_state_bytes, H6Error, H6_ARM_ID, H6_DECISION_BUCKETS, H6_DECISION_STATE_BYTES,
};
pub use mixer::{MoonMixer, MOON_MIXER_BUCKETS, MOON_MIXER_INPUTS, MOON_MIXER_WEIGHT_BYTES};
pub use reuse::{LineCache, ReferenceCoder, REFERENCE_TREE_BYTES, REFERENCE_TREE_NODES};
pub use table::{
    Cell, ContextTable, H1_CELL_BYTES, H1_CONTEXT_CELLS, H1_CONTEXT_TABLE_BYTES, H1_PROBE_DEPTH,
};
