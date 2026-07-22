//! M4: bounded online token dictionary.
//!
//! M4 terminates the value-coder chain: every value it sees is coded as a
//! sequence of segments, each either a charged reference to a dictionary
//! token or an unmatched byte run coded through the unchanged M1 lane models.
//! After a value is coded, both sides teach the dictionary from its exact
//! bytes. There is no static or shipped dictionary; all state is input
//! derived and item scoped. Values consumed by an M2 or M3 hit never reach
//! M4.

use super::chassis::{
    chassis_contexts, decode_chassis_item, decode_m1_value, encode_chassis_item, encode_m1_value,
    ChassisError, ValueCoder, M1_BINARY_CONTEXTS, M1_TREE_CONTEXTS, MAX_VALUE_BYTES,
};
use super::m2::{extend_m2_tree_alphabets, M2ValueCoder, M2_BINARY_CONTEXTS, M2_TREE_CONTEXTS};
use super::m3::{extend_m3_tree_alphabets, M3_BINARY_CONTEXTS, M3_TREE_CONTEXTS};
use super::template::{fnv1a64, fnv1a64_extend};
use super::{ContextStore, EventDecoder, EventEncoder, JsonLayout, Ledger, LossTable, Tape};
use std::collections::HashMap;

pub const M4_ARM_ID: u8 = 4;

pub const M4_TOKEN_SLOTS: usize = 262_144;
pub const M4_TOKEN_BYTES_MIN: usize = 2;
pub const M4_TOKEN_BYTES_MAX: usize = 32;
pub const M4_TOKEN_ARENA_BYTES: usize = 25_165_824;
pub const M4_DECLARED_SLOT_BYTES: usize = 16;
pub const M4_DECLARED_STATE_BYTES: usize =
    M4_TOKEN_ARENA_BYTES + M4_TOKEN_SLOTS * M4_DECLARED_SLOT_BYTES;

const LANE_BUCKETS: usize = 1_024;
const TOKEN_SPLIT: u32 = 512;

// M4 contexts append strictly after the M1 prefix and the M2 and M3 blocks.
const TOKEN_HIT_BASE: usize = M1_BINARY_CONTEXTS + M2_BINARY_CONTEXTS + M3_BINARY_CONTEXTS;
const CONTINUE_BASE: usize = TOKEN_HIT_BASE + LANE_BUCKETS;
pub const M4_BINARY_CONTEXTS: usize = 2 * LANE_BUCKETS;
const TOKEN_HIGH_TREE: usize = M1_TREE_CONTEXTS + M2_TREE_CONTEXTS + M3_TREE_CONTEXTS;
const TOKEN_LOW_TREE: usize = TOKEN_HIGH_TREE + 1;
pub const M4_TREE_CONTEXTS: usize = 2;

const _: () = assert!(TOKEN_HIT_BASE == 11_744);
const _: () = assert!(CONTINUE_BASE == 12_768);
const _: () = assert!(TOKEN_HIGH_TREE == 22_534);
const _: () = assert!(TOKEN_LOW_TREE == 22_535);
const _: () = assert!(TOKEN_SPLIT as usize * TOKEN_SPLIT as usize == M4_TOKEN_SLOTS);
const _: () = assert!(TOKEN_SPLIT <= 65_536);
const _: () = assert!(M4_TOKEN_BYTES_MIN >= 2 && M4_TOKEN_BYTES_MIN <= M4_TOKEN_BYTES_MAX);
const _: () = assert!(M4_TOKEN_BYTES_MAX <= M4_TOKEN_ARENA_BYTES);
const _: () = assert!(LANE_BUCKETS.is_power_of_two());

#[derive(Clone, Debug, Default)]
struct TokenSlot {
    hash: u64,
    bytes: Option<Box<[u8]>>,
    referenced: bool,
}

/// Deterministic bounded token dictionary with the frozen CLOCK rule (the
/// hand advances only during insertion, reference bits set on decoded hits,
/// cleared while scanning, first zero-bit slot in ascending scan order from
/// the hand claimed) plus arena pressure: insertion keeps evicting further
/// victims until the resident token bytes fit the arena. The hash index is
/// acceleration only; matching always compares complete token bytes in
/// ascending slot order, and no two slots ever hold identical bytes.
struct TokenStore {
    slots: Box<[TokenSlot]>,
    index: HashMap<u64, Vec<u32>>,
    hand: usize,
    arena_bytes: usize,
    arena_limit: usize,
}

impl TokenStore {
    fn new() -> Self {
        Self::with_limits(M4_TOKEN_SLOTS, M4_TOKEN_ARENA_BYTES)
    }

    fn with_limits(slot_count: usize, arena_limit: usize) -> Self {
        Self {
            slots: (0..slot_count)
                .map(|_| TokenSlot::default())
                .collect::<Vec<_>>()
                .into_boxed_slice(),
            index: HashMap::new(),
            hand: 0,
            arena_bytes: 0,
            arena_limit,
        }
    }

    fn token_hash(bytes: &[u8]) -> u64 {
        fnv1a64_extend(fnv1a64(b"s0-m4-token"), bytes)
    }

    fn slot_holding(&self, bytes: &[u8]) -> Option<usize> {
        let hash = Self::token_hash(bytes);
        self.index.get(&hash).and_then(|candidates| {
            candidates
                .iter()
                .copied()
                .map(|slot| slot as usize)
                .find(|&slot| {
                    self.slots[slot].hash == hash
                        && self.slots[slot].bytes.as_deref() == Some(bytes)
                })
        })
    }

    /// Longest dictionary token that is an exact prefix of `bytes`, together
    /// with its slot. Sets the reference bit: this is called only for charged
    /// hits, mirrored by the decoder's `select`.
    fn lookup_longest(&mut self, bytes: &[u8]) -> Option<(usize, usize)> {
        let maximum = bytes.len().min(M4_TOKEN_BYTES_MAX);
        for length in (M4_TOKEN_BYTES_MIN..=maximum).rev() {
            if let Some(slot) = self.slot_holding(&bytes[..length]) {
                self.slots[slot].referenced = true;
                return Some((slot, length));
            }
        }
        None
    }

    /// Pure probe used by the encoder to find the end of an unmatched run.
    /// Never touches reference bits.
    fn has_match(&self, bytes: &[u8]) -> bool {
        let maximum = bytes.len().min(M4_TOKEN_BYTES_MAX);
        (M4_TOKEN_BYTES_MIN..=maximum)
            .rev()
            .any(|length| self.slot_holding(&bytes[..length]).is_some())
    }

    /// Decoder-side selection by the fully charged token identifier.
    fn select(&mut self, slot: usize) -> Result<&[u8], ChassisError> {
        let candidate = self
            .slots
            .get_mut(slot)
            .ok_or(ChassisError::TokenReference)?;
        let bytes = candidate
            .bytes
            .as_deref()
            .ok_or(ChassisError::TokenReference)?;
        candidate.referenced = true;
        Ok(bytes)
    }

    /// Teach one token. Uncharged: both sides call this with identical bytes
    /// in identical order. Out-of-bounds lengths and duplicates are ignored.
    fn insert(&mut self, bytes: &[u8]) -> Result<(), ChassisError> {
        if bytes.len() < M4_TOKEN_BYTES_MIN || bytes.len() > M4_TOKEN_BYTES_MAX {
            return Ok(());
        }
        // Unreachable with the frozen limits (32 bytes vs a 24 MiB arena) but
        // keeps shrunken test stores from scanning for impossible space.
        if bytes.len() > self.arena_limit {
            return Ok(());
        }
        if self.slot_holding(bytes).is_some() {
            return Ok(());
        }

        let target = self.next_victim(None)?;
        self.evict(target)?;
        while self
            .arena_bytes
            .checked_add(bytes.len())
            .ok_or(ChassisError::TokenReference)?
            > self.arena_limit
        {
            let extra = self.next_victim(Some(target))?;
            self.evict(extra)?;
        }

        let hash = Self::token_hash(bytes);
        self.slots[target] = TokenSlot {
            hash,
            bytes: Some(bytes.to_vec().into_boxed_slice()),
            referenced: false,
        };
        self.arena_bytes += bytes.len();
        let slot = u32::try_from(target).map_err(|_| ChassisError::TokenReference)?;
        let candidates = self.index.entry(hash).or_default();
        let position = candidates.partition_point(|&existing| existing < slot);
        candidates.insert(position, slot);
        Ok(())
    }

    fn next_victim(&mut self, excluded: Option<usize>) -> Result<usize, ChassisError> {
        for _ in 0..=self.slots.len() * 2 {
            let slot = self.hand;
            self.hand = (self.hand + 1) % self.slots.len();
            if excluded == Some(slot) {
                continue;
            }
            let candidate = &mut self.slots[slot];
            if candidate.bytes.is_none() || !candidate.referenced {
                return Ok(slot);
            }
            candidate.referenced = false;
        }
        Err(ChassisError::TokenReference)
    }

    fn evict(&mut self, slot: usize) -> Result<(), ChassisError> {
        let Some(bytes) = self.slots[slot].bytes.take() else {
            return Ok(());
        };
        self.arena_bytes = self
            .arena_bytes
            .checked_sub(bytes.len())
            .ok_or(ChassisError::TokenReference)?;
        let hash = self.slots[slot].hash;
        let candidates = self
            .index
            .get_mut(&hash)
            .ok_or(ChassisError::TokenReference)?;
        let slot = u32::try_from(slot).map_err(|_| ChassisError::TokenReference)?;
        let position = candidates
            .iter()
            .position(|&candidate| candidate == slot)
            .ok_or(ChassisError::TokenReference)?;
        candidates.remove(position);
        if candidates.is_empty() {
            self.index.remove(&hash);
        }
        Ok(())
    }
}

/// The terminal M4 layer of the value-coder chain.
pub struct M4ValueCoder {
    store: TokenStore,
}

impl Default for M4ValueCoder {
    fn default() -> Self {
        Self::new()
    }
}

impl M4ValueCoder {
    #[must_use]
    pub fn new() -> Self {
        Self {
            store: TokenStore::new(),
        }
    }

    /// Conservative logical model-state charge for the dictionary. Actual RSS
    /// is measured separately by the runner.
    #[must_use]
    pub fn declared_state_bytes(&self) -> usize {
        M4_DECLARED_STATE_BYTES
    }

    /// Frozen teaching rule: split the exact value bytes into maximal runs of
    /// ASCII alphanumerics and maximal runs of everything else, clip each run
    /// into 32-byte chunks left to right, and insert every chunk of at least
    /// two bytes.
    fn teach(&mut self, bytes: &[u8]) -> Result<(), ChassisError> {
        let mut start = 0_usize;
        while start < bytes.len() {
            let alnum = bytes[start].is_ascii_alphanumeric();
            let mut end = start + 1;
            while end < bytes.len() && bytes[end].is_ascii_alphanumeric() == alnum {
                end += 1;
            }
            let mut chunk_start = start;
            while chunk_start < end {
                let chunk_end = end.min(chunk_start + M4_TOKEN_BYTES_MAX);
                self.store.insert(&bytes[chunk_start..chunk_end])?;
                chunk_start = chunk_end;
            }
            start = end;
        }
        Ok(())
    }

    #[cfg(test)]
    fn contains_token(&self, bytes: &[u8]) -> bool {
        self.store.slot_holding(bytes).is_some()
    }

    #[cfg(test)]
    fn with_store_limits(slot_count: usize, arena_limit: usize) -> Self {
        Self {
            store: TokenStore::with_limits(slot_count, arena_limit),
        }
    }
}

impl ValueCoder for M4ValueCoder {
    fn encode_value(
        &mut self,
        events: &mut EventEncoder<'_>,
        _slot: usize,
        _lane_index: usize,
        lane_key: u64,
        bytes: &[u8],
    ) -> Result<(), ChassisError> {
        debug_assert!(!bytes.is_empty(), "JSON values are never empty");
        let bucket = bucket(lane_key);
        let mut cursor = 0_usize;
        loop {
            if let Some((token_slot, length)) = self.store.lookup_longest(&bytes[cursor..]) {
                events.bit(TOKEN_HIT_BASE + bucket, true)?;
                let slot = u32::try_from(token_slot).map_err(|_| ChassisError::TokenReference)?;
                events.symbol(TOKEN_HIGH_TREE, slot / TOKEN_SPLIT)?;
                events.symbol(TOKEN_LOW_TREE, slot % TOKEN_SPLIT)?;
                cursor += length;
            } else {
                events.bit(TOKEN_HIT_BASE + bucket, false)?;
                let start = cursor;
                cursor += 1;
                while cursor < bytes.len() && !self.store.has_match(&bytes[cursor..]) {
                    cursor += 1;
                }
                encode_m1_value(events, lane_key, &bytes[start..cursor])?;
            }
            let more = cursor < bytes.len();
            events.bit(CONTINUE_BASE + bucket, more)?;
            if !more {
                break;
            }
        }
        self.teach(bytes)
    }

    fn decode_value(
        &mut self,
        events: &mut EventDecoder<'_>,
        _slot: usize,
        _lane_index: usize,
        lane_key: u64,
    ) -> Result<Vec<u8>, ChassisError> {
        let bucket = bucket(lane_key);
        let mut value = Vec::new();
        loop {
            if events.bit(TOKEN_HIT_BASE + bucket)? {
                let high = events.symbol(TOKEN_HIGH_TREE)?;
                let low = events.symbol(TOKEN_LOW_TREE)?;
                let token_slot = high as usize * TOKEN_SPLIT as usize + low as usize;
                let bytes = self.store.select(token_slot)?;
                value.extend_from_slice(bytes);
            } else {
                let segment = decode_m1_value(events, lane_key)?;
                value.extend_from_slice(&segment);
            }
            if value.len() > MAX_VALUE_BYTES {
                return Err(ChassisError::TokenReference);
            }
            if !events.bit(CONTINUE_BASE + bucket)? {
                break;
            }
        }
        self.teach(&value)?;
        Ok(value)
    }

    /// Seed the dictionary from the taught record's parsed values, uncharged
    /// and identical on both sides.
    fn after_miss_insert(&mut self, _slot: usize, layout: &JsonLayout) -> Result<(), ChassisError> {
        for value in layout.values() {
            self.teach(value)?;
        }
        Ok(())
    }

    fn on_slots_cleared(&mut self, _cleared_slots: &[usize]) -> Result<(), ChassisError> {
        // The token dictionary is item-scoped, not template-slot-scoped.
        Ok(())
    }
}

fn bucket(lane_key: u64) -> usize {
    lane_key as usize & (LANE_BUCKETS - 1)
}

/// The m1-m2-m4 arm's chain: M2 decides first, escapes and ineligible values
/// proceed directly to the terminal M4 coder.
fn m4_chain() -> M2ValueCoder<M4ValueCoder> {
    M2ValueCoder::with_inner(M4ValueCoder::new())
}

/// Context space for arms that include M4: the frozen M1 prefix, then the
/// M2, M3, and M4 blocks in canonical order. The M3 block is allocated even
/// when M3 is not part of the arm, so every absolute context index is
/// arm-invariant; unused contexts never charge events.
pub fn m4_contexts() -> Result<ContextStore, ChassisError> {
    let mut alphabets = Vec::with_capacity(M2_TREE_CONTEXTS + M3_TREE_CONTEXTS + M4_TREE_CONTEXTS);
    extend_m2_tree_alphabets(&mut alphabets);
    extend_m3_tree_alphabets(&mut alphabets);
    alphabets.push(TOKEN_SPLIT);
    alphabets.push(TOKEN_SPLIT);
    chassis_contexts(
        M2_BINARY_CONTEXTS + M3_BINARY_CONTEXTS + M4_BINARY_CONTEXTS,
        &alphabets,
    )
}

pub fn encode_m1_m2_m4_item(
    source: &[u8],
    table: &LossTable,
    item_index: u8,
) -> Result<(Tape, Ledger), ChassisError> {
    encode_chassis_item(
        source,
        table,
        m4_contexts()?,
        M4_ARM_ID,
        item_index,
        &mut m4_chain(),
    )
}

pub fn decode_m1_m2_m4_item(
    tape: &Tape,
    expected_ledger: Ledger,
    table: &LossTable,
    expected_item_index: u8,
) -> Result<Vec<u8>, ChassisError> {
    decode_chassis_item(
        tape,
        expected_ledger,
        table,
        m4_contexts()?,
        M4_ARM_ID,
        expected_item_index,
        &mut m4_chain(),
    )
}

#[cfg(test)]
mod tests {
    use super::super::chassis::{encode_m1_value, lane_key};
    use super::super::m2::encode_m1_m2_item;
    use super::super::m3::M3ValueCoder;
    use super::*;

    fn round_trip(source: &[u8], item_index: u8) -> Ledger {
        let table = LossTable::generate();
        let (tape, ledger) = encode_m1_m2_m4_item(source, &table, item_index).unwrap();
        assert_eq!(
            decode_m1_m2_m4_item(&tape, ledger, &table, item_index).unwrap(),
            source
        );
        let (repeat_tape, repeat_ledger) =
            encode_m1_m2_m4_item(source, &table, item_index).unwrap();
        assert_eq!(repeat_tape.to_bytes(), tape.to_bytes());
        assert_eq!(repeat_ledger, ledger);
        ledger
    }

    #[test]
    fn repeated_tokens_round_trip_and_beat_the_m2_arm() {
        let table = LossTable::generate();
        let mut source = Vec::new();
        for index in 0..10 {
            source.extend_from_slice(
                format!(
                    "{{\"path\":\"/api/customers/{index}/orders/pending\",\"n\":\"x{index}\"}}\n"
                )
                .as_bytes(),
            );
        }
        source.extend_from_slice(
            b"\n{bad}\n{\"path\":\"/api/customers/9/orders/pending\",\"n\":\"tail\"}",
        );
        let m4_ledger = round_trip(&source, 0);
        let (_, m2_ledger) = encode_m1_m2_item(&source, &table, 0).unwrap();
        assert!(
            m4_ledger.modeled_binary_events < m2_ledger.modeled_binary_events,
            "m4 {} !< m2 {}",
            m4_ledger.modeled_binary_events,
            m2_ledger.modeled_binary_events
        );
    }

    #[test]
    fn matchless_values_cost_exactly_two_extra_bits_each() {
        let table = LossTable::generate();
        // Byte values below never form alphanumeric runs of length >= 2, so
        // the dictionary stays empty of anything matchable and every value is
        // a single unmatched segment: one hit bit plus one continue bit over
        // the plain M1 cost.
        let source = b"{\"a\":\"#!\",\"b\":\"()\"}\n{\"a\":\"[]\",\"b\":\"{}\"}\n{\"a\":\"<>\",\"b\":\"%^\"}\n";
        let (_, m2_ledger) = encode_m1_m2_item(source, &table, 1).unwrap();
        let m4_ledger = round_trip(source, 1);
        assert_eq!(
            m4_ledger.modeled_binary_events,
            m2_ledger.modeled_binary_events + 4 * 2
        );
    }

    #[test]
    fn token_hit_charges_one_bit_plus_the_split_identifier() {
        let table = LossTable::generate();
        let layout = JsonLayout::parse(b"{\"s\":\"sessiontoken\"}").unwrap();
        let key = lane_key(layout.skeleton(), 0).unwrap();
        let mut coder = M4ValueCoder::new();
        coder.after_miss_insert(0, &layout).unwrap();
        assert!(coder.contains_token(b"sessiontoken"));

        // The value is quote + token + quote: a one-byte miss segment, a
        // token hit, and another one-byte miss segment, each with its
        // continue bit. Hit cost is 1 + 9 + 9 = 19 events.
        let mut events = EventEncoder::new(&table, m4_contexts().unwrap(), M4_ARM_ID, 0);
        let mut plain = EventEncoder::new(&table, m4_contexts().unwrap(), M4_ARM_ID, 0);
        encode_m1_value(&mut plain, key, b"\"").unwrap();
        encode_m1_value(&mut plain, key, b"\"").unwrap();
        let quotes = plain.ledger().modeled_binary_events;
        coder
            .encode_value(&mut events, 0, 0, key, b"\"sessiontoken\"")
            .unwrap();
        assert_eq!(events.ledger().modeled_binary_events, quotes + 2 + 19 + 3);
    }

    #[test]
    fn longest_match_wins_over_shorter_tokens() {
        let mut store = TokenStore::new();
        store.insert(b"abc").unwrap();
        store.insert(b"abcdef").unwrap();
        let (slot, length) = store.lookup_longest(b"abcdefxyz").unwrap();
        assert_eq!(length, 6);
        assert_eq!(
            store.slots[slot].bytes.as_deref(),
            Some(b"abcdef".as_slice())
        );
        let (_, shorter) = store.lookup_longest(b"abcdxyz").unwrap();
        assert_eq!(shorter, 3);
    }

    #[test]
    fn teaching_splits_alnum_runs_and_clips_to_32_bytes() {
        let mut coder = M4ValueCoder::new();
        let long_run: String = "a".repeat(33);
        let value = format!("\"{long_run}--tail7\"");
        coder.teach(value.as_bytes()).unwrap();
        assert!(coder.contains_token("a".repeat(32).as_bytes()));
        assert!(!coder.contains_token("a".repeat(33).as_bytes()));
        assert!(!coder.contains_token(b"a")); // one-byte leftover chunk dropped
        assert!(coder.contains_token(b"--"));
        assert!(coder.contains_token(b"tail7"));
        assert!(!coder.contains_token(b"\"")); // single quote too short
    }

    #[test]
    fn arena_pressure_evicts_deterministically() {
        let mut store = TokenStore::with_limits(4, 8);
        store.insert(b"aaa").unwrap();
        store.insert(b"bbb").unwrap();
        store.insert(b"cc").unwrap();
        assert_eq!(store.arena_bytes, 8);
        // Inserting four more bytes exceeds the arena: the empty target slot
        // is claimed, then victims evict in scan order until it fits.
        store.insert(b"dddd").unwrap();
        assert!(store.slot_holding(b"aaa").is_none());
        assert!(store.slot_holding(b"bbb").is_none());
        assert!(store.slot_holding(b"cc").is_some());
        assert!(store.slot_holding(b"dddd").is_some());
        assert_eq!(store.arena_bytes, 6);
    }

    #[test]
    fn clock_reference_bits_protect_hit_tokens() {
        let mut store = TokenStore::with_limits(3, 1_024);
        store.insert(b"one1").unwrap();
        store.insert(b"two2").unwrap();
        store.insert(b"three3").unwrap();
        assert!(store.lookup_longest(b"one1...").is_some());
        store.insert(b"four4").unwrap();
        assert!(store.slot_holding(b"one1").is_some());
        assert!(store.slot_holding(b"two2").is_none());
        assert!(store.slot_holding(b"four4").is_some());
    }

    #[test]
    fn values_consumed_by_m2_or_m3_hits_never_reach_m4() {
        let table = LossTable::generate();
        let layout = JsonLayout::parse(b"{\"id\":4000}").unwrap();
        let key = lane_key(layout.skeleton(), 0).unwrap();

        // M2 hit: the delta-coded value must not be taught to M4.
        let mut chain = m4_chain();
        chain.after_miss_insert(0, &layout).unwrap();
        let mut events = EventEncoder::new(&table, m4_contexts().unwrap(), M4_ARM_ID, 0);
        chain.encode_value(&mut events, 0, 0, key, b"4001").unwrap();
        assert!(!chain.inner_mut().contains_token(b"4001"));

        // M3 hit: the referenced value must not be taught to M4 either.
        let string_layout = JsonLayout::parse(b"{\"s\":\"held-by-m3\"}").unwrap();
        let string_key = lane_key(string_layout.skeleton(), 0).unwrap();
        let mut full = M3ValueCoder::with_inner(M4ValueCoder::new());
        // Seeding teaches both stores; wipe M4's dictionary to isolate the
        // hit path, then reference the session-cached value.
        full.after_miss_insert(0, &string_layout).unwrap();
        let mut isolated = M3ValueCoder::with_inner(M4ValueCoder::new());
        let mut m3_events = EventEncoder::new(&table, m4_contexts().unwrap(), M4_ARM_ID, 0);
        isolated.after_miss_insert(0, &string_layout).unwrap();
        let before = m3_events.ledger().modeled_binary_events;
        isolated
            .encode_value(&mut m3_events, 0, 0, string_key, b"\"held-by-m3\"")
            .unwrap();
        // A session hit costs exactly 17 events, proving M4 was never entered.
        assert_eq!(m3_events.ledger().modeled_binary_events - before, 17);
    }

    #[test]
    fn decoder_rejects_references_to_unoccupied_token_slots() {
        let table = LossTable::generate();
        let layout = JsonLayout::parse(b"{\"s\":\"abcd\"}").unwrap();
        let key = lane_key(layout.skeleton(), 0).unwrap();
        let mut events = EventEncoder::new(&table, m4_contexts().unwrap(), M4_ARM_ID, 0);
        events.bit(TOKEN_HIT_BASE + bucket(key), true).unwrap();
        events.symbol(TOKEN_HIGH_TREE, 3).unwrap();
        events.symbol(TOKEN_LOW_TREE, 7).unwrap();
        let (tape, _) = events.finish();

        let mut coder = M4ValueCoder::new();
        let mut decoder = EventDecoder::new(&table, m4_contexts().unwrap(), &tape);
        assert_eq!(
            coder.decode_value(&mut decoder, 0, 0, key),
            Err(ChassisError::TokenReference)
        );
    }

    #[test]
    fn hostile_endless_values_fail_closed_at_the_value_bound() {
        let table = LossTable::generate();
        let layout = JsonLayout::parse(b"{\"s\":\"abcd\"}").unwrap();
        let key = lane_key(layout.skeleton(), 0).unwrap();
        // Teach a 32-byte token, then hand-write a tape that references it
        // in an unbounded loop; the decoder must stop at the value ceiling.
        let token = [b'q'; 32];
        let mut encoder_coder = M4ValueCoder::new();
        encoder_coder.store.insert(&token).unwrap();
        let mut events = EventEncoder::new(&table, m4_contexts().unwrap(), M4_ARM_ID, 0);
        let repeats = MAX_VALUE_BYTES / token.len() + 2;
        for _ in 0..repeats {
            events.bit(TOKEN_HIT_BASE + bucket(key), true).unwrap();
            events.symbol(TOKEN_HIGH_TREE, 0).unwrap();
            events.symbol(TOKEN_LOW_TREE, 0).unwrap();
            events.bit(CONTINUE_BASE + bucket(key), true).unwrap();
        }
        let (tape, _) = events.finish();

        let mut coder = M4ValueCoder::new();
        coder.store.insert(&token).unwrap();
        let mut decoder = EventDecoder::new(&table, m4_contexts().unwrap(), &tape);
        assert_eq!(
            coder.decode_value(&mut decoder, 0, 0, key),
            Err(ChassisError::TokenReference)
        );
    }

    #[test]
    fn mixed_segments_reconstruct_exactly() {
        // Values interleaving unmatched prefixes, token hits, and unmatched
        // suffixes across repeated records.
        let mut source = Vec::new();
        for index in 0..6 {
            source.extend_from_slice(
                format!("{{\"m\":\"pre#{index} usertoken77 :post\"}}\n").as_bytes(),
            );
        }
        round_trip(&source, 2);
    }

    #[test]
    fn arm_and_item_identity_are_bound() {
        let table = LossTable::generate();
        let source = b"{\"a\":\"x\"}\n";
        let (tape, ledger) = encode_m1_m2_m4_item(source, &table, 3).unwrap();
        assert_eq!(
            decode_m1_m2_m4_item(&tape, ledger, &table, 4),
            Err(ChassisError::TapeIdentityMismatch)
        );
        let (m2_tape, m2_ledger) = encode_m1_m2_item(source, &table, 3).unwrap();
        assert_eq!(
            decode_m1_m2_m4_item(&m2_tape, m2_ledger, &table, 3),
            Err(ChassisError::TapeIdentityMismatch)
        );
    }

    #[test]
    fn full_chain_round_trip_survives_slot_and_arena_eviction() {
        // A shrunken dictionary forces both CLOCK slot reuse and
        // arena-pressure eviction through the real chassis entry points on
        // both sides; the byte stream must stay lossless and deterministic.
        use super::super::chassis::{decode_chassis_item, encode_chassis_item};
        let table = LossTable::generate();
        let mut source = Vec::new();
        for index in 0..120_u32 {
            source.extend_from_slice(
                format!(
                    "{{\"w\":\"word{:02}\",\"again\":\"word{:02}\"}}\n",
                    index % 40,
                    (index + 1) % 40
                )
                .as_bytes(),
            );
        }
        let encode = || {
            encode_chassis_item(
                &source,
                &table,
                m4_contexts().unwrap(),
                M4_ARM_ID,
                6,
                &mut M2ValueCoder::with_inner(M4ValueCoder::with_store_limits(8, 48)),
            )
            .unwrap()
        };
        let (tape, ledger) = encode();
        let decoded = decode_chassis_item(
            &tape,
            ledger,
            &table,
            m4_contexts().unwrap(),
            M4_ARM_ID,
            6,
            &mut M2ValueCoder::with_inner(M4ValueCoder::with_store_limits(8, 48)),
        )
        .unwrap();
        assert_eq!(decoded, source);
        let (repeat_tape, repeat_ledger) = encode();
        assert_eq!(repeat_tape.to_bytes(), tape.to_bytes());
        assert_eq!(repeat_ledger, ledger);
    }

    #[test]
    fn declared_state_is_fixed_and_arena_is_bounded() {
        let mut coder = M4ValueCoder::new();
        assert_eq!(coder.declared_state_bytes(), M4_DECLARED_STATE_BYTES);
        for index in 0..100_000_u32 {
            coder
                .store
                .insert(format!("token{index:06}").as_bytes())
                .unwrap();
        }
        assert_eq!(coder.store.slots.len(), M4_TOKEN_SLOTS);
        assert!(coder.store.arena_bytes <= M4_TOKEN_ARENA_BYTES);
        assert_eq!(coder.declared_state_bytes(), M4_DECLARED_STATE_BYTES);
    }
}
