//! H1 loss-decomposition diagnostic (read-only observer).
//!
//! Development-only prescreen infrastructure (Lane 2, the Pareto moonshot), not
//! a product codec. It answers one question for the ratio sprint: *which bytes
//! and which byte classes does the H1 floor arm spend its coding loss on?* It
//! runs the H1 arm's own [`encode_h1_item_traced`] observer — a parallel encode
//! proven byte-identical to the canonical arm — and buckets the exact
//! fixed-point Q24 loss the frozen ledger tracks along the dimensions the sprint
//! asked for:
//!
//! * a streaming NDJSON-ish byte-position classifier (structural tokens vs
//!   field-name bytes vs string/number/literal value bytes vs whitespace/record
//!   boundaries), with measured coverage;
//! * value subclasses (digit bytes, ISO-8601 timestamp spans, hex/id runs) as
//!   overlays;
//! * a repeated-string-candidacy overlay from a deterministic rolling-hash
//!   long-match observer (a proxy for bits a copy model could capture);
//! * a context-miss proxy from the H1 context table's own confidence counters;
//! * framing (continuation) bits vs modeled bits, and per-record boundary cost.
//!
//! Everything here only *reads* the arm; it never mutates the tape, the ledger,
//! or any frozen surface, and it re-runs the canonical arm and refuses if the
//! observer's tape or ledger diverges by a single byte. The output is a
//! deterministic JSON report keyed only by byte offsets and single-byte class
//! labels — it never re-emits source text.

use std::collections::HashMap;
use std::error::Error;
use std::fmt::{Display, Formatter};

use crate::s0::{Ledger, LossTable};

use super::h1::{encode_h1_item_traced, encode_h1_item_with_bits, H1Error, H1LossTrace};

/// Report schema identity.
pub const DIAGNOSIS_SCHEMA: &str = "clab-moon-h1-loss-decomposition-v1";

/// Q24 fixed-point scale of every `*_loss_q24` figure (`loss_q24 / 2^24` bits).
pub const Q24_SCALE: u64 = 1 << 24;

/// Minimum match length (bytes) the rolling-hash observer counts as a repeat.
pub const MATCH_MIN_LENGTH: usize = 8;
/// Back-reference window (bytes) for the rolling-hash repeat observer.
pub const MATCH_WINDOW_BYTES: usize = 65_536;
/// Minimum length of a maximal hex-character run counted as a hex/id span.
pub const HEX_RUN_MIN: usize = 16;
/// Minimum length of a maximal alphanumeric run (with at least one digit and
/// one letter) counted as a mixed id span.
pub const ID_RUN_MIN: usize = 20;
/// Default number of top-loss 64-byte regions reported.
pub const DEFAULT_TOP_REGIONS: usize = 16;
/// Width in bytes of each reported hot region.
pub const REGION_BYTES: usize = 64;

const FNV_OFFSET: u64 = 14_695_981_039_346_656_037;
const FNV_PRIME: u64 = 1_099_511_628_211;

/// Primary byte-position class. Every source byte is assigned exactly one, so
/// the per-class losses partition the modeled (byte-bit) loss with no overlap.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ByteClass {
    /// JSON structural punctuation and the string delimiters: `{ } [ ] , : "`.
    Structural,
    /// Bytes inside an object key string (between its quotes).
    FieldName,
    /// Bytes inside a string value (between its quotes).
    StringValue,
    /// Bytes of a numeric literal value.
    NumberValue,
    /// Bytes of a `true` / `false` / `null` literal value.
    LiteralValue,
    /// Space, tab, carriage return, and the newline record boundary.
    Whitespace,
    /// Bytes the streaming classifier could not place (coverage gap).
    Unclassified,
}

/// Number of primary classes; indexes the per-class arrays.
pub const CLASS_COUNT: usize = 7;

impl ByteClass {
    #[must_use]
    fn index(self) -> usize {
        match self {
            Self::Structural => 0,
            Self::FieldName => 1,
            Self::StringValue => 2,
            Self::NumberValue => 3,
            Self::LiteralValue => 4,
            Self::Whitespace => 5,
            Self::Unclassified => 6,
        }
    }

    /// Stable JSON label for this class.
    #[must_use]
    pub fn label(self) -> &'static str {
        match self {
            Self::Structural => "structural",
            Self::FieldName => "field_name",
            Self::StringValue => "string_value",
            Self::NumberValue => "number_value",
            Self::LiteralValue => "literal_value",
            Self::Whitespace => "whitespace",
            Self::Unclassified => "unclassified",
        }
    }

    #[must_use]
    fn from_index(index: usize) -> Self {
        [
            Self::Structural,
            Self::FieldName,
            Self::StringValue,
            Self::NumberValue,
            Self::LiteralValue,
            Self::Whitespace,
            Self::Unclassified,
        ][index]
    }
}

#[derive(Clone, Copy)]
enum Container {
    Object,
    Array,
}

fn is_number_continuation(byte: u8) -> bool {
    byte.is_ascii_digit() || matches!(byte, b'.' | b'e' | b'E' | b'+' | b'-')
}

/// Deterministic streaming NDJSON-ish byte classifier. It does not fully parse
/// JSON; it assigns each byte a position class with a small state machine that
/// **resets at every newline** (the NDJSON record boundary), so a malformed
/// line cannot desynchronise later lines. Documented and total: every byte
/// receives exactly one class.
#[must_use]
pub fn classify(source: &[u8]) -> Vec<ByteClass> {
    let mut classes = Vec::with_capacity(source.len());
    let mut stack: Vec<Container> = Vec::new();
    let mut expect_key = false;
    let mut in_string = false;
    let mut string_is_key = false;
    let mut escaped = false;
    let mut in_number = false;
    let mut in_literal = false;

    for &byte in source {
        if in_number {
            if is_number_continuation(byte) {
                classes.push(ByteClass::NumberValue);
                continue;
            }
            in_number = false;
        }
        if in_literal {
            if byte.is_ascii_lowercase() {
                classes.push(ByteClass::LiteralValue);
                continue;
            }
            in_literal = false;
        }
        if in_string {
            let role = if string_is_key {
                ByteClass::FieldName
            } else {
                ByteClass::StringValue
            };
            if escaped {
                escaped = false;
                classes.push(role);
            } else {
                match byte {
                    b'\\' => {
                        escaped = true;
                        classes.push(role);
                    }
                    b'"' => {
                        in_string = false;
                        classes.push(ByteClass::Structural);
                    }
                    _ => classes.push(role),
                }
            }
            continue;
        }
        match byte {
            b'\n' => {
                classes.push(ByteClass::Whitespace);
                stack.clear();
                expect_key = false;
                escaped = false;
            }
            b' ' | b'\t' | b'\r' => classes.push(ByteClass::Whitespace),
            b'{' => {
                classes.push(ByteClass::Structural);
                stack.push(Container::Object);
                expect_key = true;
            }
            b'[' => {
                classes.push(ByteClass::Structural);
                stack.push(Container::Array);
            }
            b'}' | b']' => {
                classes.push(ByteClass::Structural);
                stack.pop();
            }
            b':' => {
                classes.push(ByteClass::Structural);
                expect_key = false;
            }
            b',' => {
                classes.push(ByteClass::Structural);
                expect_key = matches!(stack.last(), Some(Container::Object));
            }
            b'"' => {
                classes.push(ByteClass::Structural);
                in_string = true;
                string_is_key = matches!(stack.last(), Some(Container::Object)) && expect_key;
            }
            b'0'..=b'9' | b'-' => {
                in_number = true;
                classes.push(ByteClass::NumberValue);
            }
            b't' | b'f' | b'n' => {
                in_literal = true;
                classes.push(ByteClass::LiteralValue);
            }
            _ => classes.push(ByteClass::Unclassified),
        }
    }
    classes
}

/// Mark bytes inside a maximal digit run — the cheapest value subclass overlay.
fn digit_overlay(source: &[u8]) -> Vec<bool> {
    source.iter().map(|byte| byte.is_ascii_digit()).collect()
}

/// Mark bytes inside an ISO-8601 date-time span. The core pattern is
/// `YYYY-MM-DDThh:mm:ss` (a space in place of `T` is also accepted), optionally
/// followed by a fractional part `.d+` and a zone (`Z` or `[+-]hh:mm`). Purely
/// structural digit/separator matching, not calendar validation.
fn timestamp_overlay(source: &[u8]) -> Vec<bool> {
    let n = source.len();
    let mut marked = vec![false; n];
    let digit = |offset: usize| offset < n && source[offset].is_ascii_digit();
    let literal = |offset: usize, value: u8| offset < n && source[offset] == value;
    let digits = |start: usize, count: usize| (0..count).all(|k| digit(start + k));

    let mut index = 0;
    while index < n {
        // YYYY - MM - DD (T| ) hh : mm : ss  == 19 bytes.
        let core = digits(index, 4)
            && literal(index + 4, b'-')
            && digits(index + 5, 2)
            && literal(index + 7, b'-')
            && digits(index + 8, 2)
            && (literal(index + 10, b'T') || literal(index + 10, b' '))
            && digits(index + 11, 2)
            && literal(index + 13, b':')
            && digits(index + 14, 2)
            && literal(index + 16, b':')
            && digits(index + 17, 2);
        if !core {
            index += 1;
            continue;
        }
        let mut end = index + 19;
        if literal(end, b'.') {
            let mut cursor = end + 1;
            while digit(cursor) {
                cursor += 1;
            }
            if cursor > end + 1 {
                end = cursor;
            }
        }
        if literal(end, b'Z') {
            end += 1;
        } else if (literal(end, b'+') || literal(end, b'-'))
            && digits(end + 1, 2)
            && literal(end + 3, b':')
            && digits(end + 4, 2)
        {
            end += 6;
        }
        for byte in marked.iter_mut().take(end).skip(index) {
            *byte = true;
        }
        index = end;
    }
    marked
}

/// Mark bytes inside a long hex run (>= [`HEX_RUN_MIN`]) or a long mixed
/// alphanumeric id run (>= [`ID_RUN_MIN`] containing at least one digit and one
/// letter). A cheap proxy for opaque identifiers/hashes.
fn hex_id_overlay(source: &[u8]) -> Vec<bool> {
    let n = source.len();
    let mut marked = vec![false; n];

    let mut start = 0;
    while start < n {
        if !source[start].is_ascii_hexdigit() {
            start += 1;
            continue;
        }
        let mut end = start;
        while end < n && source[end].is_ascii_hexdigit() {
            end += 1;
        }
        if end - start >= HEX_RUN_MIN {
            for byte in marked.iter_mut().take(end).skip(start) {
                *byte = true;
            }
        }
        start = end;
    }

    let mut start = 0;
    while start < n {
        if !source[start].is_ascii_alphanumeric() {
            start += 1;
            continue;
        }
        let mut end = start;
        let mut has_digit = false;
        let mut has_alpha = false;
        while end < n && source[end].is_ascii_alphanumeric() {
            has_digit |= source[end].is_ascii_digit();
            has_alpha |= source[end].is_ascii_alphabetic();
            end += 1;
        }
        if end - start >= ID_RUN_MIN && has_digit && has_alpha {
            for byte in marked.iter_mut().take(end).skip(start) {
                *byte = true;
            }
        }
        start = end;
    }
    marked
}

fn fnv1a64(bytes: &[u8]) -> u64 {
    bytes.iter().fold(FNV_OFFSET, |hash, byte| {
        (hash ^ u64::from(*byte)).wrapping_mul(FNV_PRIME)
    })
}

/// Deterministic rolling-hash long-match observer. For each position it looks
/// up the most recent prior occurrence of the current [`MATCH_MIN_LENGTH`]-gram
/// within [`MATCH_WINDOW_BYTES`], verifies the bytes are equal (excluding hash
/// collisions), greedily extends the match forward, and marks every byte the
/// match covers. It is a *proxy* for how many expensive bytes lie inside long
/// repeats a copy model could capture — not an exhaustive matcher — and it
/// never influences the encode.
fn repeat_overlay(source: &[u8]) -> Vec<bool> {
    let n = source.len();
    let mut marked = vec![false; n];
    if n < MATCH_MIN_LENGTH {
        return marked;
    }
    let mut last_position: HashMap<u64, usize> = HashMap::new();
    for start in 0..=(n - MATCH_MIN_LENGTH) {
        let key = fnv1a64(&source[start..start + MATCH_MIN_LENGTH]);
        if let Some(&prior) = last_position.get(&key) {
            if start - prior <= MATCH_WINDOW_BYTES
                && source[prior..prior + MATCH_MIN_LENGTH]
                    == source[start..start + MATCH_MIN_LENGTH]
            {
                let mut length = MATCH_MIN_LENGTH;
                while start + length < n && source[prior + length] == source[start + length] {
                    length += 1;
                }
                for byte in marked.iter_mut().take(start + length).skip(start) {
                    *byte = true;
                }
            }
        }
        last_position.insert(key, start);
    }
    marked
}

/// A primary-class bucket: exact Q24 loss and the number of source bytes.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ClassBucket {
    pub class: ByteClass,
    pub loss_q24: u64,
    pub bytes: u64,
}

/// A value-subclass or repeat overlay: modeled Q24 loss over the marked bytes.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct Overlay {
    pub loss_q24: u64,
    pub bytes: u64,
}

/// The context-miss proxy aggregate (see [`H1_LOW_CONFIDENCE_THRESHOLD`]).
///
/// [`H1_LOW_CONFIDENCE_THRESHOLD`]: super::h1::H1_LOW_CONFIDENCE_THRESHOLD
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct ContextMiss {
    pub low_confidence_bits: u64,
    pub low_confidence_loss_q24: u64,
}

/// One hot 64-byte region: offset, length, total loss, and its bucket mix. No
/// source content — only class byte counts and overlay byte counts.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Region {
    pub offset: u64,
    pub length: u64,
    pub loss_q24: u64,
    pub class_bytes: [u64; CLASS_COUNT],
    pub digit_bytes: u64,
    pub timestamp_bytes: u64,
    pub hex_id_bytes: u64,
    pub repeat_bytes: u64,
    pub low_confidence_bits: u64,
}

/// The full deterministic decomposition of one H1-arm item encode.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Decomposition {
    pub item_index: u8,
    pub sse_bucket_bits: u32,
    pub source_bytes: u64,
    pub ledger: Ledger,
    pub tape_bytes: u64,
    /// Total modeled loss (== `ledger.modeled_loss_q24`); every bucket below
    /// sums into this with no slack.
    pub total_loss_q24: u64,
    pub framing_continuation_loss_q24: u64,
    pub terminal_continuation_loss_q24: u64,
    pub modeled_bits_loss_q24: u64,
    pub records: u64,
    pub record_boundary_loss_q24: u64,
    pub classified_bytes: u64,
    pub unclassified_bytes: u64,
    pub classes: [ClassBucket; CLASS_COUNT],
    pub digits: Overlay,
    pub timestamp: Overlay,
    pub hex_id: Overlay,
    pub repeat: Overlay,
    pub context_miss: ContextMiss,
    pub top_regions: Vec<Region>,
    pub top_regions_requested: usize,
}

/// Loss-decomposition error. Wraps the arm error and adds the fail-closed
/// observer-divergence guard.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DiagnoseError {
    H1(H1Error),
    /// The observer's tape or ledger differed from the canonical arm on the
    /// same input — refuse rather than report a decomposition of a tape the arm
    /// would not have produced.
    ObserverDivergedFromArm,
}

impl Display for DiagnoseError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::H1(error) => write!(formatter, "H1 arm error during diagnosis: {error}"),
            Self::ObserverDivergedFromArm => write!(
                formatter,
                "loss-decomposition observer diverged from the H1 arm tape/ledger"
            ),
        }
    }
}

impl Error for DiagnoseError {}

impl From<H1Error> for DiagnoseError {
    fn from(error: H1Error) -> Self {
        Self::H1(error)
    }
}

/// Parts-per-million of `total`, saturating and total-zero safe.
#[must_use]
fn ppm(part: u64, total: u64) -> u64 {
    if total == 0 {
        return 0;
    }
    ((u128::from(part) * 1_000_000) / u128::from(total)) as u64
}

/// Decompose one H1-arm item encode. Runs the read-only traced observer, then
/// re-runs the canonical arm and refuses on any divergence, then buckets the
/// exact Q24 loss along every requested dimension.
pub fn decompose_h1(
    source: &[u8],
    table: &LossTable,
    item_index: u8,
    sse_bucket_bits: u32,
    top_regions: usize,
) -> Result<Decomposition, DiagnoseError> {
    let (traced_tape, traced_ledger, trace) =
        encode_h1_item_traced(source, table, item_index, sse_bucket_bits)?;
    // Fail-closed byte-identity guard: the canonical arm must produce the exact
    // same tape and ledger, or we do not trust the decomposition.
    let (arm_tape, arm_ledger) =
        encode_h1_item_with_bits(source, table, item_index, sse_bucket_bits)?;
    if traced_tape.to_bytes() != arm_tape.to_bytes() || traced_ledger != arm_ledger {
        return Err(DiagnoseError::ObserverDivergedFromArm);
    }

    let decomposition = build(
        source,
        &trace,
        traced_ledger,
        traced_tape.to_bytes().len() as u64,
        item_index,
        sse_bucket_bits,
        top_regions,
    );
    // The buckets must close exactly against the ledger the arm charged.
    let bucket_sum: u64 = decomposition
        .classes
        .iter()
        .map(|bucket| bucket.loss_q24)
        .sum::<u64>()
        + decomposition.framing_continuation_loss_q24;
    if bucket_sum != traced_ledger.modeled_loss_q24 {
        return Err(DiagnoseError::ObserverDivergedFromArm);
    }
    Ok(decomposition)
}

#[allow(clippy::too_many_arguments)]
fn build(
    source: &[u8],
    trace: &H1LossTrace,
    ledger: Ledger,
    tape_bytes: u64,
    item_index: u8,
    sse_bucket_bits: u32,
    top_regions: usize,
) -> Decomposition {
    let classes = classify(source);
    let digits = digit_overlay(source);
    let timestamp = timestamp_overlay(source);
    let hex_id = hex_id_overlay(source);
    let repeat = repeat_overlay(source);

    let mut class_loss = [0_u64; CLASS_COUNT];
    let mut class_bytes = [0_u64; CLASS_COUNT];
    let mut digit_overlay_acc = Overlay::default();
    let mut timestamp_overlay_acc = Overlay::default();
    let mut hex_id_overlay_acc = Overlay::default();
    let mut repeat_overlay_acc = Overlay::default();
    let mut context_miss = ContextMiss::default();
    let mut framing_continuation = u64::from(trace.terminal_continuation_loss_q24);
    let mut modeled_total = 0_u64;
    let mut record_boundary = 0_u64;

    for (position, entry) in trace.bytes.iter().enumerate() {
        let modeled = entry.modeled_loss_q24();
        let class = classes[position];
        class_loss[class.index()] += modeled;
        class_bytes[class.index()] += 1;
        framing_continuation += u64::from(entry.continuation_loss_q24);
        modeled_total += modeled;

        if entry.byte == b'\n' {
            record_boundary += entry.total_loss_q24();
        }
        if digits[position] {
            digit_overlay_acc.loss_q24 += modeled;
            digit_overlay_acc.bytes += 1;
        }
        if timestamp[position] {
            timestamp_overlay_acc.loss_q24 += modeled;
            timestamp_overlay_acc.bytes += 1;
        }
        if hex_id[position] {
            hex_id_overlay_acc.loss_q24 += modeled;
            hex_id_overlay_acc.bytes += 1;
        }
        if repeat[position] {
            repeat_overlay_acc.loss_q24 += modeled;
            repeat_overlay_acc.bytes += 1;
        }
        for slot in 0..8 {
            if entry.low_confidence_mask & (1 << slot) != 0 {
                context_miss.low_confidence_bits += 1;
                context_miss.low_confidence_loss_q24 += u64::from(entry.bit_loss_q24[slot]);
            }
        }
    }

    let unclassified_bytes = class_bytes[ByteClass::Unclassified.index()];
    let classified_bytes = source.len() as u64 - unclassified_bytes;

    let classes_out: [ClassBucket; CLASS_COUNT] = std::array::from_fn(|index| ClassBucket {
        class: ByteClass::from_index(index),
        loss_q24: class_loss[index],
        bytes: class_bytes[index],
    });

    let regions = top_regions_by_loss(
        source,
        trace,
        &classes,
        &digits,
        &timestamp,
        &hex_id,
        &repeat,
        top_regions,
    );

    Decomposition {
        item_index,
        sse_bucket_bits,
        source_bytes: source.len() as u64,
        ledger,
        tape_bytes,
        total_loss_q24: ledger.modeled_loss_q24,
        framing_continuation_loss_q24: framing_continuation,
        terminal_continuation_loss_q24: u64::from(trace.terminal_continuation_loss_q24),
        modeled_bits_loss_q24: modeled_total,
        records: ledger.records,
        record_boundary_loss_q24: record_boundary,
        classified_bytes,
        unclassified_bytes,
        classes: classes_out,
        digits: digit_overlay_acc,
        timestamp: timestamp_overlay_acc,
        hex_id: hex_id_overlay_acc,
        repeat: repeat_overlay_acc,
        context_miss,
        top_regions: regions,
        top_regions_requested: top_regions,
    }
}

#[allow(clippy::too_many_arguments)]
fn top_regions_by_loss(
    source: &[u8],
    trace: &H1LossTrace,
    classes: &[ByteClass],
    digits: &[bool],
    timestamp: &[bool],
    hex_id: &[bool],
    repeat: &[bool],
    top_regions: usize,
) -> Vec<Region> {
    let n = source.len();
    let mut regions: Vec<Region> = Vec::new();
    let mut start = 0;
    while start < n {
        let end = (start + REGION_BYTES).min(n);
        let mut loss = 0_u64;
        let mut class_bytes = [0_u64; CLASS_COUNT];
        let mut digit_bytes = 0_u64;
        let mut timestamp_bytes = 0_u64;
        let mut hex_id_bytes = 0_u64;
        let mut repeat_bytes = 0_u64;
        let mut low_confidence_bits = 0_u64;
        for position in start..end {
            let entry = &trace.bytes[position];
            loss += entry.total_loss_q24();
            class_bytes[classes[position].index()] += 1;
            digit_bytes += u64::from(digits[position]);
            timestamp_bytes += u64::from(timestamp[position]);
            hex_id_bytes += u64::from(hex_id[position]);
            repeat_bytes += u64::from(repeat[position]);
            low_confidence_bits += u64::from(entry.low_confidence_mask.count_ones());
        }
        regions.push(Region {
            offset: start as u64,
            length: (end - start) as u64,
            loss_q24: loss,
            class_bytes,
            digit_bytes,
            timestamp_bytes,
            hex_id_bytes,
            repeat_bytes,
            low_confidence_bits,
        });
        start = end;
    }
    // Highest loss first; ties resolve by ascending offset for determinism.
    regions.sort_by(|left, right| {
        right
            .loss_q24
            .cmp(&left.loss_q24)
            .then(left.offset.cmp(&right.offset))
    });
    regions.truncate(top_regions);
    regions
}

impl Decomposition {
    /// Coverage as parts-per-million of source bytes the classifier placed.
    #[must_use]
    pub fn coverage_ppm(&self) -> u64 {
        ppm(self.classified_bytes, self.source_bytes)
    }

    /// Render the deterministic JSON report. `kernel_version`, `source_sha256`,
    /// and `tape_sha256` are supplied by the caller for provenance.
    #[must_use]
    pub fn to_json(&self, kernel_version: &str, source_sha256: &str, tape_sha256: &str) -> String {
        let total = self.total_loss_q24;
        let mut classes = String::new();
        for (index, bucket) in self.classes.iter().enumerate() {
            if index > 0 {
                classes.push_str(",\n");
            }
            classes.push_str(&format!(
                "    {{\"bucket\": \"{}\", \"loss_q24\": {}, \"loss_ppm\": {}, \"bytes\": {}}}",
                bucket.class.label(),
                bucket.loss_q24,
                ppm(bucket.loss_q24, total),
                bucket.bytes
            ));
        }

        let overlay = |name: &str, overlay: Overlay| {
            format!(
                "    \"{name}\": {{\"loss_q24\": {}, \"loss_ppm\": {}, \"bytes\": {}}}",
                overlay.loss_q24,
                ppm(overlay.loss_q24, total),
                overlay.bytes
            )
        };

        let mut regions = String::new();
        for (index, region) in self.top_regions.iter().enumerate() {
            if index > 0 {
                regions.push_str(",\n");
            }
            let mut class_mix = String::new();
            for (slot, count) in region.class_bytes.iter().enumerate() {
                if slot > 0 {
                    class_mix.push_str(", ");
                }
                class_mix.push_str(&format!(
                    "\"{}\": {}",
                    ByteClass::from_index(slot).label(),
                    count
                ));
            }
            regions.push_str(&format!(
                "    {{\"offset\": {}, \"length\": {}, \"loss_q24\": {}, \"loss_ppm\": {}, \"class_bytes\": {{{}}}, \"overlay_bytes\": {{\"digits\": {}, \"timestamp\": {}, \"hex_id\": {}, \"repeat\": {}, \"low_confidence_bits\": {}}}}}",
                region.offset,
                region.length,
                region.loss_q24,
                ppm(region.loss_q24, total),
                class_mix,
                region.digit_bytes,
                region.timestamp_bytes,
                region.hex_id_bytes,
                region.repeat_bytes,
                region.low_confidence_bits,
            ));
        }

        format!(
            "{{\n  \"schema\": \"{schema}\",\n  \"kernel_version\": \"{kernel_version}\",\n  \"evidence_stage\": \"development_only_prescreen\",\n  \"arm\": \"h1-floor\",\n  \"item_index\": {item_index},\n  \"sse_bucket_bits\": {sse_bucket_bits},\n  \"q24_scale\": {q24_scale},\n  \"source_bytes\": {source_bytes},\n  \"source_sha256\": \"{source_sha256}\",\n  \"tape_bytes\": {tape_bytes},\n  \"tape_sha256\": \"{tape_sha256}\",\n  \"ledger\": {{\"records\": {records}, \"modeled_binary_events\": {events}, \"modeled_loss_q24\": {loss}, \"raw_literal_bytes\": {raw}}},\n  \"totals\": {{\"total_loss_q24\": {total}, \"modeled_bits_loss_q24\": {modeled}, \"framing_continuation_loss_q24\": {framing}, \"framing_loss_ppm\": {framing_ppm}, \"modeled_loss_ppm\": {modeled_ppm}}},\n  \"framing\": {{\"continuation_bits_loss_q24\": {framing}, \"terminal_continuation_loss_q24\": {terminal}, \"records\": {records}, \"record_boundary_loss_q24\": {record_boundary}, \"record_boundary_loss_ppm\": {record_boundary_ppm}}},\n  \"classifier\": {{\"coverage_ppm\": {coverage_ppm}, \"classified_bytes\": {classified}, \"unclassified_bytes\": {unclassified}, \"resets_on_newline\": true, \"low_confidence_threshold\": {low_conf_threshold}}},\n  \"primary_partition\": [\n{classes}\n  ],\n  \"value_subclasses\": {{\n{digits},\n{timestamp},\n{hex_id}\n  }},\n  \"repeat_candidate\": {{\"min_match\": {match_min}, \"window_bytes\": {match_window}, \"loss_q24\": {repeat_loss}, \"loss_ppm\": {repeat_ppm}, \"bytes\": {repeat_bytes}}},\n  \"context_miss\": {{\"low_confidence_threshold\": {low_conf_threshold}, \"low_confidence_bits\": {low_conf_bits}, \"low_confidence_loss_q24\": {low_conf_loss}, \"loss_ppm\": {low_conf_ppm}}},\n  \"top_regions_requested\": {top_requested},\n  \"region_bytes\": {region_bytes},\n  \"top_regions\": [\n{regions}\n  ]\n}}\n",
            schema = DIAGNOSIS_SCHEMA,
            kernel_version = kernel_version,
            item_index = self.item_index,
            sse_bucket_bits = self.sse_bucket_bits,
            q24_scale = Q24_SCALE,
            source_bytes = self.source_bytes,
            source_sha256 = source_sha256,
            tape_bytes = self.tape_bytes,
            tape_sha256 = tape_sha256,
            records = self.records,
            events = self.ledger.modeled_binary_events,
            loss = self.ledger.modeled_loss_q24,
            raw = self.ledger.raw_literal_bytes,
            total = total,
            modeled = self.modeled_bits_loss_q24,
            framing = self.framing_continuation_loss_q24,
            framing_ppm = ppm(self.framing_continuation_loss_q24, total),
            modeled_ppm = ppm(self.modeled_bits_loss_q24, total),
            terminal = self.terminal_continuation_loss_q24,
            record_boundary = self.record_boundary_loss_q24,
            record_boundary_ppm = ppm(self.record_boundary_loss_q24, total),
            coverage_ppm = self.coverage_ppm(),
            classified = self.classified_bytes,
            unclassified = self.unclassified_bytes,
            low_conf_threshold = super::h1::H1_LOW_CONFIDENCE_THRESHOLD,
            classes = classes,
            digits = overlay("digits", self.digits),
            timestamp = overlay("timestamp_span", self.timestamp),
            hex_id = overlay("hex_id_run", self.hex_id),
            match_min = MATCH_MIN_LENGTH,
            match_window = MATCH_WINDOW_BYTES,
            repeat_loss = self.repeat.loss_q24,
            repeat_ppm = ppm(self.repeat.loss_q24, total),
            repeat_bytes = self.repeat.bytes,
            low_conf_bits = self.context_miss.low_confidence_bits,
            low_conf_loss = self.context_miss.low_confidence_loss_q24,
            low_conf_ppm = ppm(self.context_miss.low_confidence_loss_q24, total),
            top_requested = self.top_regions_requested,
            region_bytes = REGION_BYTES,
            regions = regions,
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn corpus() -> Vec<u8> {
        let mut source = Vec::new();
        for index in 0..80_u32 {
            source.extend_from_slice(
                format!(
                    "{{\"ts\":\"2026-07-22T10:{:02}:{:02}Z\",\"level\":\"info\",\"id\":{},\"hash\":\"{:016x}\",\"path\":\"/api/v1/x/{}\"}}\n",
                    index % 60,
                    (index * 7) % 60,
                    100_000 + index,
                    u64::from(index).wrapping_mul(0x9e37_79b9_7f4a_7c15),
                    index % 8,
                )
                .as_bytes(),
            );
        }
        source
    }

    #[test]
    fn classifier_covers_well_formed_ndjson_completely() {
        let source = corpus();
        let classes = classify(&source);
        assert_eq!(classes.len(), source.len());
        let unclassified = classes
            .iter()
            .filter(|class| matches!(class, ByteClass::Unclassified))
            .count();
        assert_eq!(unclassified, 0, "clean NDJSON should be fully classified");
        // Field names and value bytes both appear.
        assert!(classes.iter().any(|c| matches!(c, ByteClass::FieldName)));
        assert!(classes.iter().any(|c| matches!(c, ByteClass::StringValue)));
        assert!(classes.iter().any(|c| matches!(c, ByteClass::NumberValue)));
    }

    #[test]
    fn classifier_distinguishes_keys_from_string_values() {
        let source = b"{\"key\":\"val\"}\n".to_vec();
        let classes = classify(&source);
        // {  "  k  e  y  "  :  "  v  a  l  "  }  \n
        assert!(matches!(classes[0], ByteClass::Structural)); // {
        assert!(matches!(classes[2], ByteClass::FieldName)); // k
        assert!(matches!(classes[8], ByteClass::StringValue)); // v
        assert!(matches!(classes[6], ByteClass::Structural)); // :
    }

    #[test]
    fn classifier_resets_state_on_newline() {
        // A malformed first line must not desync the well-formed second line.
        let source = b"{\"a\":\n{\"b\":\"c\"}\n".to_vec();
        let classes = classify(&source);
        let second_line_start = source.iter().position(|&b| b == b'\n').unwrap() + 1;
        // The 'b' key byte on the second line is classified as a field name.
        let b_index = second_line_start + 2;
        assert!(matches!(classes[b_index], ByteClass::FieldName));
    }

    #[test]
    fn overlays_detect_their_patterns() {
        let source = b"{\"ts\":\"2026-07-22T10:30:45Z\",\"h\":\"deadbeefdeadbeef01\"}\n".to_vec();
        let timestamp = timestamp_overlay(&source);
        let hex_id = hex_id_overlay(&source);
        assert!(timestamp.iter().filter(|marked| **marked).count() >= 19);
        assert!(hex_id.iter().any(|marked| *marked));
    }

    #[test]
    fn repeat_overlay_marks_duplicated_records() {
        let mut source = Vec::new();
        for _ in 0..8 {
            source.extend_from_slice(b"{\"level\":\"info\",\"msg\":\"ready\"}\n");
        }
        let repeat = repeat_overlay(&source);
        // The second copy onward should be inside long matches.
        let marked = repeat.iter().filter(|m| **m).count();
        assert!(marked > source.len() / 2, "duplicates should be marked");
    }

    #[test]
    fn decomposition_buckets_close_against_the_ledger() {
        let table = LossTable::generate();
        let source = corpus();
        let decomposition =
            decompose_h1(&source, &table, 0, crate::s0::SSE_BASE_BUCKET_BITS, 8).unwrap();
        let class_sum: u64 = decomposition
            .classes
            .iter()
            .map(|bucket| bucket.loss_q24)
            .sum();
        assert_eq!(
            class_sum + decomposition.framing_continuation_loss_q24,
            decomposition.total_loss_q24
        );
        assert_eq!(
            decomposition.total_loss_q24,
            decomposition.ledger.modeled_loss_q24
        );
        // Modeled + framing continuation partition the whole loss.
        assert_eq!(
            decomposition.modeled_bits_loss_q24 + decomposition.framing_continuation_loss_q24,
            decomposition.total_loss_q24
        );
    }

    #[test]
    fn decomposition_is_deterministic_including_json() {
        let table = LossTable::generate();
        let source = corpus();
        let first = decompose_h1(&source, &table, 3, crate::s0::SSE_BASE_BUCKET_BITS, 16).unwrap();
        let second = decompose_h1(&source, &table, 3, crate::s0::SSE_BASE_BUCKET_BITS, 16).unwrap();
        assert_eq!(first, second);
        assert_eq!(
            first.to_json("test", "abc", "def"),
            second.to_json("test", "abc", "def")
        );
    }

    #[test]
    fn top_regions_are_sorted_and_bounded() {
        let table = LossTable::generate();
        let source = corpus();
        let decomposition =
            decompose_h1(&source, &table, 0, crate::s0::SSE_BASE_BUCKET_BITS, 5).unwrap();
        assert!(decomposition.top_regions.len() <= 5);
        for pair in decomposition.top_regions.windows(2) {
            assert!(pair[0].loss_q24 >= pair[1].loss_q24);
        }
    }

    #[test]
    fn coverage_is_partial_on_non_json_lines() {
        let source = b"this is not json at all\n\x00\x01\x02\x03\n".to_vec();
        let classes = classify(&source);
        let unclassified = classes
            .iter()
            .filter(|class| matches!(class, ByteClass::Unclassified))
            .count();
        assert!(unclassified > 0, "binary/plain lines should leave a gap");
    }
}
