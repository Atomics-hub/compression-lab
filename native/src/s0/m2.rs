//! M2 arm: typed ID and TIME delta lanes over the shared chassis.
//!
//! M2 changes only HIT value coding. MISS, FALLBACK, EMPTY, record framing,
//! template grammar, and every M1 prefix context remain identical. The first
//! 64 top-level value positions of each template slot may carry typed state;
//! index >= 64 always uses M1 value coding and carries no M2 state. Exact
//! previous state is indexed by slot and lane, never hashed: context hash
//! collisions may share predictions but never reconstruction state.

use super::chassis::{
    chassis_contexts, decode_chassis_item, encode_chassis_item, ChassisError, M1ValueCoder,
    ValueCoder, M1_BINARY_CONTEXTS, M1_TREE_CONTEXTS,
};
use super::template::TEMPLATE_SLOTS;
use super::{ContextStore, EventDecoder, EventEncoder, JsonLayout, Ledger, LossTable, Tape};

pub const M2_ARM_ID: u8 = 2;
pub const M2_LANES_PER_SLOT: usize = 64;
pub const M2_LANE_STATE_BYTES: usize = 32;
pub const M2_DECLARED_STATE_BYTES: usize = TEMPLATE_SLOTS * M2_LANES_PER_SLOT * M2_LANE_STATE_BYTES;

const LANE_BUCKETS: usize = 1_024;
const ID_CLASS_ALPHABET: u32 = 64;
const TIME_CLASS_ALPHABET: u32 = 69;
const ID_MANTISSA_CONTEXTS: usize = 2_016;
const TIME_MANTISSA_CONTEXTS: usize = 2_346;

// Binary context offsets, relative to the frozen M1 binary prefix.
const ID_HIT_BASE: usize = M1_BINARY_CONTEXTS;
const ID_ZERO_BASE: usize = ID_HIT_BASE + LANE_BUCKETS;
const ID_SIGN_BASE: usize = ID_ZERO_BASE + LANE_BUCKETS;
const ID_MANTISSA_BASE: usize = ID_SIGN_BASE + LANE_BUCKETS;
const TIME_HIT_BASE: usize = ID_MANTISSA_BASE + ID_MANTISSA_CONTEXTS;
const TIME_ZERO_BASE: usize = TIME_HIT_BASE + LANE_BUCKETS;
const TIME_SIGN_BASE: usize = TIME_ZERO_BASE + LANE_BUCKETS;
const TIME_MANTISSA_BASE: usize = TIME_SIGN_BASE + LANE_BUCKETS;
pub const M2_BINARY_CONTEXTS: usize =
    TIME_MANTISSA_BASE + TIME_MANTISSA_CONTEXTS - M1_BINARY_CONTEXTS;

// Tree context offsets, absolute after the frozen M1 tree prefix.
const ID_CLASS_TREE_BASE: usize = M1_TREE_CONTEXTS;
const TIME_CLASS_TREE_BASE: usize = ID_CLASS_TREE_BASE + LANE_BUCKETS;
pub const M2_TREE_CONTEXTS: usize = TIME_CLASS_TREE_BASE + LANE_BUCKETS - M1_TREE_CONTEXTS;

const _: () = assert!(M2_BINARY_CONTEXTS == 10_506);
const _: () = assert!(M2_TREE_CONTEXTS == 2_048);
const _: () = assert!(
    ID_MANTISSA_CONTEXTS == (ID_CLASS_ALPHABET as usize * (ID_CLASS_ALPHABET as usize - 1)) / 2
);
const _: () = assert!(
    TIME_MANTISSA_CONTEXTS
        == (TIME_CLASS_ALPHABET as usize * (TIME_CLASS_ALPHABET as usize - 1)) / 2
);
const _: () = assert!(LANE_BUCKETS.is_power_of_two());

// Scaled time is nanoseconds since 0000-01-01 00:00:00 in the proleptic
// Gregorian calendar; every valid timestamp fits [0, MAX_SCALED_TIME].
const NANOS_PER_SECOND: i128 = 1_000_000_000;
const SECONDS_PER_DAY: i128 = 86_400;
// 25 full 400-year Gregorian eras of 146,097 days each.
const DAYS_TO_YEAR_10000: i128 = 25 * 146_097;
const MAX_SCALED_TIME: i128 =
    ((DAYS_TO_YEAR_10000 - 1) * SECONDS_PER_DAY + 86_399) * NANOS_PER_SECOND + 999_999_999;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum LaneState {
    Empty,
    Id { previous: i64 },
    Time { previous: i128, shape: TimeShape },
}

const _: () = assert!(std::mem::size_of::<LaneState>() <= M2_LANE_STATE_BYTES);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct TimeShape {
    separator: u8,
    fraction_width: u8,
    zone_length: u8,
    zone: [u8; 6],
}

enum Classified {
    Id(i64),
    Time { scaled: i128, shape: TimeShape },
    Other,
}

impl Classified {
    fn armed(&self) -> LaneState {
        match *self {
            Classified::Id(previous) => LaneState::Id { previous },
            Classified::Time { scaled, shape } => LaneState::Time {
                previous: scaled,
                shape,
            },
            Classified::Other => LaneState::Empty,
        }
    }
}

/// M2 wraps an inner value coder: M2 decides first, and escapes plus
/// ineligible values (untyped lanes, lane index >= 64) proceed to the inner
/// coder. Whether the inner coder is plain M1 or a longer mechanism chain
/// never changes M2's hit/escape sequence for identical input.
pub struct M2ValueCoder<Inner: ValueCoder = M1ValueCoder> {
    lanes: Box<[LaneState]>,
    inner: Inner,
}

impl Default for M2ValueCoder {
    fn default() -> Self {
        Self::new()
    }
}

impl M2ValueCoder {
    /// Fixed allocation at item start; item boundaries reset through fresh
    /// construction.
    #[must_use]
    pub fn new() -> Self {
        Self::with_inner(M1ValueCoder)
    }
}

impl<Inner: ValueCoder> M2ValueCoder<Inner> {
    #[must_use]
    pub fn with_inner(inner: Inner) -> Self {
        Self {
            lanes: vec![LaneState::Empty; TEMPLATE_SLOTS * M2_LANES_PER_SLOT].into_boxed_slice(),
            inner,
        }
    }

    /// Conservative logical model-state charge for the lane table. Actual RSS
    /// is measured separately by the runner and never inferred from this.
    #[must_use]
    pub fn declared_state_bytes(&self) -> usize {
        M2_DECLARED_STATE_BYTES
    }

    fn lane_mut(&mut self, slot: usize, lane_index: usize) -> Result<&mut LaneState, ChassisError> {
        if lane_index >= M2_LANES_PER_SLOT {
            return Err(ChassisError::LaneOutOfRange);
        }
        self.lanes
            .get_mut(slot * M2_LANES_PER_SLOT + lane_index)
            .ok_or(ChassisError::LaneOutOfRange)
    }

    #[cfg(test)]
    fn lane_state(&self, slot: usize, lane_index: usize) -> LaneState {
        self.lanes[slot * M2_LANES_PER_SLOT + lane_index]
    }

    #[cfg(test)]
    pub(super) fn inner_mut(&mut self) -> &mut Inner {
        &mut self.inner
    }
}

impl<Inner: ValueCoder> ValueCoder for M2ValueCoder<Inner> {
    fn encode_value(
        &mut self,
        events: &mut EventEncoder<'_>,
        slot: usize,
        lane_index: usize,
        lane_key: u64,
        bytes: &[u8],
    ) -> Result<(), ChassisError> {
        if lane_index >= M2_LANES_PER_SLOT {
            return self
                .inner
                .encode_value(events, slot, lane_index, lane_key, bytes);
        }
        let bucket = bucket(lane_key);
        let state = *self.lane_mut(slot, lane_index)?;
        let next = match state {
            LaneState::Empty => {
                self.inner
                    .encode_value(events, slot, lane_index, lane_key, bytes)?;
                classify(bytes).armed()
            }
            LaneState::Id { previous } => match classify(bytes) {
                Classified::Id(current) => {
                    events.bit(ID_HIT_BASE + bucket, true)?;
                    let delta = i128::from(current) - i128::from(previous);
                    encode_signed_delta(events, delta, &ID_FAMILY, bucket)?;
                    LaneState::Id { previous: current }
                }
                other => {
                    events.bit(ID_HIT_BASE + bucket, false)?;
                    self.inner
                        .encode_value(events, slot, lane_index, lane_key, bytes)?;
                    other.armed()
                }
            },
            LaneState::Time { previous, shape } => match classify(bytes) {
                Classified::Time {
                    scaled,
                    shape: current_shape,
                } if current_shape == shape => {
                    events.bit(TIME_HIT_BASE + bucket, true)?;
                    // Both scaled values are multiples of the shape's
                    // granularity, so the delta is charged in granularity
                    // units: a one-second step at width zero is one unit,
                    // not a 36-bit nanosecond magnitude.
                    let delta = scaled
                        .checked_sub(previous)
                        .ok_or(ChassisError::DeltaOverflow)?
                        / shape_granularity(shape);
                    encode_signed_delta(events, delta, &TIME_FAMILY, bucket)?;
                    LaneState::Time {
                        previous: scaled,
                        shape,
                    }
                }
                other => {
                    events.bit(TIME_HIT_BASE + bucket, false)?;
                    self.inner
                        .encode_value(events, slot, lane_index, lane_key, bytes)?;
                    other.armed()
                }
            },
        };
        *self.lane_mut(slot, lane_index)? = next;
        Ok(())
    }

    fn decode_value(
        &mut self,
        events: &mut EventDecoder<'_>,
        slot: usize,
        lane_index: usize,
        lane_key: u64,
    ) -> Result<Vec<u8>, ChassisError> {
        if lane_index >= M2_LANES_PER_SLOT {
            return self.inner.decode_value(events, slot, lane_index, lane_key);
        }
        let bucket = bucket(lane_key);
        let state = *self.lane_mut(slot, lane_index)?;
        let (bytes, next) = match state {
            LaneState::Empty => {
                let bytes = self
                    .inner
                    .decode_value(events, slot, lane_index, lane_key)?;
                let next = classify(&bytes).armed();
                (bytes, next)
            }
            LaneState::Id { previous } => {
                if events.bit(ID_HIT_BASE + bucket)? {
                    let delta = decode_signed_delta(events, &ID_FAMILY, bucket)?;
                    let current = i128::from(previous)
                        .checked_add(delta)
                        .ok_or(ChassisError::DeltaOverflow)?;
                    let current = validate_id_value(current)?;
                    (render_id(current), LaneState::Id { previous: current })
                } else {
                    let bytes = self
                        .inner
                        .decode_value(events, slot, lane_index, lane_key)?;
                    let next = classify(&bytes).armed();
                    (bytes, next)
                }
            }
            LaneState::Time { previous, shape } => {
                if events.bit(TIME_HIT_BASE + bucket)? {
                    let delta = decode_signed_delta(events, &TIME_FAMILY, bucket)?
                        .checked_mul(shape_granularity(shape))
                        .ok_or(ChassisError::DeltaOverflow)?;
                    let current = previous
                        .checked_add(delta)
                        .ok_or(ChassisError::DeltaOverflow)?;
                    validate_scaled_time(current, shape)?;
                    (
                        render_time(current, shape)?,
                        LaneState::Time {
                            previous: current,
                            shape,
                        },
                    )
                } else {
                    let bytes = self
                        .inner
                        .decode_value(events, slot, lane_index, lane_key)?;
                    let next = classify(&bytes).armed();
                    (bytes, next)
                }
            }
        };
        *self.lane_mut(slot, lane_index)? = next;
        Ok(bytes)
    }

    /// Seed qualifying ID/TIME lane states from the taught record's parsed
    /// values; no additional events are charged.
    fn after_miss_insert(&mut self, slot: usize, layout: &JsonLayout) -> Result<(), ChassisError> {
        for lane_index in 0..M2_LANES_PER_SLOT {
            *self.lane_mut(slot, lane_index)? = match layout.values().get(lane_index) {
                Some(value) => classify(value).armed(),
                None => LaneState::Empty,
            };
        }
        self.inner.after_miss_insert(slot, layout)
    }

    fn on_slots_cleared(&mut self, cleared_slots: &[usize]) -> Result<(), ChassisError> {
        for &slot in cleared_slots {
            for lane_index in 0..M2_LANES_PER_SLOT {
                *self.lane_mut(slot, lane_index)? = LaneState::Empty;
            }
        }
        self.inner.on_slots_cleared(cleared_slots)
    }
}

/// Append M2's tree alphabets in their frozen order; later mechanism blocks
/// build on this to keep every absolute context index arm-invariant.
pub(super) fn extend_m2_tree_alphabets(alphabets: &mut Vec<u32>) {
    alphabets.extend(std::iter::repeat_n(ID_CLASS_ALPHABET, LANE_BUCKETS));
    alphabets.extend(std::iter::repeat_n(TIME_CLASS_ALPHABET, LANE_BUCKETS));
}

pub fn m2_contexts() -> Result<ContextStore, ChassisError> {
    let mut alphabets = Vec::with_capacity(M2_TREE_CONTEXTS);
    extend_m2_tree_alphabets(&mut alphabets);
    chassis_contexts(M2_BINARY_CONTEXTS, &alphabets)
}

pub fn encode_m1_m2_item(
    source: &[u8],
    table: &LossTable,
    item_index: u8,
) -> Result<(Tape, Ledger), ChassisError> {
    encode_chassis_item(
        source,
        table,
        m2_contexts()?,
        M2_ARM_ID,
        item_index,
        &mut M2ValueCoder::new(),
    )
}

pub fn decode_m1_m2_item(
    tape: &Tape,
    expected_ledger: Ledger,
    table: &LossTable,
    expected_item_index: u8,
) -> Result<Vec<u8>, ChassisError> {
    decode_chassis_item(
        tape,
        expected_ledger,
        table,
        m2_contexts()?,
        M2_ARM_ID,
        expected_item_index,
        &mut M2ValueCoder::new(),
    )
}

fn bucket(lane_key: u64) -> usize {
    lane_key as usize & (LANE_BUCKETS - 1)
}

struct DeltaFamily {
    zero_base: usize,
    sign_base: usize,
    class_tree_base: usize,
    mantissa_base: usize,
    class_alphabet: u32,
}

const ID_FAMILY: DeltaFamily = DeltaFamily {
    zero_base: ID_ZERO_BASE,
    sign_base: ID_SIGN_BASE,
    class_tree_base: ID_CLASS_TREE_BASE,
    mantissa_base: ID_MANTISSA_BASE,
    class_alphabet: ID_CLASS_ALPHABET,
};

const TIME_FAMILY: DeltaFamily = DeltaFamily {
    zero_base: TIME_ZERO_BASE,
    sign_base: TIME_SIGN_BASE,
    class_tree_base: TIME_CLASS_TREE_BASE,
    mantissa_base: TIME_MANTISSA_BASE,
    class_alphabet: TIME_CLASS_ALPHABET,
};

/// Triangular offset of the shared mantissa block for a magnitude class:
/// class `c` charges `c - 1` mantissa bits at positions `0..c-1`.
fn mantissa_offset(class: u32) -> usize {
    let lower = (class - 1) as usize;
    lower * lower.saturating_sub(1) / 2
}

fn encode_signed_delta(
    events: &mut EventEncoder<'_>,
    delta: i128,
    family: &DeltaFamily,
    bucket: usize,
) -> Result<(), ChassisError> {
    events.bit(family.zero_base + bucket, delta == 0)?;
    if delta == 0 {
        return Ok(());
    }
    events.bit(family.sign_base + bucket, delta < 0)?;
    let magnitude = delta.unsigned_abs();
    let class = u128::BITS - magnitude.leading_zeros();
    if class > family.class_alphabet {
        return Err(ChassisError::DeltaOverflow);
    }
    events.symbol(family.class_tree_base + bucket, class - 1)?;
    let offset = family.mantissa_base + mantissa_offset(class);
    for position in (0..class - 1).rev() {
        events.bit(
            offset + position as usize,
            magnitude & (1_u128 << position) != 0,
        )?;
    }
    Ok(())
}

fn decode_signed_delta(
    events: &mut EventDecoder<'_>,
    family: &DeltaFamily,
    bucket: usize,
) -> Result<i128, ChassisError> {
    if events.bit(family.zero_base + bucket)? {
        return Ok(0);
    }
    let negative = events.bit(family.sign_base + bucket)?;
    let class = events.symbol(family.class_tree_base + bucket)? + 1;
    if class > family.class_alphabet {
        return Err(ChassisError::DeltaOverflow);
    }
    let mut magnitude = 1_u128
        .checked_shl(class - 1)
        .ok_or(ChassisError::DeltaOverflow)?;
    let offset = family.mantissa_base + mantissa_offset(class);
    for position in (0..class - 1).rev() {
        if events.bit(offset + position as usize)? {
            magnitude |= 1_u128 << position;
        }
    }
    let magnitude = i128::try_from(magnitude).map_err(|_| ChassisError::DeltaOverflow)?;
    // A zero flag of false with magnitude zero is impossible: the leading
    // class bit is always set.
    Ok(if negative { -magnitude } else { magnitude })
}

/// Canonical JSON integer recognizer: `0` or `-?[1-9][0-9]*`, fits `i64`, and
/// excludes `i64::MIN` so magnitude and delta arithmetic stay symmetrical.
/// Noncanonical spellings (leading zeros, `-0`, `+`, `.`, exponents) and
/// oversized magnitudes classify as Other.
fn classify_id(bytes: &[u8]) -> Option<i64> {
    let (negative, digits) = match bytes.split_first()? {
        (b'-', rest) => (true, rest),
        _ => (false, bytes),
    };
    if digits.is_empty() || digits.len() > 19 {
        return None;
    }
    if digits[0] == b'0' && (digits.len() > 1 || negative) {
        return None;
    }
    let mut value = 0_i128;
    for &byte in digits {
        if !byte.is_ascii_digit() {
            return None;
        }
        value = value * 10 + i128::from(byte - b'0');
    }
    if negative {
        value = -value;
    }
    let value = i64::try_from(value).ok()?;
    if value == i64::MIN {
        return None;
    }
    Some(value)
}

fn render_id(value: i64) -> Vec<u8> {
    value.to_string().into_bytes()
}

/// Strict quoted ISO-like timestamp recognizer:
/// `"YYYY-MM-DD[ Tt]HH:MM:SS[.1-9 digits](Z|z|+hh:mm|-hh:mm|+hhmm|-hhmm)"`.
/// Numeric epochs are not TIME; they stay in the ID lane.
fn classify_time(bytes: &[u8]) -> Option<(i128, TimeShape)> {
    if bytes.len() < 22 || bytes[0] != b'"' || bytes[bytes.len() - 1] != b'"' {
        return None;
    }
    let body = &bytes[1..bytes.len() - 1];
    if body.len() < 20 {
        return None;
    }
    let year = parse_digits(body.get(0..4)?)?;
    if body[4] != b'-' {
        return None;
    }
    let month = parse_digits(body.get(5..7)?)?;
    if body[7] != b'-' {
        return None;
    }
    let day = parse_digits(body.get(8..10)?)?;
    let separator = body[10];
    if !matches!(separator, b' ' | b'T' | b't') {
        return None;
    }
    let hour = parse_digits(body.get(11..13)?)?;
    if body[13] != b':' {
        return None;
    }
    let minute = parse_digits(body.get(14..16)?)?;
    if body[16] != b':' {
        return None;
    }
    let second = parse_digits(body.get(17..19)?)?;

    if month == 0 || month > 12 {
        return None;
    }
    if day == 0 || day > days_in_month(year, month) {
        return None;
    }
    if hour > 23 || minute > 59 || second > 59 {
        return None;
    }

    let mut cursor = 19_usize;
    let mut fraction_width = 0_u8;
    let mut fraction_nanos = 0_i128;
    if body.get(cursor) == Some(&b'.') {
        cursor += 1;
        let start = cursor;
        while cursor < body.len() && body[cursor].is_ascii_digit() && cursor - start < 9 {
            fraction_nanos = fraction_nanos * 10 + i128::from(body[cursor] - b'0');
            cursor += 1;
        }
        let width = cursor - start;
        if width == 0 {
            return None;
        }
        // A tenth consecutive digit makes the fraction invalid, not truncated.
        if cursor < body.len() && body[cursor].is_ascii_digit() {
            return None;
        }
        fraction_width = width as u8;
        fraction_nanos *= 10_i128.pow(9 - width as u32);
    }

    let zone_bytes = &body[cursor..];
    if !zone_is_valid(zone_bytes) {
        return None;
    }
    let mut zone = [0_u8; 6];
    zone[..zone_bytes.len()].copy_from_slice(zone_bytes);

    let days = days_from_year0(i64::from(year), month, day);
    let seconds = i128::from(days) * SECONDS_PER_DAY
        + i128::from(hour) * 3_600
        + i128::from(minute) * 60
        + i128::from(second);
    let scaled = seconds * NANOS_PER_SECOND + fraction_nanos;
    Some((
        scaled,
        TimeShape {
            separator,
            fraction_width,
            zone_length: zone_bytes.len() as u8,
            zone,
        },
    ))
}

fn classify(bytes: &[u8]) -> Classified {
    if let Some(value) = classify_id(bytes) {
        return Classified::Id(value);
    }
    if let Some((scaled, shape)) = classify_time(bytes) {
        return Classified::Time { scaled, shape };
    }
    Classified::Other
}

fn parse_digits(bytes: &[u8]) -> Option<u32> {
    let mut value = 0_u32;
    for &byte in bytes {
        if !byte.is_ascii_digit() {
            return None;
        }
        value = value * 10 + u32::from(byte - b'0');
    }
    Some(value)
}

fn zone_is_valid(zone: &[u8]) -> bool {
    match zone {
        [b'Z'] | [b'z'] => true,
        [sign, h1, h2, b':', m1, m2] | [sign, h1, h2, m1, m2] => {
            matches!(sign, b'+' | b'-')
                && zone_field_ok(*h1, *h2, 23)
                && zone_field_ok(*m1, *m2, 59)
        }
        _ => false,
    }
}

fn zone_field_ok(tens: u8, ones: u8, maximum: u32) -> bool {
    if !tens.is_ascii_digit() || !ones.is_ascii_digit() {
        return false;
    }
    u32::from(tens - b'0') * 10 + u32::from(ones - b'0') <= maximum
}

fn is_leap_year(year: i64) -> bool {
    year % 4 == 0 && (year % 100 != 0 || year % 400 == 0)
}

fn days_in_month(year: u32, month: u32) -> u32 {
    match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        2 if is_leap_year(i64::from(year)) => 29,
        2 => 28,
        _ => 0,
    }
}

/// Days since 0000-01-01 in the proleptic Gregorian calendar (year 0 is a
/// leap year). Standard civil-days arithmetic, valid for years 0000-9999.
fn days_from_year0(year: i64, month: u32, day: u32) -> i64 {
    let adjusted_year = year - i64::from(month <= 2);
    let era = adjusted_year.div_euclid(400);
    let year_of_era = adjusted_year.rem_euclid(400) as u64;
    let shifted_month = if month > 2 { month - 3 } else { month + 9 } as u64;
    let day_of_year = (153 * shifted_month + 2) / 5 + u64::from(day) - 1;
    let day_of_era = year_of_era * 365 + year_of_era / 4 - year_of_era / 100 + day_of_year;
    era * 146_097 + day_of_era as i64 + 60
}

/// Inverse of [`days_from_year0`].
fn year0_from_days(days: i64) -> (i64, u32, u32) {
    let shifted = days - 60;
    let era = shifted.div_euclid(146_097);
    let day_of_era = shifted.rem_euclid(146_097) as u64;
    let year_of_era =
        (day_of_era - day_of_era / 1_460 + day_of_era / 36_524 - day_of_era / 146_096) / 365;
    let year = year_of_era as i64 + era * 400;
    let day_of_year = day_of_era - (365 * year_of_era + year_of_era / 4 - year_of_era / 100);
    let shifted_month = (5 * day_of_year + 2) / 153;
    let day = (day_of_year - (153 * shifted_month + 2) / 5 + 1) as u32;
    let month = if shifted_month < 10 {
        shifted_month + 3
    } else {
        shifted_month - 9
    } as u32;
    (year + i64::from(month <= 2), month, day)
}

fn validate_id_value(value: i128) -> Result<i64, ChassisError> {
    let value = i64::try_from(value).map_err(|_| ChassisError::DeltaOverflow)?;
    if value == i64::MIN {
        return Err(ChassisError::DeltaOverflow);
    }
    Ok(value)
}

/// Nanoseconds per least-significant rendered digit of the stored shape.
/// Shapes are only ever constructed by `classify_time`, which bounds the
/// fraction width at nine digits; a wider width saturates to the finest
/// granularity and is rejected by `validate_scaled_time`.
fn shape_granularity(shape: TimeShape) -> i128 {
    10_i128.pow(9_u32.saturating_sub(u32::from(shape.fraction_width)))
}

fn validate_scaled_time(scaled: i128, shape: TimeShape) -> Result<(), ChassisError> {
    if shape.fraction_width > 9 {
        return Err(ChassisError::DeltaOverflow);
    }
    if !(0..=MAX_SCALED_TIME).contains(&scaled) {
        return Err(ChassisError::DeltaOverflow);
    }
    if scaled % shape_granularity(shape) != 0 {
        return Err(ChassisError::DeltaOverflow);
    }
    Ok(())
}

/// Exact bounds are validated before rendering; the stored shape (separator,
/// fraction width, zone bytes) is reproduced verbatim and never normalized.
fn render_time(scaled: i128, shape: TimeShape) -> Result<Vec<u8>, ChassisError> {
    validate_scaled_time(scaled, shape)?;
    let seconds_total = scaled.div_euclid(NANOS_PER_SECOND);
    let nanos = scaled.rem_euclid(NANOS_PER_SECOND);
    let days = seconds_total.div_euclid(SECONDS_PER_DAY);
    let second_of_day = seconds_total.rem_euclid(SECONDS_PER_DAY);
    let (year, month, day) = year0_from_days(days as i64);
    if !(0..=9_999).contains(&year) {
        return Err(ChassisError::DeltaOverflow);
    }
    let hour = second_of_day / 3_600;
    let minute = second_of_day % 3_600 / 60;
    let second = second_of_day % 60;

    let mut output = Vec::with_capacity(2 + 19 + 10 + 6);
    output.push(b'"');
    output.extend_from_slice(format!("{year:04}-{month:02}-{day:02}").as_bytes());
    output.push(shape.separator);
    output.extend_from_slice(format!("{hour:02}:{minute:02}:{second:02}").as_bytes());
    if shape.fraction_width > 0 {
        let width = usize::from(shape.fraction_width);
        let fraction = nanos / 10_i128.pow(9 - u32::from(shape.fraction_width));
        output.push(b'.');
        output.extend_from_slice(format!("{fraction:0width$}").as_bytes());
    }
    output.extend_from_slice(&shape.zone[..usize::from(shape.zone_length)]);
    output.push(b'"');
    Ok(output)
}
// M2 test module draft — appended to m2.rs when landing.

#[cfg(test)]
mod tests {
    use super::super::m1::encode_m1_item;
    use super::*;

    fn round_trip(source: &[u8], item_index: u8) -> Ledger {
        let table = LossTable::generate();
        let (tape, ledger) = encode_m1_m2_item(source, &table, item_index).unwrap();
        assert_eq!(
            decode_m1_m2_item(&tape, ledger, &table, item_index).unwrap(),
            source
        );
        let (repeat_tape, repeat_ledger) = encode_m1_m2_item(source, &table, item_index).unwrap();
        assert_eq!(repeat_tape.to_bytes(), tape.to_bytes());
        assert_eq!(repeat_ledger, ledger);
        ledger
    }

    fn seeded_coder(record: &[u8], slot: usize) -> (M2ValueCoder, JsonLayout) {
        let layout = JsonLayout::parse(record).unwrap();
        let mut coder = M2ValueCoder::new();
        coder.after_miss_insert(slot, &layout).unwrap();
        (coder, layout)
    }

    /// Charged events for encoding `bytes` in lane 0 of `slot` after seeding
    /// the coder with `seed_record`.
    fn lane_events(seed_record: &[u8], bytes: &[u8]) -> u64 {
        let table = LossTable::generate();
        let (mut coder, layout) = seeded_coder(seed_record, 3);
        let lane_key = super::super::chassis::lane_key(layout.skeleton(), 0).unwrap();
        let mut events = EventEncoder::new(&table, m2_contexts().unwrap(), M2_ARM_ID, 0);
        coder
            .encode_value(&mut events, 3, 0, lane_key, bytes)
            .unwrap();
        events.ledger().modeled_binary_events
    }

    #[test]
    fn mixed_item_round_trips_exactly_and_deterministically() {
        let mut source = Vec::new();
        source.extend_from_slice(b"{\"id\":100,\"ts\":\"2026-07-22T10:00:00Z\",\"msg\":\"a\"}\n");
        source.extend_from_slice(b"{\"id\":101,\"ts\":\"2026-07-22T10:00:01Z\",\"msg\":\"bb\"}\n");
        source.extend_from_slice(b"{\"id\":99,\"ts\":\"2026-07-22T10:00:01Z\",\"msg\":\"c\"}\n");
        source.extend_from_slice(b"{\"other\":[1,2]}\n");
        source.extend_from_slice(
            b"{\"id\":150,\"ts\":\"2026-07-22 10:00:02+00:00\",\"msg\":\"d\"}\n",
        );
        source.extend_from_slice(b"\n");
        source.extend_from_slice(b"{bad}\n");
        source
            .extend_from_slice(b"{\"id\":151,\"ts\":\"2026-07-22 10:00:03+00:00\",\"msg\":\"e\"}");
        let ledger = round_trip(&source, 0);
        assert_eq!(ledger.records, 8);
    }

    #[test]
    fn id_deltas_cover_positive_negative_and_zero() {
        let source = b"{\"a\":10}\n{\"a\":10}\n{\"a\":25}\n{\"a\":-3}\n{\"a\":-3}\n{\"a\":0}\n";
        round_trip(source, 1);
    }

    #[test]
    fn id_boundaries_and_noncanonical_spellings_classify_exactly() {
        assert_eq!(classify_id(b"0"), Some(0));
        assert_eq!(classify_id(b"9223372036854775807"), Some(i64::MAX));
        assert_eq!(classify_id(b"-9223372036854775807"), Some(-i64::MAX));
        for other in [
            b"-9223372036854775808".as_slice(), // i64::MIN excluded
            b"9223372036854775808",             // > i64::MAX
            b"-0",
            b"01",
            b"+1",
            b"1.0",
            b"1e3",
            b"",
            b"\"1\"",
            b"12345678901234567890123",
        ] {
            assert!(
                !matches!(classify(other), Classified::Id(_)),
                "accepted {other:?}"
            );
        }
        // Boundary values round trip through the full arm.
        let source = b"{\"a\":9223372036854775807}\n{\"a\":-9223372036854775807}\n{\"a\":9223372036854775807}\n";
        round_trip(source, 2);
        // i64::MIN spelling stays lossless through the M1 escape.
        let min = b"{\"a\":-9223372036854775808}\n{\"a\":-9223372036854775808}\n";
        round_trip(min, 3);
    }

    #[test]
    fn time_fraction_widths_zero_through_nine_round_trip() {
        let mut source = Vec::new();
        source.extend_from_slice(b"{\"t\":\"2026-01-02T03:04:05Z\"}\n");
        for width in 1..=9 {
            let fraction = &"050000009"[..width];
            source.extend_from_slice(
                format!("{{\"t\":\"2026-01-02T03:04:05.{fraction}Z\"}}\n").as_bytes(),
            );
            // Same shape twice in a row exercises the delta hit path.
            source.extend_from_slice(
                format!("{{\"t\":\"2026-01-02T03:04:06.{fraction}Z\"}}\n").as_bytes(),
            );
        }
        round_trip(&source, 4);
    }

    #[test]
    fn every_separator_and_zone_spelling_round_trips() {
        let mut source = Vec::new();
        for separator in ['T', 't', ' '] {
            for zone in ["Z", "z", "+00:00", "-05:30", "+0000", "-0530", "+23:59"] {
                source.extend_from_slice(
                    format!("{{\"t\":\"2026-07-22{separator}10:00:00{zone}\"}}\n").as_bytes(),
                );
                source.extend_from_slice(
                    format!("{{\"t\":\"2026-07-22{separator}10:00:05{zone}\"}}\n").as_bytes(),
                );
            }
        }
        round_trip(&source, 5);
    }

    #[test]
    fn gregorian_leap_day_boundaries_classify_exactly() {
        assert!(classify_time(b"\"2024-02-29T00:00:00Z\"").is_some());
        assert!(classify_time(b"\"2000-02-29T00:00:00Z\"").is_some());
        assert!(classify_time(b"\"0000-02-29T00:00:00Z\"").is_some());
        assert!(classify_time(b"\"2023-02-29T00:00:00Z\"").is_none());
        assert!(classify_time(b"\"1900-02-29T00:00:00Z\"").is_none());
        assert!(classify_time(b"\"2024-02-30T00:00:00Z\"").is_none());
        let source = b"{\"t\":\"2024-02-28T23:59:59Z\"}\n{\"t\":\"2024-02-29T00:00:00Z\"}\n{\"t\":\"2024-03-01T00:00:00Z\"}\n";
        round_trip(source, 6);
    }

    #[test]
    fn year_zero_and_year_9999_round_trip_with_extreme_deltas() {
        let source = b"{\"t\":\"0000-01-01T00:00:00Z\"}\n{\"t\":\"9999-12-31T23:59:59Z\"}\n{\"t\":\"0000-01-01T00:00:00Z\"}\n";
        round_trip(source, 7);
    }

    #[test]
    fn invalid_dates_and_times_escape_to_m1() {
        for invalid in [
            b"\"2026-13-01T00:00:00Z\"".as_slice(),
            b"\"2026-00-01T00:00:00Z\"",
            b"\"2026-01-00T00:00:00Z\"",
            b"\"2026-01-32T00:00:00Z\"",
            b"\"2026-04-31T00:00:00Z\"",
            b"\"2026-01-01T24:00:00Z\"",
            b"\"2026-01-01T00:60:00Z\"",
            b"\"2026-01-01T00:00:60Z\"", // leap second rejected
            b"\"2026-01-01T00:00:00\"",  // missing zone
            b"\"2026-01-01T00:00:00.Z\"",
            b"\"2026-01-01T00:00:00.0000000000Z\"",
            b"\"2026-01-01T00:00:00+24:00\"",
            b"\"2026-01-01T00:00:00+00:60\"",
            b"\"2026-01-01T00:00:00+0:00\"",
            b"\"2026-01-01X00:00:00Z\"",
            b"\"2026/01/01T00:00:00Z\"",
            b"\"26-01-01T00:00:00Z\"",
            b"2026-01-01T00:00:00Z", // unquoted
        ] {
            assert!(
                matches!(classify(invalid), Classified::Other),
                "accepted {:?}",
                std::str::from_utf8(invalid)
            );
        }
        let source = b"{\"t\":\"2026-01-01T00:00:00Z\"}\n{\"t\":\"2026-01-01T00:00:60Z\"}\n{\"t\":\"2026-01-01T00:00:01Z\"}\n";
        round_trip(source, 8);
    }

    #[test]
    fn shape_changes_escape_and_rearm_with_the_new_shape() {
        // Zone spelling change, separator change, and width change each force
        // one escape; the following same-shape record hits again.
        let source = b"{\"t\":\"2026-01-01T00:00:00Z\"}\n{\"t\":\"2026-01-01T00:00:01Z\"}\n{\"t\":\"2026-01-01T00:00:02+00:00\"}\n{\"t\":\"2026-01-01T00:00:03+00:00\"}\n{\"t\":\"2026-01-01 00:00:04+00:00\"}\n{\"t\":\"2026-01-01 00:00:05.5+00:00\"}\n{\"t\":\"2026-01-01 00:00:06.6+00:00\"}\n";
        round_trip(source, 9);

        let escape_then_hit = lane_events(
            b"{\"t\":\"2026-01-01T00:00:00Z\"}",
            b"\"2026-01-01T00:00:01+00:00\"",
        );
        let hit = lane_events(
            b"{\"t\":\"2026-01-01T00:00:00Z\"}",
            b"\"2026-01-01T00:00:01Z\"",
        );
        // The escape charges exactly one bit plus the unchanged M1 cost; the
        // hit path never pays M1 byte costs.
        assert!(escape_then_hit > hit);
    }

    #[test]
    fn miss_seeding_arms_lanes_without_extra_events() {
        // After seeding from the miss, an identical value costs exactly the
        // hit bit plus the zero flag.
        assert_eq!(lane_events(b"{\"a\":100}", b"100"), 2);
        // Delta one: hit + zero + sign + 6-bit class tree + empty mantissa.
        assert_eq!(lane_events(b"{\"a\":100}", b"101"), 9);
        // Time zero delta.
        assert_eq!(
            lane_events(
                b"{\"t\":\"2026-01-01T00:00:00Z\"}",
                b"\"2026-01-01T00:00:00Z\""
            ),
            2
        );
    }

    #[test]
    fn coarse_shapes_charge_deltas_in_few_events() {
        // The purpose of granularity units: a one-second step at width zero
        // is one unit (class 1, empty mantissa): 1 hit + 1 zero-flag + 1 sign
        // + 7 class-tree bits = 10 events, not a 36-bit nanosecond mantissa.
        assert_eq!(
            lane_events(
                b"{\"t\":\"2026-07-22T10:00:00Z\"}",
                b"\"2026-07-22T10:00:01Z\""
            ),
            10
        );
        // A legitimate in-range negative delta through the same division.
        assert_eq!(
            lane_events(
                b"{\"t\":\"2026-07-22T10:00:05Z\"}",
                b"\"2026-07-22T10:00:04Z\""
            ),
            10
        );
    }

    #[test]
    fn decreasing_timestamps_round_trip_through_unit_deltas() {
        let source = b"{\"t\":\"2026-07-22T10:00:09.500Z\"}\n{\"t\":\"2026-07-22T10:00:07.250Z\"}\n{\"t\":\"2026-07-22T10:00:01.125Z\"}\n";
        round_trip(source, 11);
    }

    #[test]
    fn maximum_delta_event_counts_match_the_frozen_plan() {
        // ID: previous -(2^63-1), current 2^63-1 => magnitude 2^64-2, class 64:
        // 1 hit + 1 zero + 1 sign + 6 class + 63 mantissa = 72.
        assert_eq!(
            lane_events(b"{\"a\":-9223372036854775807}", b"9223372036854775807"),
            72
        );
        // TIME: scaled 0 to the maximum timestamp, class 69:
        // 1 hit + 1 zero + 1 sign + 7 class + 68 mantissa = 78.
        assert_eq!(
            lane_events(
                b"{\"t\":\"0000-01-01T00:00:00.000000000Z\"}",
                b"\"9999-12-31T23:59:59.999999999Z\""
            ),
            78
        );
    }

    #[test]
    fn untyped_values_add_no_recurring_m2_tax() {
        let table = LossTable::generate();
        let source = b"{\"a\":\"x\",\"b\":[1]}\n{\"a\":\"y\",\"b\":[2]}\n{\"a\":\"z\",\"b\":[3]}\n";
        let (_, m1_ledger) = encode_m1_item(source, &table, 4).unwrap();
        let (_, m2_ledger) = encode_m1_m2_item(source, &table, 4).unwrap();
        assert_eq!(
            m2_ledger.modeled_binary_events,
            m1_ledger.modeled_binary_events
        );
        assert_eq!(m2_ledger.modeled_loss_q24, m1_ledger.modeled_loss_q24);
    }

    #[test]
    fn armed_lane_escaping_to_other_goes_silent() {
        // Arm as ID, escape to a string once, then further strings must cost
        // exactly the M1 events with no recurring escape bit.
        let table = LossTable::generate();
        let (mut coder, layout) = seeded_coder(b"{\"a\":1}", 0);
        let lane_key = super::super::chassis::lane_key(layout.skeleton(), 0).unwrap();
        let mut events = EventEncoder::new(&table, m2_contexts().unwrap(), M2_ARM_ID, 0);

        let mut m1_events = EventEncoder::new(&table, m2_contexts().unwrap(), M2_ARM_ID, 0);
        super::super::chassis::encode_m1_value(&mut m1_events, lane_key, b"\"x\"").unwrap();
        let m1_cost = m1_events.ledger().modeled_binary_events;

        coder
            .encode_value(&mut events, 0, 0, lane_key, b"\"x\"")
            .unwrap();
        let first = events.ledger().modeled_binary_events;
        assert_eq!(first, m1_cost + 1); // one escape bit

        coder
            .encode_value(&mut events, 0, 0, lane_key, b"\"x\"")
            .unwrap();
        let second = events.ledger().modeled_binary_events - first;
        assert_eq!(second, m1_cost); // silent: no recurring escape bit
    }

    #[test]
    fn lane_index_63_is_typed_and_64_is_plain_m1() {
        let keys: Vec<String> = (0..66).map(|i| format!("\"k{i:02}\":{i}")).collect();
        let record = format!("{{{}}}", keys.join(","));
        let next: Vec<String> = (0..66).map(|i| format!("\"k{i:02}\":{}", i + 1)).collect();
        let record2 = format!("{{{}}}", next.join(","));
        let source = format!("{record}\n{record2}\n{record}\n");
        round_trip(source.as_bytes(), 10);

        let table = LossTable::generate();
        let layout = JsonLayout::parse(record.as_bytes()).unwrap();
        let mut coder = M2ValueCoder::new();
        coder.after_miss_insert(0, &layout).unwrap();
        let key63 = super::super::chassis::lane_key(layout.skeleton(), 63).unwrap();
        let key64 = super::super::chassis::lane_key(layout.skeleton(), 64).unwrap();

        let mut events = EventEncoder::new(&table, m2_contexts().unwrap(), M2_ARM_ID, 0);
        coder
            .encode_value(&mut events, 0, 63, key63, b"63")
            .unwrap();
        assert_eq!(events.ledger().modeled_binary_events, 2); // typed zero delta

        let mut plain = EventEncoder::new(&table, m2_contexts().unwrap(), M2_ARM_ID, 0);
        super::super::chassis::encode_m1_value(&mut plain, key64, b"64").unwrap();
        let mut lane64 = EventEncoder::new(&table, m2_contexts().unwrap(), M2_ARM_ID, 0);
        coder
            .encode_value(&mut lane64, 0, 64, key64, b"64")
            .unwrap();
        assert_eq!(
            lane64.ledger().modeled_binary_events,
            plain.ledger().modeled_binary_events
        );
    }

    #[test]
    fn eviction_clears_single_and_multiple_slots() {
        let (mut coder, layout) = seeded_coder(b"{\"a\":1}", 5);
        coder.after_miss_insert(9, &layout).unwrap();
        assert_eq!(coder.lane_state(5, 0), LaneState::Id { previous: 1 });
        assert_eq!(coder.lane_state(9, 0), LaneState::Id { previous: 1 });
        coder.on_slots_cleared(&[5]).unwrap();
        assert_eq!(coder.lane_state(5, 0), LaneState::Empty);
        assert_eq!(coder.lane_state(9, 0), LaneState::Id { previous: 1 });
        coder.after_miss_insert(5, &layout).unwrap();
        coder.on_slots_cleared(&[5, 9]).unwrap();
        assert_eq!(coder.lane_state(5, 0), LaneState::Empty);
        assert_eq!(coder.lane_state(9, 0), LaneState::Empty);
    }

    #[test]
    fn decoder_rejects_delta_overflow() {
        let table = LossTable::generate();
        let (encoder_coder, layout) = seeded_coder(b"{\"a\":9223372036854775807}", 0);
        let lane_key = super::super::chassis::lane_key(layout.skeleton(), 0).unwrap();
        // Hand-write a hit with delta +1 past i64::MAX.
        let mut events = EventEncoder::new(&table, m2_contexts().unwrap(), M2_ARM_ID, 0);
        events.bit(ID_HIT_BASE + bucket(lane_key), true).unwrap();
        encode_signed_delta(&mut events, 1, &ID_FAMILY, bucket(lane_key)).unwrap();
        let (tape, _) = events.finish();

        let mut decoder_coder = M2ValueCoder::new();
        decoder_coder.after_miss_insert(0, &layout).unwrap();
        let mut decoder = EventDecoder::new(&table, m2_contexts().unwrap(), &tape);
        assert_eq!(
            decoder_coder.decode_value(&mut decoder, 0, 0, lane_key),
            Err(ChassisError::DeltaOverflow)
        );
        let _ = encoder_coder;
    }

    /// Hand-writes a TIME hit whose signed delta is `delta` against a lane
    /// seeded from `seed_record`, and returns the decoder's verdict.
    fn hostile_time_delta(seed_record: &[u8], delta: i128) -> Result<Vec<u8>, ChassisError> {
        let table = LossTable::generate();
        let layout = JsonLayout::parse(seed_record).unwrap();
        let lane_key = super::super::chassis::lane_key(layout.skeleton(), 0).unwrap();
        let mut events = EventEncoder::new(&table, m2_contexts().unwrap(), M2_ARM_ID, 0);
        events.bit(TIME_HIT_BASE + bucket(lane_key), true).unwrap();
        encode_signed_delta(&mut events, delta, &TIME_FAMILY, bucket(lane_key)).unwrap();
        let (tape, _) = events.finish();

        let mut decoder_coder = M2ValueCoder::new();
        decoder_coder.after_miss_insert(0, &layout).unwrap();
        let mut decoder = EventDecoder::new(&table, m2_contexts().unwrap(), &tape);
        decoder_coder.decode_value(&mut decoder, 0, 0, lane_key)
    }

    #[test]
    fn decoder_rejects_time_deltas_past_the_calendar_bounds() {
        // One granularity unit (one second at width zero) past the maximum.
        assert_eq!(
            hostile_time_delta(b"{\"t\":\"9999-12-31T23:59:59Z\"}", 1),
            Err(ChassisError::DeltaOverflow)
        );
        // One unit before 0000-01-01T00:00:00Z.
        assert_eq!(
            hostile_time_delta(b"{\"t\":\"0000-01-01T00:00:00Z\"}", -1),
            Err(ChassisError::DeltaOverflow)
        );
        // A maximum-class delta (69 all-ones mantissa bits, ~5.9e20) exceeds
        // the calendar range while exercising the last TIME mantissa context.
        assert_eq!(
            hostile_time_delta(
                b"{\"t\":\"0000-01-01T00:00:00.000000000Z\"}",
                (1_i128 << 69) - 1
            ),
            Err(ChassisError::DeltaOverflow)
        );
    }

    #[test]
    fn time_deltas_are_charged_in_shape_granularity_units() {
        // One unit at width 3 is one millisecond; one unit at width 9 is one
        // nanosecond. Sub-granularity residues are unrepresentable through
        // the unit grammar, and the validator still rejects them directly.
        assert_eq!(
            hostile_time_delta(b"{\"t\":\"2026-01-01T00:00:00.000Z\"}", 1),
            Ok(b"\"2026-01-01T00:00:00.001Z\"".to_vec())
        );
        assert_eq!(
            hostile_time_delta(b"{\"t\":\"2026-01-01T00:00:00.000000000Z\"}", 1),
            Ok(b"\"2026-01-01T00:00:00.000000001Z\"".to_vec())
        );
        let (scaled, shape) = classify_time(b"\"2026-01-01T00:00:00.000Z\"").unwrap();
        assert_eq!(validate_scaled_time(scaled, shape), Ok(()));
        assert_eq!(
            validate_scaled_time(scaled + 1, shape),
            Err(ChassisError::DeltaOverflow)
        );
    }

    #[test]
    fn state_footprint_is_fixed_before_and_after_heavy_observations() {
        let mut coder = M2ValueCoder::new();
        assert_eq!(coder.declared_state_bytes(), M2_DECLARED_STATE_BYTES);
        assert_eq!(coder.lanes.len(), TEMPLATE_SLOTS * M2_LANES_PER_SLOT);
        let layout = JsonLayout::parse(b"{\"a\":1,\"t\":\"2026-01-01T00:00:00Z\"}").unwrap();
        for slot in 0..TEMPLATE_SLOTS {
            coder.after_miss_insert(slot, &layout).unwrap();
        }
        assert_eq!(coder.declared_state_bytes(), M2_DECLARED_STATE_BYTES);
        assert_eq!(coder.lanes.len(), TEMPLATE_SLOTS * M2_LANES_PER_SLOT);
    }

    #[test]
    fn arm_and_item_identity_are_bound() {
        let table = LossTable::generate();
        let source = b"{\"a\":1}\n";
        let (tape, ledger) = encode_m1_m2_item(source, &table, 3).unwrap();
        assert_eq!(
            decode_m1_m2_item(&tape, ledger, &table, 4),
            Err(ChassisError::TapeIdentityMismatch)
        );
        let (m1_tape, m1_ledger) = encode_m1_item(source, &table, 3).unwrap();
        assert_eq!(
            decode_m1_m2_item(&m1_tape, m1_ledger, &table, 3),
            Err(ChassisError::TapeIdentityMismatch)
        );
    }

    #[test]
    fn decoded_values_cannot_inject_structure_through_typed_lanes() {
        // A crafted tape that teaches {"a":1}, then hits with an M1 escape
        // whose literal bytes would splice new fields must still be rejected
        // by the chassis reparse.
        let table = LossTable::generate();
        let layout = JsonLayout::parse(b"{\"a\":1}").unwrap();
        let lane = super::super::chassis::lane_key(layout.skeleton(), 0).unwrap();
        let mut events = EventEncoder::new(&table, m2_contexts().unwrap(), M2_ARM_ID, 0);
        let mut helper = M2ValueCoder::new();

        events
            .bit(super::super::chassis::MORE_CONTEXT, true)
            .unwrap();
        events.record().unwrap();
        events
            .symbol(
                super::super::chassis::type_tree(super::super::chassis::RecordType::Miss),
                super::super::chassis::RecordType::Miss as u32,
            )
            .unwrap();
        events.literal(b"{\"a\":1}").unwrap();
        helper.after_miss_insert(0, &layout).unwrap();

        events
            .bit(super::super::chassis::MORE_CONTEXT, true)
            .unwrap();
        events.record().unwrap();
        events
            .symbol(
                super::super::chassis::type_tree(super::super::chassis::RecordType::Miss),
                super::super::chassis::RecordType::Hit as u32,
            )
            .unwrap();
        events
            .bit(super::super::chassis::SAME_TEMPLATE_CONTEXT, true)
            .unwrap();
        // Armed ID lane: escape bit, then M1-coded injected bytes.
        events.bit(ID_HIT_BASE + bucket(lane), false).unwrap();
        super::super::chassis::encode_m1_value(&mut events, lane, b"1,\"b\":2").unwrap();
        events
            .bit(super::super::chassis::MORE_CONTEXT, false)
            .unwrap();
        events
            .bit(super::super::chassis::TERMINATED_CONTEXT, false)
            .unwrap();
        let (tape, ledger) = events.finish();
        assert_eq!(
            decode_m1_m2_item(&tape, ledger, &table, 0),
            Err(ChassisError::InvalidDecodedLayout)
        );
    }

    #[test]
    fn scaled_time_calendar_arithmetic_is_exact() {
        assert_eq!(days_from_year0(0, 1, 1), 0);
        assert_eq!(days_from_year0(0, 3, 1), 60); // year 0 is a leap year
        assert_eq!(days_from_year0(10_000, 1, 1) as i128, DAYS_TO_YEAR_10000);
        for (year, month, day) in [
            (0, 1, 1),
            (0, 12, 31),
            (1, 1, 1),
            (1969, 12, 31),
            (1970, 1, 1),
            (2000, 2, 29),
            (2024, 2, 29),
            (2026, 7, 22),
            (9999, 12, 31),
        ] {
            let days = days_from_year0(year, month, day);
            assert_eq!(
                year0_from_days(days),
                (year, month, day),
                "round trip failed for {year:04}-{month:02}-{day:02}"
            );
        }
    }

    #[test]
    fn calendar_conversion_is_a_bijection_over_every_supported_day() {
        for day_number in 0..DAYS_TO_YEAR_10000 as i64 {
            let (year, month, day) = year0_from_days(day_number);
            assert!((0..=9_999).contains(&year), "day {day_number}: year {year}");
            assert!((1..=12).contains(&month), "day {day_number}: month {month}");
            assert!(
                day >= 1 && day <= days_in_month(year as u32, month),
                "day {day_number}: {year:04}-{month:02}-{day:02}"
            );
            assert_eq!(
                days_from_year0(year, month, day),
                day_number,
                "inverse failed at {year:04}-{month:02}-{day:02}"
            );
        }
    }
}
