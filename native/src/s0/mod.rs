//! Deterministic accounting kernel for the preregistered S0 JSON/log screen.
//!
//! This module is research infrastructure, not a production codec. It provides
//! integer-only prequential loss accounting, an exact event/literal tape, and
//! the frozen complete-byte projection. Corpus-specific grammar and models are
//! deliberately layered on top of these primitives.

mod event;
mod fixed_log;
mod json;
mod ledger;
mod m1;
mod tape;
mod template;

pub use event::{ContextStore, EventDecoder, EventEncoder, EventError};
pub use fixed_log::{LossTable, Probability, MAX_PROBABILITY, MIN_PROBABILITY};
pub use json::{split_records, JsonLayout, JsonLayoutError, Record};
pub use ledger::{Decision, Ledger, Projection};
pub use m1::{decode_m1_item, encode_m1_item, M1Error};
pub use tape::{Tape, TapeError, TapeReader, TapeWriter};
pub use template::{TemplateError, TemplateHit, TemplateStore};
