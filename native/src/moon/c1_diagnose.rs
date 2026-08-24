//! Provenance-neutral, byte-transparent C1 residual diagnostic.
//!
//! Canonical C1 and this diagnostic share one event generator. The streaming
//! observer is invoked after coder/model updates and cannot affect a charged
//! probability. Reports are mechanism-local; the CLI never infers input class.

use std::error::Error;
use std::fmt::{Display, Formatter};
use std::mem::size_of;

use sha2::{Digest, Sha256};

use super::c1::{
    c1_declared_state_bytes, encode_c1_item_with_bits, encode_c1_item_with_bits_observer, C1Error,
    C1ObservedByte, MATCH_HASH_BITS, MATCH_MIN_LENGTH, MATCH_WINDOW_BYTES,
};
use super::diagnose::{
    classify, digit_overlay, hex_id_overlay, timestamp_overlay, ByteClass, CLASS_COUNT, Q24_SCALE,
};
use crate::s0::{Ledger, LossTable};

pub const C1_DIAGNOSIS_SCHEMA: &str = "clab-moon-c1-residual-diagnostic-v2";
const DEPTHS: [usize; 3] = [1, 2, 4];
const NO_POS: u32 = u32::MAX;
const FNV_OFFSET: u64 = 14_695_981_039_346_656_037;
const FNV_PRIME: u64 = 1_099_511_628_211;
// Tape wire layout for C1 (which has no raw literals): magic (4), arm (1),
// item (1), bit count (8), literal count (8), and SHA-256 digest (32).
const C1_TAPE_FIXED_WIRE_BYTES: u64 = 54;

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct Bucket {
    pub bytes: u64,
    pub loss_q24: u64,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct ShadowBucket {
    /// Per-position opportunity count among retained verified candidates;
    /// never a span length or non-overlapping byte mass.
    pub candidate_opportunities_upper_bound: u64,
    pub any_correct_bytes_upper_bound: u64,
    pub any_correct_loss_q24_upper_bound: u64,
    pub incremental_any_correct_bytes_upper_bound: u64,
    pub incremental_any_correct_loss_q24_upper_bound: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StateAccounting {
    pub canonical_c1_declared_bytes: u64,
    pub c1_derived_stretch_tables_bytes: u64,
    pub shared_loss_table_bytes: u64,
    pub shadow_table_bytes: u64,
    pub source_input_bytes: u64,
    pub classification_bytes: u64,
    pub overlay_bit_payload_bytes: u64,
    pub aggregation_struct_bytes: u64,
    pub retained_observed_tape_payload_bytes: u64,
    pub comparison_tape_payload_bytes: u64,
    pub accounted_concurrent_logical_bytes: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct C1ResidualReport {
    pub item_index: u8,
    pub sse_bucket_bits: u32,
    pub source_bytes: u64,
    pub tape_bytes: u64,
    pub ledger: Ledger,
    /// Full ordered charged-event identity: typed byte events followed by the
    /// typed terminal continuation event.
    pub charged_event_digest_sha256: String,
    pub modeled_bits_loss_q24: u64,
    pub framing_loss_q24_including_terminal: u64,
    pub terminal_loss_q24: u64,
    pub class_buckets: [Bucket; CLASS_COUNT],
    pub overlays: [Bucket; 3],
    pub live: Bucket,
    pub not_live: Bucket,
    pub valid_match_bits: u64,
    pub correct_match_bits: u64,
    pub match_breaks: u64,
    pub initial_acquisitions: u64,
    pub post_break_reacquisitions: u64,
    pub unresolved_breaks: u64,
    pub terminal_censored_lag: Option<u64>,
    pub acquisition_empty_slot: u64,
    pub acquisition_prefix_verification_failed: u64,
    pub acquisition_window_expired: u64,
    pub acquisition_live_suppressed: u64,
    pub length_buckets: [Bucket; 6],
    pub distance_buckets: [Bucket; 8],
    pub reacquisition_lag: [u64; 6],
    pub shadow: [ShadowBucket; 3],
    pub state_accounting: StateAccounting,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum C1DiagnoseError {
    C1(C1Error),
    ObserverDivergedFromCanonical,
    ObserverEventMisattributed,
    ClosureDoesNotHold,
    ArithmeticOverflow,
}
impl Display for C1DiagnoseError {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::C1(e) => write!(f, "C1 arm error during diagnosis: {e}"),
            Self::ObserverDivergedFromCanonical => {
                write!(f, "observed C1 diverged from canonical C1")
            }
            Self::ObserverEventMisattributed => {
                write!(f, "observer position or byte was misattributed")
            }
            Self::ClosureDoesNotHold => write!(f, "diagnostic closure invariant failed"),
            Self::ArithmeticOverflow => write!(f, "diagnostic accounting overflowed"),
        }
    }
}
impl Error for C1DiagnoseError {}
impl From<C1Error> for C1DiagnoseError {
    fn from(e: C1Error) -> Self {
        Self::C1(e)
    }
}

fn fnv(seed: u64, bytes: &[u8]) -> u64 {
    bytes
        .iter()
        .fold(seed, |h, b| (h ^ u64::from(*b)).wrapping_mul(FNV_PRIME))
}
fn key(bytes: &[u8], bits: u32) -> usize {
    (fnv(fnv(FNV_OFFSET, &[0xc1]), bytes) as usize) & ((1 << bits) - 1)
}
fn verified(source: &[u8], candidate: usize, position: usize) -> bool {
    candidate >= MATCH_MIN_LENGTH
        && candidate < position
        && position - candidate <= MATCH_WINDOW_BYTES
        && source[candidate - MATCH_MIN_LENGTH..candidate]
            == source[position - MATCH_MIN_LENGTH..position]
}
struct Oracle {
    slots: Box<[[u32; 4]]>,
    bits: u32,
}
impl Oracle {
    fn new(bits: u32) -> Self {
        Self {
            slots: vec![[NO_POS; 4]; 1 << bits].into_boxed_slice(),
            bits,
        }
    }
    fn bytes(&self) -> usize {
        self.slots.len() * size_of::<[u32; 4]>()
    }
    fn select(
        source: &[u8],
        prior: &[u32; 4],
        position: usize,
        depth: usize,
    ) -> (bool, bool, usize) {
        let mut opportunity = false;
        let mut any_correct = false;
        let mut inspected = 0;
        for candidate in prior[..depth].iter().copied() {
            inspected += 1;
            if candidate == NO_POS {
                continue;
            }
            let candidate = candidate as usize;
            if verified(source, candidate, position) {
                opportunity = true;
                any_correct |= source[candidate] == source[position];
            }
        }
        (opportunity, any_correct, inspected)
    }
    fn rotate_in(slot: &mut [u32; 4], position: u32) {
        slot.rotate_right(1);
        slot[0] = position;
    }
    fn observe(&mut self, source: &[u8], position: usize) -> Option<[(bool, bool); 3]> {
        let mut out = [(false, false); 3];
        if position >= MATCH_MIN_LENGTH {
            let lookup = key(&source[position - MATCH_MIN_LENGTH..position], self.bits);
            let prior = self.slots[lookup];
            for (i, depth) in DEPTHS.into_iter().enumerate() {
                let (opportunity, any_correct, _) = Self::select(source, &prior, position, depth);
                out[i] = (opportunity, any_correct);
            }
        }
        let next_position = position.checked_add(1)?;
        if next_position >= MATCH_MIN_LENGTH {
            let insertion = key(
                &source[next_position - MATCH_MIN_LENGTH..=position],
                self.bits,
            );
            let candidate = u32::try_from(next_position).ok()?;
            if candidate == NO_POS {
                return None;
            }
            Self::rotate_in(&mut self.slots[insertion], candidate);
        }
        Some(out)
    }
}

fn len_bucket(n: u32) -> usize {
    match n {
        0..=5 => 0,
        6..=7 => 1,
        8..=15 => 2,
        16..=31 => 3,
        32..=63 => 4,
        _ => 5,
    }
}
fn dist_bucket(n: u32) -> usize {
    match n {
        0 => 0,
        1..=64 => 1,
        65..=256 => 2,
        257..=1024 => 3,
        1025..=4096 => 4,
        4097..=65536 => 5,
        65537..=1048576 => 6,
        _ => 7,
    }
}
fn lag_bucket(n: u64) -> usize {
    match n {
        0 => 0,
        1 => 1,
        2..=3 => 2,
        4..=7 => 3,
        8..=31 => 4,
        _ => 5,
    }
}

struct Acc<'a> {
    source: &'a [u8],
    classes: Vec<ByteClass>,
    masks: [Vec<bool>; 3],
    oracle: Oracle,
    next: usize,
    expected_match_pre_state: (u32, u32),
    bad: bool,
    digest: Sha256,
    modeled: u64,
    framing: u64,
    classes_out: [Bucket; CLASS_COUNT],
    overlays: [Bucket; 3],
    live: Bucket,
    not_live: Bucket,
    length: [Bucket; 6],
    distance: [Bucket; 8],
    valid: u64,
    correct: u64,
    breaks: u64,
    initial: u64,
    post: u64,
    pending: Option<u64>,
    lags: [u64; 6],
    empty: u64,
    prefix: u64,
    window: u64,
    suppressed: u64,
    shadow: [ShadowBucket; 3],
}

fn update_event_digest(digest: &mut Sha256, event: &C1ObservedByte) {
    digest.update([0x01]);
    digest.update((event.position as u64).to_le_bytes());
    digest.update([event.byte]);
    digest.update(event.continuation_loss_q24.to_le_bytes());
    for loss in event.bit_loss_q24 {
        digest.update(loss.to_le_bytes());
    }
    digest.update([event.match_valid_mask, event.match_correct_mask]);
    digest.update(event.match_length_before.to_le_bytes());
    digest.update(event.match_distance_before.to_le_bytes());
    digest.update(event.match_length_after.to_le_bytes());
    digest.update(event.match_distance_after.to_le_bytes());
    digest.update([
        u8::from(event.match_broke),
        u8::from(event.acquisition_initial),
        u8::from(event.acquisition_after_break),
        u8::from(event.acquisition_empty_slot),
        u8::from(event.acquisition_prefix_verification_failed),
        u8::from(event.acquisition_window_expired),
        u8::from(event.acquisition_live_suppressed),
    ]);
}

fn update_terminal_event_digest(digest: &mut Sha256, terminal_loss_q24: u32) {
    digest.update([0xff]);
    digest.update(terminal_loss_q24.to_le_bytes());
}

fn acquisition_position_bounds_hold(event: &C1ObservedByte) -> bool {
    let position = event.position;
    let first_lookup = MATCH_MIN_LENGTH - 1;
    (position != first_lookup || event.acquisition_empty_slot)
        && (!event.acquisition_initial || position >= MATCH_MIN_LENGTH)
        && (!event.acquisition_prefix_verification_failed || position >= MATCH_MIN_LENGTH)
        && (!event.acquisition_after_break || position > MATCH_MIN_LENGTH)
        && (!event.acquisition_window_expired
            || MATCH_WINDOW_BYTES
                .checked_add(MATCH_MIN_LENGTH)
                .is_some_and(|first_expiry| position >= first_expiry))
}

impl<'a> Acc<'a> {
    fn new(source: &'a [u8]) -> Self {
        Self {
            source,
            classes: classify(source),
            masks: [
                digit_overlay(source),
                timestamp_overlay(source),
                hex_id_overlay(source),
            ],
            oracle: Oracle::new(MATCH_HASH_BITS),
            next: 0,
            expected_match_pre_state: (0, 0),
            bad: false,
            digest: Sha256::new(),
            modeled: 0,
            framing: 0,
            classes_out: [Bucket::default(); CLASS_COUNT],
            overlays: [Bucket::default(); 3],
            live: Bucket::default(),
            not_live: Bucket::default(),
            length: [Bucket::default(); 6],
            distance: [Bucket::default(); 8],
            valid: 0,
            correct: 0,
            breaks: 0,
            initial: 0,
            post: 0,
            pending: None,
            lags: [0; 6],
            empty: 0,
            prefix: 0,
            window: 0,
            suppressed: 0,
            shadow: [ShadowBucket::default(); 3],
        }
    }
    fn observe(&mut self, e: C1ObservedByte) {
        if e.position != self.next || self.source.get(e.position).copied() != Some(e.byte) {
            self.bad = true;
            return;
        }
        self.next += 1;
        let live = e.match_length_before > 0;
        if (e.match_length_before, e.match_distance_before) != self.expected_match_pre_state {
            self.bad = true;
        }
        let valid_is_prefix =
            e.match_valid_mask == u8::MAX || e.match_valid_mask.wrapping_add(1).is_power_of_two();
        let live_match_shape = !live
            || (e.match_length_before >= MATCH_MIN_LENGTH as u32
                && (1..=MATCH_WINDOW_BYTES as u32).contains(&e.match_distance_before)
                && e.match_valid_mask != 0
                && ((e.match_valid_mask == u8::MAX
                    && e.match_correct_mask == u8::MAX
                    && !e.match_broke)
                    || (e.match_correct_mask == (e.match_valid_mask >> 1) && e.match_broke)));
        let causal_live_bounds = !live
            || (e.position > MATCH_MIN_LENGTH
                && e.position
                    .checked_sub(MATCH_MIN_LENGTH)
                    .is_some_and(|bound| {
                        usize::try_from(e.match_distance_before)
                            .is_ok_and(|distance| distance <= bound)
                    })
                && e.position.checked_sub(1).is_some_and(|bound| {
                    usize::try_from(e.match_length_before).is_ok_and(|length| length <= bound)
                }));
        let should_suppress = live && !e.match_broke;
        let no_other_disposition = !e.acquisition_initial
            && !e.acquisition_after_break
            && !e.acquisition_empty_slot
            && !e.acquisition_prefix_verification_failed
            && !e.acquisition_window_expired;
        let continued_live_disposition = if should_suppress {
            e.acquisition_live_suppressed && no_other_disposition
        } else {
            !e.acquisition_live_suppressed
        };
        let acquired = e.acquisition_initial || e.acquisition_after_break;
        let expected_after = if acquired {
            Some((MATCH_MIN_LENGTH as u32, e.match_distance_after))
        } else if live && !e.match_broke {
            e.match_length_before
                .checked_add(1)
                .map(|length| (length, e.match_distance_before))
        } else {
            Some((0, 0))
        };
        let after_state_holds = expected_after
            == Some((e.match_length_after, e.match_distance_after))
            && (!acquired || (1..=MATCH_WINDOW_BYTES as u32).contains(&e.match_distance_after));
        if e.match_correct_mask & !e.match_valid_mask != 0
            || (!live
                && (e.match_distance_before != 0
                    || e.match_valid_mask != 0
                    || e.match_correct_mask != 0))
            || (live && e.match_distance_before == 0)
            || (e.match_broke && !live)
            || !valid_is_prefix
            || !live_match_shape
            || !causal_live_bounds
            || !continued_live_disposition
            || !after_state_holds
            || (live && e.match_broke && e.acquisition_live_suppressed)
            || (e.acquisition_initial && live)
            || (e.acquisition_initial && e.acquisition_after_break)
            || (e.acquisition_initial && self.pending.is_some())
            || (e.acquisition_after_break && self.pending.is_none() && !e.match_broke)
            || !acquisition_position_bounds_hold(&e)
        {
            self.bad = true;
        }
        self.expected_match_pre_state = (e.match_length_after, e.match_distance_after);
        update_event_digest(&mut self.digest, &e);
        let loss = e.modeled_loss_q24();
        self.modeled += loss;
        self.framing += u64::from(e.continuation_loss_q24);
        let b = &mut self.classes_out[self.classes[e.position] as usize];
        b.bytes += 1;
        b.loss_q24 += loss;
        for (i, m) in self.masks.iter().enumerate() {
            if m[e.position] {
                self.overlays[i].bytes += 1;
                self.overlays[i].loss_q24 += loss
            }
        }
        let b = if live {
            &mut self.live
        } else {
            &mut self.not_live
        };
        b.bytes += 1;
        b.loss_q24 += loss;
        let b = &mut self.length[len_bucket(e.match_length_before)];
        b.bytes += 1;
        b.loss_q24 += loss;
        let b = &mut self.distance[dist_bucket(e.match_distance_before)];
        b.bytes += 1;
        b.loss_q24 += loss;
        self.valid += u64::from(e.match_valid_mask.count_ones());
        self.correct += u64::from(e.match_correct_mask.count_ones());
        if self.pending.is_some() && !e.match_broke {
            self.pending = self.pending.map(|n| n + 1)
        }
        if e.match_broke {
            self.breaks += 1;
            self.pending = Some(0)
        }
        if e.acquisition_initial {
            self.initial += 1
        }
        if e.acquisition_after_break {
            self.post += 1;
            if let Some(n) = self.pending.take() {
                self.lags[lag_bucket(n)] += 1
            } else {
                self.bad = true
            }
        }
        self.empty += u64::from(e.acquisition_empty_slot);
        self.prefix += u64::from(e.acquisition_prefix_verification_failed);
        self.window += u64::from(e.acquisition_window_expired);
        self.suppressed += u64::from(e.acquisition_live_suppressed);
        let dispositions = [
            e.acquisition_initial,
            e.acquisition_after_break,
            e.acquisition_empty_slot,
            e.acquisition_prefix_verification_failed,
            e.acquisition_window_expired,
            e.acquisition_live_suppressed,
        ]
        .into_iter()
        .filter(|value| *value)
        .count();
        let expected = usize::from(e.position + 1 >= MATCH_MIN_LENGTH);
        if dispositions != expected {
            self.bad = true;
        }
        let Some(shadow) = self.oracle.observe(self.source, e.position) else {
            self.bad = true;
            return;
        };
        for (i, (candidate, correct)) in shadow.into_iter().enumerate() {
            self.shadow[i].candidate_opportunities_upper_bound += u64::from(candidate);
            if correct {
                self.shadow[i].any_correct_bytes_upper_bound += 1;
                self.shadow[i].any_correct_loss_q24_upper_bound += loss
            }
        }
    }
}
fn sum(v: &[u64]) -> Result<u64, C1DiagnoseError> {
    v.iter()
        .try_fold(0u64, |a, b| a.checked_add(*b))
        .ok_or(C1DiagnoseError::ArithmeticOverflow)
}

fn c1_tape_wire_bytes(modeled_binary_events: u64) -> Result<u64, C1DiagnoseError> {
    let bit_payload = modeled_binary_events
        .checked_add(7)
        .ok_or(C1DiagnoseError::ArithmeticOverflow)?
        / 8;
    C1_TAPE_FIXED_WIRE_BYTES
        .checked_add(bit_payload)
        .ok_or(C1DiagnoseError::ArithmeticOverflow)
}

pub fn diagnose_c1(
    source: &[u8],
    table: &LossTable,
    item_index: u8,
    bits: u32,
) -> Result<C1ResidualReport, C1DiagnoseError> {
    let mut a = Acc::new(source);
    let shadow_bytes = a.oracle.bytes() as u64;
    let (observed, ledger, terminal) =
        encode_c1_item_with_bits_observer(source, table, item_index, bits, |e| a.observe(e))?;
    if a.bad || a.next != source.len() {
        return Err(C1DiagnoseError::ObserverEventMisattributed);
    }
    let (canonical, canonical_ledger) = encode_c1_item_with_bits(source, table, item_index, bits)?;
    if observed != canonical || ledger != canonical_ledger {
        return Err(C1DiagnoseError::ObserverDivergedFromCanonical);
    }
    update_terminal_event_digest(&mut a.digest, terminal);
    for i in 0..3 {
        let (pb, pl) = if i == 0 {
            (0, 0)
        } else {
            (
                a.shadow[i - 1].any_correct_bytes_upper_bound,
                a.shadow[i - 1].any_correct_loss_q24_upper_bound,
            )
        };
        a.shadow[i].incremental_any_correct_bytes_upper_bound = a.shadow[i]
            .any_correct_bytes_upper_bound
            .checked_sub(pb)
            .ok_or(C1DiagnoseError::ClosureDoesNotHold)?;
        a.shadow[i].incremental_any_correct_loss_q24_upper_bound = a.shadow[i]
            .any_correct_loss_q24_upper_bound
            .checked_sub(pl)
            .ok_or(C1DiagnoseError::ClosureDoesNotHold)?
    }
    let n = source.len() as u64;
    let framing = a.framing + u64::from(terminal);
    let unresolved = u64::from(a.pending.is_some());
    let acquisitions = a.initial + a.post;
    let cb = a.classes_out.map(|b| b.bytes);
    let cl = a.classes_out.map(|b| b.loss_q24);
    let lb = a.length.map(|b| b.bytes);
    let ll = a.length.map(|b| b.loss_q24);
    let db = a.distance.map(|b| b.bytes);
    let dl = a.distance.map(|b| b.loss_q24);
    let dispositions = sum(&[acquisitions, a.empty, a.prefix, a.window, a.suppressed])?;
    let evaluated = n.saturating_sub((MATCH_MIN_LENGTH - 1) as u64);
    let events = n
        .checked_mul(9)
        .and_then(|v| v.checked_add(1))
        .ok_or(C1DiagnoseError::ArithmeticOverflow)?;
    if sum(&cb)? != n
        || sum(&cl)? != a.modeled
        || a.live.bytes + a.not_live.bytes != n
        || a.live.loss_q24 + a.not_live.loss_q24 != a.modeled
        || sum(&lb)? != n
        || sum(&ll)? != a.modeled
        || sum(&db)? != n
        || sum(&dl)? != a.modeled
        || a.modeled + framing != ledger.modeled_loss_q24
        || ledger.modeled_binary_events != events
        || ledger.raw_literal_bytes != 0
        || ledger.records != source.iter().filter(|&&b| b == b'\n').count() as u64
        || dispositions != evaluated
        || a.post + unresolved != a.breaks
        || sum(&a.lags)? != a.post
    {
        return Err(C1DiagnoseError::ClosureDoesNotHold);
    }
    let tape_bytes = c1_tape_wire_bytes(events)?;
    let tape_payload_bytes = events.div_ceil(8);
    let mut state = StateAccounting {
        canonical_c1_declared_bytes: c1_declared_state_bytes(table, bits) as u64,
        c1_derived_stretch_tables_bytes: 3 * 65_536 * size_of::<i32>() as u64,
        shared_loss_table_bytes: 65_536 * size_of::<u32>() as u64,
        shadow_table_bytes: shadow_bytes,
        source_input_bytes: n,
        classification_bytes: n * (size_of::<ByteClass>() as u64),
        overlay_bit_payload_bytes: 3 * n.div_ceil(8),
        aggregation_struct_bytes: size_of::<Acc<'_>>() as u64,
        retained_observed_tape_payload_bytes: tape_payload_bytes,
        comparison_tape_payload_bytes: tape_payload_bytes,
        accounted_concurrent_logical_bytes: 0,
    };
    state.accounted_concurrent_logical_bytes = sum(&[
        state.canonical_c1_declared_bytes,
        state.c1_derived_stretch_tables_bytes,
        state.shared_loss_table_bytes,
        state.shadow_table_bytes,
        state.source_input_bytes,
        state.classification_bytes,
        state.overlay_bit_payload_bytes,
        state.aggregation_struct_bytes,
        state.retained_observed_tape_payload_bytes,
        state.comparison_tape_payload_bytes,
    ])?;
    Ok(C1ResidualReport {
        item_index,
        sse_bucket_bits: bits,
        source_bytes: n,
        tape_bytes,
        ledger,
        charged_event_digest_sha256: a
            .digest
            .finalize()
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect(),
        modeled_bits_loss_q24: a.modeled,
        framing_loss_q24_including_terminal: framing,
        terminal_loss_q24: u64::from(terminal),
        class_buckets: a.classes_out,
        overlays: a.overlays,
        live: a.live,
        not_live: a.not_live,
        valid_match_bits: a.valid,
        correct_match_bits: a.correct,
        match_breaks: a.breaks,
        initial_acquisitions: a.initial,
        post_break_reacquisitions: a.post,
        unresolved_breaks: unresolved,
        terminal_censored_lag: a.pending,
        acquisition_empty_slot: a.empty,
        acquisition_prefix_verification_failed: a.prefix,
        acquisition_window_expired: a.window,
        acquisition_live_suppressed: a.suppressed,
        length_buckets: a.length,
        distance_buckets: a.distance,
        reacquisition_lag: a.lags,
        shadow: a.shadow,
        state_accounting: state,
    })
}

fn buckets(labels: &[&str], v: &[Bucket]) -> String {
    labels
        .iter()
        .zip(v)
        .map(|(l, b)| {
            format!(
                "{{\"label\":\"{l}\",\"bytes\":{},\"loss_q24\":{}}}",
                b.bytes, b.loss_q24
            )
        })
        .collect::<Vec<_>>()
        .join(",")
}

fn render_json(
    r: &C1ResidualReport,
    version: &str,
    source_sha: &str,
    tape_sha: &str,
    classes: &[&str],
    shadow: &str,
    terminal_lag: &str,
) -> String {
    let state = &r.state_accounting;
    let primary = buckets(classes, &r.class_buckets);
    let overlays = buckets(&["digits", "timestamp", "hex_id"], &r.overlays);
    let live = buckets(&["live", "not_live"], &[r.live, r.not_live]);
    let lengths = buckets(
        &["0-5", "6-7", "8-15", "16-31", "32-63", "64+"],
        &r.length_buckets,
    );
    let distances = buckets(
        &[
            "none",
            "1-64",
            "65-256",
            "257-1024",
            "1025-4096",
            "4097-65536",
            "65537-1048576",
            "1048577+",
        ],
        &r.distance_buckets,
    );
    let lags = r
        .reacquisition_lag
        .iter()
        .map(u64::to_string)
        .collect::<Vec<_>>()
        .join(",");
    format!(
        "{{\"schema\":\"{C1_DIAGNOSIS_SCHEMA}\",\
\"kernel_version\":\"{version}\",\
\"evidence_stage\":\"mechanism_local_diagnostic\",\
\"claim_ceiling\":\"mechanism-local attribution and hindsight upper bounds only; no input-class, ratio, corpus, realizable-gain, candidate, SOTA, or product claim\",\
\"arm\":\"c1-match-mixer\",\
\"item_index\":{},\"sse_bucket_bits\":{},\"q24_scale\":{Q24_SCALE},\
\"source_bytes\":{},\"source_sha256\":\"{source_sha}\",\
\"tape_bytes\":{},\"tape_sha256\":\"{tape_sha}\",\
\"charged_event_digest_sha256\":\"{}\",\
\"identity_guard\":{{\"shared_canonical_event_generator\":true,\"canonical_tape_equal\":true,\"canonical_ledger_equal\":true}},\
\"state_accounting\":{{\
\"semantics\":\"checked peak-phase logical payload accounting; Vec capacity, allocator overhead, stack, and RSS are not claimed\",\
\"canonical_c1_declared_bytes\":{},\
\"c1_derived_stretch_tables_bytes\":{},\
\"shared_loss_table_bytes\":{},\
\"shadow_table_bytes\":{},\
\"source_input_bytes\":{},\
\"classification_bytes\":{},\
\"overlay_bit_payload_bytes\":{},\
\"aggregation_struct_bytes\":{},\
\"retained_observed_tape_payload_bytes\":{},\
\"comparison_tape_payload_bytes\":{},\
\"accounted_concurrent_logical_bytes\":{}}},\
\"ledger\":{{\"records\":{},\"modeled_binary_events\":{},\"modeled_loss_q24\":{},\"raw_literal_bytes\":{}}},\
\"loss\":{{\"modeled_bits_q24\":{},\"framing_q24_including_terminal\":{},\"terminal_q24\":{}}},\
\"primary_partition\":[{primary}],\
\"overlays\":{{\"partition\":false,\"rows\":[{overlays}],\"repeat_signal\":\"canonical live_match_partition is the bounded causal repeat signal; no separate unbounded repeat overlay is retained\"}},\
\"live_match_partition\":[{live}],\
\"match_bits\":{{\"valid\":{},\"correct\":{}}},\
\"match_lifecycle\":{{\
\"breaks\":{},\"total_acquisitions\":{},\"initial_acquisitions\":{},\
\"post_break_reacquisitions\":{},\"unresolved_breaks\":{},\
\"terminal_censored_lag\":{terminal_lag},\
\"acquisition_disposition\":{{\"empty_slot\":{},\"prefix_verification_failed\":{},\"window_expired\":{},\"live_match_suppressed\":{}}},\
\"reacquisition_lag_buckets\":[{lags}]}},\
\"match_length_buckets\":[{lengths}],\
\"match_distance_buckets\":[{distances}],\
\"shadow_oracle\":{{\
\"selection_semantics\":\"at each position, any retained verified candidate may supply the current byte; candidates may change every byte, so all fields are non-causal hindsight upper bounds prohibited as direct funding evidence\",\
\"candidate_opportunity_semantics\":\"per-position verified-candidate opportunity count, not span mass\",\
\"self_overlap\":\"legal because every candidate byte is strictly earlier than the current position\",\
\"raw_overlapping_matched_bytes_reported\":false,\
\"rows\":[{shadow}]}}}}\n",
        r.item_index,
        r.sse_bucket_bits,
        r.source_bytes,
        r.tape_bytes,
        r.charged_event_digest_sha256,
        state.canonical_c1_declared_bytes,
        state.c1_derived_stretch_tables_bytes,
        state.shared_loss_table_bytes,
        state.shadow_table_bytes,
        state.source_input_bytes,
        state.classification_bytes,
        state.overlay_bit_payload_bytes,
        state.aggregation_struct_bytes,
        state.retained_observed_tape_payload_bytes,
        state.comparison_tape_payload_bytes,
        state.accounted_concurrent_logical_bytes,
        r.ledger.records,
        r.ledger.modeled_binary_events,
        r.ledger.modeled_loss_q24,
        r.ledger.raw_literal_bytes,
        r.modeled_bits_loss_q24,
        r.framing_loss_q24_including_terminal,
        r.terminal_loss_q24,
        r.valid_match_bits,
        r.correct_match_bits,
        r.match_breaks,
        r.initial_acquisitions + r.post_break_reacquisitions,
        r.initial_acquisitions,
        r.post_break_reacquisitions,
        r.unresolved_breaks,
        r.acquisition_empty_slot,
        r.acquisition_prefix_verification_failed,
        r.acquisition_window_expired,
        r.acquisition_live_suppressed,
    )
}

impl C1ResidualReport {
    #[must_use]
    pub fn to_json(&self, version: &str, source_sha: &str, tape_sha: &str) -> String {
        let classes = [
            "structural",
            "field_name",
            "string_value",
            "number_value",
            "literal_value",
            "whitespace",
            "unclassified",
        ];
        let shadow=DEPTHS.iter().zip(self.shadow).map(|(d,r)|format!("{{\"depth\":{d},\"candidate_opportunities_upper_bound\":{},\"any_correct_bytes_upper_bound\":{},\"any_correct_loss_q24_upper_bound\":{},\"incremental_any_correct_bytes_upper_bound\":{},\"incremental_any_correct_loss_q24_upper_bound\":{}}}",r.candidate_opportunities_upper_bound,r.any_correct_bytes_upper_bound,r.any_correct_loss_q24_upper_bound,r.incremental_any_correct_bytes_upper_bound,r.incremental_any_correct_loss_q24_upper_bound)).collect::<Vec<_>>().join(",");
        let lag = self
            .terminal_censored_lag
            .map_or_else(|| "null".into(), |n| n.to_string());
        render_json(self, version, source_sha, tape_sha, &classes, &shadow, &lag)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn blank_event() -> C1ObservedByte {
        C1ObservedByte {
            position: 0,
            byte: b'a',
            continuation_loss_q24: 1,
            bit_loss_q24: [2; 8],
            match_valid_mask: 1,
            match_correct_mask: 1,
            match_length_before: 6,
            match_distance_before: 7,
            match_length_after: 7,
            match_distance_after: 7,
            match_broke: false,
            acquisition_initial: false,
            acquisition_after_break: false,
            acquisition_empty_slot: false,
            acquisition_prefix_verification_failed: false,
            acquisition_window_expired: false,
            acquisition_live_suppressed: false,
        }
    }
    fn event_hash(event: C1ObservedByte) -> Vec<u8> {
        let mut digest = Sha256::new();
        update_event_digest(&mut digest, &event);
        digest.finalize().to_vec()
    }
    fn full_event_hash(event: C1ObservedByte, terminal: u32) -> Vec<u8> {
        let mut digest = Sha256::new();
        update_event_digest(&mut digest, &event);
        update_terminal_event_digest(&mut digest, terminal);
        digest.finalize().to_vec()
    }
    #[test]
    fn closures_and_lifecycle_hold() {
        let s = b"{\"k\":\"alpha beta gamma\"}\n{\"k\":\"alpha beta gamma\"}\n";
        let r = diagnose_c1(
            s,
            &LossTable::generate(),
            3,
            crate::s0::SSE_BASE_BUCKET_BITS,
        )
        .unwrap();
        assert_eq!(
            r.modeled_bits_loss_q24 + r.framing_loss_q24_including_terminal,
            r.ledger.modeled_loss_q24
        );
        assert_eq!(
            r.post_break_reacquisitions + r.unresolved_breaks,
            r.match_breaks
        );
        assert_eq!(r.to_json("v", "s", "t"), r.to_json("v", "s", "t"));
        let state = &r.state_accounting;
        assert_eq!(state.c1_derived_stretch_tables_bytes, 3 * 65_536 * 4);
        assert_eq!(state.shared_loss_table_bytes, 65_536 * 4);
        assert_eq!(
            state.overlay_bit_payload_bytes,
            3 * (s.len() as u64).div_ceil(8)
        );
        assert_eq!(
            state.retained_observed_tape_payload_bytes,
            r.ledger.modeled_binary_events.div_ceil(8)
        );
        assert_eq!(
            state.comparison_tape_payload_bytes,
            state.retained_observed_tape_payload_bytes
        );
        assert_eq!(
            state.accounted_concurrent_logical_bytes,
            sum(&[
                state.canonical_c1_declared_bytes,
                state.c1_derived_stretch_tables_bytes,
                state.shared_loss_table_bytes,
                state.shadow_table_bytes,
                state.source_input_bytes,
                state.classification_bytes,
                state.overlay_bit_payload_bytes,
                state.aggregation_struct_bytes,
                state.retained_observed_tape_payload_bytes,
                state.comparison_tape_payload_bytes,
            ])
            .unwrap()
        );
        let json = r.to_json("v", "s", "t");
        assert!(json.contains("\"total_acquisitions\":"));
        assert!(json.contains(
            "\"candidate_opportunity_semantics\":\"per-position verified-candidate opportunity count, not span mass\""
        ));
        assert!(json.contains("Vec capacity, allocator overhead, stack, and RSS are not claimed"));
    }
    #[test]
    fn local_c1_wire_length_formula_matches_serialized_tapes() {
        let table = LossTable::generate();
        for source in [
            &b""[..],
            &b"a"[..],
            &b"aaaaaa-aaaaaaXaaaaaa\n"[..],
            &b"{\"k\":1}\n{\"k\":1}\n"[..],
        ] {
            let (tape, ledger) =
                encode_c1_item_with_bits(source, &table, 3, crate::s0::SSE_BASE_BUCKET_BITS)
                    .unwrap();
            assert_eq!(ledger.raw_literal_bytes, 0);
            assert_eq!(
                c1_tape_wire_bytes(ledger.modeled_binary_events).unwrap(),
                tape.to_bytes().len() as u64
            );
        }
    }
    #[test]
    fn swapped_event_is_refused() {
        let mut a = Acc::new(b"ab");
        a.observe(C1ObservedByte {
            position: 1,
            byte: b'a',
            continuation_loss_q24: 0,
            bit_loss_q24: [0; 8],
            match_valid_mask: 0,
            match_correct_mask: 0,
            match_length_before: 0,
            match_distance_before: 0,
            match_length_after: 0,
            match_distance_after: 0,
            match_broke: false,
            acquisition_initial: false,
            acquisition_after_break: false,
            acquisition_empty_slot: false,
            acquisition_prefix_verification_failed: false,
            acquisition_window_expired: false,
            acquisition_live_suppressed: false,
        });
        assert!(a.bad);
        assert_eq!(a.next, 0)
    }

    fn causal_non_live_event() -> C1ObservedByte {
        C1ObservedByte {
            position: 0,
            byte: b'a',
            continuation_loss_q24: 0,
            bit_loss_q24: [0; 8],
            match_valid_mask: 0,
            match_correct_mask: 0,
            match_length_before: 0,
            match_distance_before: 0,
            match_length_after: 0,
            match_distance_after: 0,
            match_broke: false,
            acquisition_initial: false,
            acquisition_after_break: false,
            acquisition_empty_slot: false,
            acquisition_prefix_verification_failed: false,
            acquisition_window_expired: false,
            acquisition_live_suppressed: false,
        }
    }

    fn semantic_mutation_is_bad(event: C1ObservedByte) -> bool {
        let mut acc = Acc::new(b"a");
        acc.observe(event);
        acc.bad
    }

    #[test]
    fn impossible_event_semantics_are_refused() {
        let base = causal_non_live_event();
        let mut variants = Vec::new();
        let mut event = base;
        event.match_correct_mask = 1;
        variants.push(event);
        let mut event = base;
        event.match_distance_before = 1;
        variants.push(event);
        let mut event = base;
        event.match_valid_mask = 1;
        variants.push(event);
        let mut event = base;
        event.match_length_before = 1;
        event.match_distance_before = 1;
        variants.push(event);
        let mut event = base;
        event.match_broke = true;
        variants.push(event);
        let mut event = base;
        event.match_length_before = MATCH_MIN_LENGTH as u32;
        event.match_distance_before = 1;
        event.match_valid_mask = 0b0000_0101;
        variants.push(event);
        let mut event = base;
        event.match_length_before = MATCH_MIN_LENGTH as u32;
        event.match_distance_before = MATCH_WINDOW_BYTES as u32 + 1;
        event.match_valid_mask = u8::MAX;
        event.match_correct_mask = u8::MAX;
        event.acquisition_live_suppressed = true;
        variants.push(event);
        let mut event = base;
        event.match_length_before = MATCH_MIN_LENGTH as u32;
        event.match_distance_before = 1;
        variants.push(event);
        let mut event = base;
        event.match_length_before = MATCH_MIN_LENGTH as u32;
        event.match_distance_before = 1;
        event.match_valid_mask = 0b0000_0111;
        event.match_correct_mask = 0;
        event.match_broke = true;
        variants.push(event);
        let mut event = base;
        event.match_length_before = MATCH_MIN_LENGTH as u32;
        event.match_distance_before = 1;
        event.match_valid_mask = 0b0000_0111;
        event.match_correct_mask = 0b0000_0011;
        event.match_broke = false;
        variants.push(event);
        let mut event = base;
        event.match_length_before = MATCH_MIN_LENGTH as u32;
        event.match_distance_before = 1;
        event.match_valid_mask = u8::MAX;
        event.match_correct_mask = u8::MAX;
        event.acquisition_empty_slot = true;
        variants.push(event);
        let mut event = base;
        event.acquisition_initial = true;
        event.acquisition_after_break = true;
        variants.push(event);
        let mut event = base;
        event.acquisition_live_suppressed = true;
        variants.push(event);
        assert!(variants.into_iter().all(semantic_mutation_is_bad));
    }

    #[test]
    fn initial_acquisition_cannot_discard_an_outstanding_break() {
        let mut acc = Acc::new(b"aa");
        acc.pending = Some(3);
        let mut event = causal_non_live_event();
        event.acquisition_initial = true;
        acc.observe(event);
        assert!(acc.bad);
    }

    fn continued_live_event(position: usize) -> C1ObservedByte {
        C1ObservedByte {
            position,
            byte: b'a',
            continuation_loss_q24: 0,
            bit_loss_q24: [0; 8],
            match_valid_mask: u8::MAX,
            match_correct_mask: u8::MAX,
            match_length_before: MATCH_MIN_LENGTH as u32,
            match_distance_before: 1,
            match_length_after: MATCH_MIN_LENGTH as u32 + 1,
            match_distance_after: 1,
            match_broke: false,
            acquisition_initial: false,
            acquisition_after_break: false,
            acquisition_empty_slot: false,
            acquisition_prefix_verification_failed: false,
            acquisition_window_expired: false,
            acquisition_live_suppressed: true,
        }
    }

    #[test]
    fn live_match_position_and_elapsed_length_bounds_are_causal() {
        for position in [MATCH_MIN_LENGTH - 1, MATCH_MIN_LENGTH] {
            let source = vec![b'a'; position + 1];
            let mut acc = Acc::new(&source);
            acc.next = position;
            acc.observe(continued_live_event(position));
            assert!(
                acc.bad,
                "position {position} admitted an impossible live match"
            );
        }
        let position = MATCH_MIN_LENGTH + 1;
        let source = vec![b'a'; position + 1];
        let mut acc = Acc::new(&source);
        acc.next = position;
        acc.expected_match_pre_state = (MATCH_MIN_LENGTH as u32, 1);
        acc.observe(continued_live_event(position));
        assert!(!acc.bad);

        let mut too_long = continued_live_event(position);
        too_long.match_length_before += 1;
        let mut acc = Acc::new(&source);
        acc.next = position;
        acc.expected_match_pre_state = (MATCH_MIN_LENGTH as u32, 1);
        acc.observe(too_long);
        assert!(acc.bad);
    }

    #[test]
    fn all_a_trace_pins_the_first_live_match_off_by_one() {
        let source = b"aaaaaaaaaaaa";
        let mut live = Vec::new();
        encode_c1_item_with_bits_observer(
            source,
            &LossTable::generate(),
            0,
            crate::s0::SSE_BASE_BUCKET_BITS,
            |event| {
                if event.match_length_before > 0 {
                    live.push(event);
                }
            },
        )
        .unwrap();
        let first = live.first().unwrap();
        assert_eq!(first.position, MATCH_MIN_LENGTH + 1);
        assert_eq!(first.match_length_before, MATCH_MIN_LENGTH as u32);
        assert_eq!(first.match_distance_before, 1);
        assert_eq!(first.match_valid_mask, u8::MAX);
        assert_eq!(first.match_correct_mask, u8::MAX);
        assert!(!first.match_broke);
        assert!(first.acquisition_live_suppressed);
    }

    #[test]
    fn acquisition_disposition_position_minima_are_pinned() {
        let mut event = causal_non_live_event();
        event.position = MATCH_MIN_LENGTH - 1;
        event.acquisition_initial = true;
        assert!(!acquisition_position_bounds_hold(&event));

        event.acquisition_initial = false;
        event.acquisition_empty_slot = true;
        assert!(acquisition_position_bounds_hold(&event));

        event.acquisition_empty_slot = false;
        event.acquisition_prefix_verification_failed = true;
        assert!(!acquisition_position_bounds_hold(&event));
        event.position = MATCH_MIN_LENGTH;
        assert!(acquisition_position_bounds_hold(&event));

        event.acquisition_prefix_verification_failed = false;
        event.acquisition_after_break = true;
        assert!(!acquisition_position_bounds_hold(&event));
        event.position = MATCH_MIN_LENGTH + 1;
        assert!(acquisition_position_bounds_hold(&event));

        event.acquisition_after_break = false;
        event.acquisition_window_expired = true;
        let first_expiry = MATCH_WINDOW_BYTES.checked_add(MATCH_MIN_LENGTH).unwrap();
        event.position = first_expiry - 1;
        assert!(!acquisition_position_bounds_hold(&event));
        event.position = first_expiry;
        assert!(acquisition_position_bounds_hold(&event));
    }

    #[test]
    fn position_five_initial_acquisition_mutation_is_refused() {
        let source = vec![b'a'; MATCH_MIN_LENGTH];
        let mut acc = Acc::new(&source);
        acc.next = MATCH_MIN_LENGTH - 1;
        let mut event = causal_non_live_event();
        event.position = MATCH_MIN_LENGTH - 1;
        event.acquisition_initial = true;
        acc.observe(event);
        assert!(acc.bad);
    }

    #[test]
    fn low_hash_width_oracle_rotation_and_depth_selection_are_pinned() {
        let prefixes: [&[u8]; 5] = [b"aaaaaa", b"bbbbbb", b"cccccc", b"dddddd", b"eeeeee"];
        assert!(prefixes.into_iter().all(|prefix| key(prefix, 0) == 0));
        let mut oracle = Oracle::new(0);
        for position in 1..=5_u32 {
            Oracle::rotate_in(&mut oracle.slots[0], position);
        }
        assert_eq!(oracle.slots[0], [5, 4, 3, 2]);

        let source = b"abcdefXabcdefYabcdefX";
        let prior = [13, 6, NO_POS, NO_POS];
        assert_eq!(Oracle::select(source, &prior, 20, 1), (true, false, 1));
        assert_eq!(Oracle::select(source, &prior, 20, 2), (true, true, 2));
        assert_eq!(Oracle::select(source, &prior, 20, 4), (true, true, 4));

        let repeated = b"aaaaaaaa";
        let mut oracle = Oracle::new(0);
        for position in 0..repeated.len() {
            let rows = oracle.observe(repeated, position).unwrap();
            if position == MATCH_MIN_LENGTH + 1 {
                assert_eq!(rows, [(false, false), (true, true), (true, true)]);
            }
        }
    }

    #[test]
    fn post_advance_state_is_the_next_event_pre_state() {
        let source = b"aaaaaaaa";
        let mut acquired = causal_non_live_event();
        acquired.position = MATCH_MIN_LENGTH;
        acquired.acquisition_initial = true;
        acquired.match_length_after = MATCH_MIN_LENGTH as u32;
        acquired.match_distance_after = 1;

        let mut acc = Acc::new(source);
        acc.next = MATCH_MIN_LENGTH;
        acc.observe(acquired);
        assert!(!acc.bad);
        acc.observe(continued_live_event(MATCH_MIN_LENGTH + 1));
        assert!(!acc.bad);

        let mut acc = Acc::new(source);
        acc.next = MATCH_MIN_LENGTH;
        acc.observe(acquired);
        let mut discontinuous = continued_live_event(MATCH_MIN_LENGTH + 1);
        discontinuous.match_length_before += 1;
        discontinuous.match_length_after += 1;
        acc.observe(discontinuous);
        assert!(acc.bad);
    }
    #[test]
    fn ordered_event_digest_binds_every_field_family() {
        let base = blank_event();
        let expected = event_hash(base);
        let mut variants = Vec::new();
        let mut e = base;
        e.position = 1;
        variants.push(e);
        let mut e = base;
        e.byte = b'b';
        variants.push(e);
        let mut e = base;
        e.continuation_loss_q24 += 1;
        variants.push(e);
        let mut e = base;
        e.bit_loss_q24[3] += 1;
        variants.push(e);
        let mut e = base;
        e.match_valid_mask ^= 2;
        variants.push(e);
        let mut e = base;
        e.match_correct_mask ^= 2;
        variants.push(e);
        let mut e = base;
        e.match_length_before += 1;
        variants.push(e);
        let mut e = base;
        e.match_distance_before += 1;
        variants.push(e);
        let mut e = base;
        e.match_length_after += 1;
        variants.push(e);
        let mut e = base;
        e.match_distance_after += 1;
        variants.push(e);
        let mut e = base;
        e.match_broke = true;
        variants.push(e);
        let mut e = base;
        e.acquisition_initial = true;
        variants.push(e);
        let mut e = base;
        e.acquisition_after_break = true;
        variants.push(e);
        let mut e = base;
        e.acquisition_empty_slot = true;
        variants.push(e);
        let mut e = base;
        e.acquisition_prefix_verification_failed = true;
        variants.push(e);
        let mut e = base;
        e.acquisition_window_expired = true;
        variants.push(e);
        let mut e = base;
        e.acquisition_live_suppressed = true;
        variants.push(e);
        for variant in variants {
            assert_ne!(event_hash(variant), expected);
        }
        assert_ne!(full_event_hash(base, 9), full_event_hash(base, 10));
        assert_ne!(full_event_hash(base, 9), event_hash(base));
    }

    #[test]
    fn synthetic_complete_event_and_report_identity_is_pinned() {
        let source = b"aaaaaa-aaaaaaXaaaaaa\n";
        let report = diagnose_c1(
            source,
            &LossTable::generate(),
            7,
            crate::s0::SSE_BASE_BUCKET_BITS,
        )
        .unwrap();
        let json = report.to_json("golden", "source", "tape");
        let report_digest: String = Sha256::digest(json.as_bytes())
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect();
        assert_eq!(
            report.charged_event_digest_sha256,
            "5b78a73f3d8eeac809ba5867a2c6f0f0d1d9f4fe67c5319d5b69fc347501833a"
        );
        assert_eq!(
            report_digest,
            "a6f3e8388f6aa37c647846bc5cb8adb8469e724ab0ad3e20ee6daced52404492"
        );
    }
    #[test]
    fn repeat_signal_has_bounded_state_on_unique_and_periodic_inputs() {
        let unique = (0..1024_u32).flat_map(u32::to_le_bytes).collect::<Vec<_>>();
        let periodic = b"abcdefgh".repeat(512);
        let table = LossTable::generate();
        let unique_report =
            diagnose_c1(&unique, &table, 0, crate::s0::SSE_BASE_BUCKET_BITS).unwrap();
        let periodic_report =
            diagnose_c1(&periodic, &table, 0, crate::s0::SSE_BASE_BUCKET_BITS).unwrap();
        assert_eq!(
            unique_report.state_accounting.shadow_table_bytes,
            periodic_report.state_accounting.shadow_table_bytes
        );
        assert_eq!(
            unique_report.state_accounting.overlay_bit_payload_bytes,
            3 * (unique.len() as u64).div_ceil(8)
        );
        let json = periodic_report.to_json("v", "s", "t");
        assert!(json.contains("canonical live_match_partition is the bounded causal repeat signal"));
        assert!(!json.contains("\"label\":\"repeat\""));
    }
    #[test]
    fn shadow_selection_work_is_bounded_on_long_period_one_input() {
        let source = vec![b'a'; 16_384];
        let prior = [6, 7, 8, 9];
        let mut inspected = 0;
        for position in 10..source.len() {
            let (opportunity, any_correct, work) = Oracle::select(&source, &prior, position, 4);
            assert!(opportunity && any_correct);
            assert_eq!(work, 4);
            inspected += work;
        }
        assert_eq!(inspected, 4 * (source.len() - 10));
    }
    #[test]
    fn no_deeper_value_means_zero_increment() {
        let s = b"abcdef-abcdef-abcdef-abcdef-";
        let r = diagnose_c1(
            s,
            &LossTable::generate(),
            0,
            crate::s0::SSE_BASE_BUCKET_BITS,
        )
        .unwrap();
        assert_eq!(r.shadow[2].incremental_any_correct_bytes_upper_bound, 0);
        assert_eq!(r.shadow[2].incremental_any_correct_loss_q24_upper_bound, 0)
    }
    #[test]
    fn mismatch_is_resolved_or_censored() {
        let s = b"abcdefghij-abcdefghij-abcdefXhij-abcdefghij-";
        let r = diagnose_c1(
            s,
            &LossTable::generate(),
            0,
            crate::s0::SSE_BASE_BUCKET_BITS,
        )
        .unwrap();
        assert!(r.match_breaks > 0);
        assert_eq!(
            r.post_break_reacquisitions + r.unresolved_breaks,
            r.match_breaks
        );
        assert_eq!(
            r.terminal_censored_lag.is_some() as u64,
            r.unresolved_breaks
        )
    }
}
