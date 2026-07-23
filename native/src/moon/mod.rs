//! Moonshot cycle-1 prescreen arms (Lane 2, the Pareto moonshot).
//!
//! Development-only prescreen infrastructure. These arms are new modules that
//! reuse the frozen s0 primitives (`Ledger`, `M5Mixer`, tape, loss table)
//! read-only via the sibling `s0` module; they never mutate s0 behavior or its
//! frozen results. Everything produced here carries a
//! `development_only_prescreen` evidence ceiling: no candidate, SOTA,
//! exact-codec, or ratio claims, and no licensed-item reads.

pub mod h1;
pub mod table;

pub use h1::{
    decode_h1_item, decode_h1_item_with_bits, encode_h1_item, encode_h1_item_with_bits,
    h1_declared_state_bytes, H1Error, H1_ARM_ID, H1_BYTE_ORDERS, H1_CONTEXT_COUNT,
};
pub use table::{
    Cell, ContextTable, H1_CELL_BYTES, H1_CONTEXT_CELLS, H1_CONTEXT_TABLE_BYTES, H1_PROBE_DEPTH,
};
