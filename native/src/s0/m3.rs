//! M3: bounded session-reference cache.
//!
//! M3 sees every value that M2 escaped or found ineligible, before that value
//! reaches the inner coder. It charges one hit bit per visible value; a hit
//! charges a reference identifier and reproduces the cached slot's exact
//! bytes, while a miss delegates to the inner coder and then teaches the
//! decoded value into the cache without further events. Values consumed by an
//! M2 hit never touch M3 state.

use super::chassis::{
    chassis_contexts, decode_chassis_item, encode_chassis_item, ChassisError, M1ValueCoder,
    ValueCoder, M1_BINARY_CONTEXTS, M1_TREE_CONTEXTS,
};
use super::m2::{extend_m2_tree_alphabets, M2ValueCoder, M2_BINARY_CONTEXTS, M2_TREE_CONTEXTS};
use super::template::{fnv1a64, fnv1a64_extend};
use super::{ContextStore, EventDecoder, EventEncoder, JsonLayout, Ledger, LossTable, Tape};
use std::collections::HashMap;

pub const M3_ARM_ID: u8 = 3;

pub const M3_SESSION_SLOTS: usize = 65_536;
pub const M3_SLOT_VALUE_BYTES: usize = 128;
pub const M3_DECLARED_SLOT_BYTES: usize = M3_SLOT_VALUE_BYTES + 16;
pub const M3_DECLARED_STATE_BYTES: usize = M3_SESSION_SLOTS * M3_DECLARED_SLOT_BYTES;

const LANE_BUCKETS: usize = 1_024;
const REFERENCE_ALPHABET: u32 = 65_536;

// M3 contexts append strictly after the frozen M1 prefix and M2 block.
const M3_HIT_BASE: usize = M1_BINARY_CONTEXTS + M2_BINARY_CONTEXTS;
const REFERENCE_TREE: usize = M1_TREE_CONTEXTS + M2_TREE_CONTEXTS;
pub const M3_BINARY_CONTEXTS: usize = LANE_BUCKETS;
pub const M3_TREE_CONTEXTS: usize = 1;

const _: () = assert!(M3_HIT_BASE == 10_720);
const _: () = assert!(REFERENCE_TREE == 22_533);
const _: () = assert!(REFERENCE_ALPHABET as usize == M3_SESSION_SLOTS);
// The event layer's maximum tree alphabet is 65,536; a larger slot count
// would only fail at runtime in BitTree::new, so pin the ceiling here.
const _: () = assert!(M3_SESSION_SLOTS <= 65_536);
const _: () = assert!(LANE_BUCKETS.is_power_of_two());

#[derive(Clone, Debug, Default)]
struct SessionSlot {
    hash: u64,
    bytes: Option<Box<[u8]>>,
    referenced: bool,
}

/// Deterministic bounded value cache with the frozen CLOCK rule: the hand
/// advances only during insertion, reference bits are set on decoded hits,
/// cleared while scanning, and the first zero-bit slot in ascending scan
/// order from the hand is claimed — the same hand-relative reading the
/// merged TemplateStore uses, pinned by the eviction tests. Hashes only
/// reject non-candidates; hit selection always compares complete value
/// bytes, in ascending slot order.
struct SessionStore {
    slots: Box<[SessionSlot]>,
    // Acceleration index only: maps a value hash to its candidate slots in
    // ascending order. Semantics are defined purely by the slots array.
    index: HashMap<u64, Vec<u16>>,
    hand: usize,
}

impl SessionStore {
    fn new() -> Self {
        Self {
            slots: (0..M3_SESSION_SLOTS)
                .map(|_| SessionSlot::default())
                .collect::<Vec<_>>()
                .into_boxed_slice(),
            index: HashMap::new(),
            hand: 0,
        }
    }

    /// First slot holding exactly `bytes`, by ascending slot index. Sets the
    /// reference bit: lookups happen only on charged hits, on both sides.
    fn lookup(&mut self, bytes: &[u8]) -> Option<usize> {
        let hash = fnv1a64_extend(fnv1a64(b"s0-m3-session"), bytes);
        let candidates = self.index.get(&hash)?;
        let slot = candidates.iter().copied().map(usize::from).find(|&slot| {
            self.slots[slot].hash == hash && self.slots[slot].bytes.as_deref() == Some(bytes)
        })?;
        self.slots[slot].referenced = true;
        Some(slot)
    }

    /// Decoder-side selection by the fully charged reference identifier.
    fn select(&mut self, slot: usize) -> Result<&[u8], ChassisError> {
        let candidate = self
            .slots
            .get_mut(slot)
            .ok_or(ChassisError::SessionReference)?;
        let bytes = candidate
            .bytes
            .as_deref()
            .ok_or(ChassisError::SessionReference)?;
        candidate.referenced = true;
        Ok(bytes)
    }

    /// Teach a missed value. Uncharged: both sides call this with identical
    /// bytes after the value was fully coded by the inner mechanisms. Values
    /// outside 1..=128 bytes or already present are ignored.
    fn insert(&mut self, bytes: &[u8]) -> Result<(), ChassisError> {
        if bytes.is_empty() || bytes.len() > M3_SLOT_VALUE_BYTES {
            return Ok(());
        }
        let hash = fnv1a64_extend(fnv1a64(b"s0-m3-session"), bytes);
        if self.index.get(&hash).is_some_and(|candidates| {
            candidates
                .iter()
                .any(|&slot| self.slots[usize::from(slot)].bytes.as_deref() == Some(bytes))
        }) {
            return Ok(());
        }

        let target = self.next_victim()?;
        self.evict(target)?;
        self.slots[target] = SessionSlot {
            hash,
            bytes: Some(bytes.to_vec().into_boxed_slice()),
            referenced: false,
        };
        let slot = u16::try_from(target).map_err(|_| ChassisError::SessionReference)?;
        let candidates = self.index.entry(hash).or_default();
        let position = candidates.partition_point(|&existing| existing < slot);
        candidates.insert(position, slot);
        Ok(())
    }

    fn next_victim(&mut self) -> Result<usize, ChassisError> {
        for _ in 0..=self.slots.len() * 2 {
            let slot = self.hand;
            self.hand = (self.hand + 1) % self.slots.len();
            let candidate = &mut self.slots[slot];
            if candidate.bytes.is_none() || !candidate.referenced {
                return Ok(slot);
            }
            candidate.referenced = false;
        }
        Err(ChassisError::SessionReference)
    }

    fn evict(&mut self, slot: usize) -> Result<(), ChassisError> {
        let Some(bytes) = self.slots[slot].bytes.take() else {
            return Ok(());
        };
        let hash = self.slots[slot].hash;
        let candidates = self
            .index
            .get_mut(&hash)
            .ok_or(ChassisError::SessionReference)?;
        let slot = u16::try_from(slot).map_err(|_| ChassisError::SessionReference)?;
        let position = candidates
            .iter()
            .position(|&candidate| candidate == slot)
            .ok_or(ChassisError::SessionReference)?;
        candidates.remove(position);
        if candidates.is_empty() {
            self.index.remove(&hash);
        }
        drop(bytes);
        Ok(())
    }
}

/// The M3 layer of the value-coder chain.
pub struct M3ValueCoder<Inner: ValueCoder> {
    store: SessionStore,
    inner: Inner,
}

impl<Inner: ValueCoder> M3ValueCoder<Inner> {
    #[must_use]
    pub fn with_inner(inner: Inner) -> Self {
        Self {
            store: SessionStore::new(),
            inner,
        }
    }

    /// Conservative logical model-state charge for the session cache. Actual
    /// RSS is measured separately by the runner.
    #[must_use]
    pub fn declared_state_bytes(&self) -> usize {
        M3_DECLARED_STATE_BYTES
    }

    #[cfg(test)]
    fn contains(&self, bytes: &[u8]) -> bool {
        let hash = fnv1a64_extend(fnv1a64(b"s0-m3-session"), bytes);
        self.store.index.get(&hash).is_some_and(|candidates| {
            candidates
                .iter()
                .any(|&slot| self.store.slots[usize::from(slot)].bytes.as_deref() == Some(bytes))
        })
    }
}

impl<Inner: ValueCoder> ValueCoder for M3ValueCoder<Inner> {
    fn encode_value(
        &mut self,
        events: &mut EventEncoder<'_>,
        slot: usize,
        lane_index: usize,
        lane_key: u64,
        bytes: &[u8],
    ) -> Result<(), ChassisError> {
        let bucket = bucket(lane_key);
        if let Some(reference) = self.store.lookup(bytes) {
            events.bit(M3_HIT_BASE + bucket, true)?;
            let symbol = u32::try_from(reference).map_err(|_| ChassisError::SessionReference)?;
            events.symbol(REFERENCE_TREE, symbol)?;
            Ok(())
        } else {
            events.bit(M3_HIT_BASE + bucket, false)?;
            self.inner
                .encode_value(events, slot, lane_index, lane_key, bytes)?;
            self.store.insert(bytes)
        }
    }

    fn decode_value(
        &mut self,
        events: &mut EventDecoder<'_>,
        slot: usize,
        lane_index: usize,
        lane_key: u64,
    ) -> Result<Vec<u8>, ChassisError> {
        let bucket = bucket(lane_key);
        if events.bit(M3_HIT_BASE + bucket)? {
            let reference = events.symbol(REFERENCE_TREE)? as usize;
            Ok(self.store.select(reference)?.to_vec())
        } else {
            let bytes = self
                .inner
                .decode_value(events, slot, lane_index, lane_key)?;
            self.store.insert(&bytes)?;
            Ok(bytes)
        }
    }

    /// Seed the cache from the taught record's parsed values, uncharged and
    /// identical on both sides. Every top-level value is eligible regardless
    /// of lane index.
    fn after_miss_insert(&mut self, slot: usize, layout: &JsonLayout) -> Result<(), ChassisError> {
        for value in layout.values() {
            self.store.insert(value)?;
        }
        self.inner.after_miss_insert(slot, layout)
    }

    fn on_slots_cleared(&mut self, cleared_slots: &[usize]) -> Result<(), ChassisError> {
        // The session cache is item-scoped, not template-slot-scoped.
        self.inner.on_slots_cleared(cleared_slots)
    }
}

fn bucket(lane_key: u64) -> usize {
    lane_key as usize & (LANE_BUCKETS - 1)
}

/// The m1-m2-m3 arm's value-coder chain: M2 decides first, escapes and
/// ineligible values proceed to M3, then to M1 bytes.
type M3Chain = M2ValueCoder<M3ValueCoder<M1ValueCoder>>;

fn m3_chain() -> M3Chain {
    M2ValueCoder::with_inner(M3ValueCoder::with_inner(M1ValueCoder))
}

/// Context space for the m1-m2-m3 arm: the frozen M1 prefix, then the M2
/// block, then the M3 block. Absolute indices for every block are identical
/// across all arms that include it.
pub fn m3_contexts() -> Result<ContextStore, ChassisError> {
    let mut alphabets = Vec::with_capacity(M2_TREE_CONTEXTS + M3_TREE_CONTEXTS);
    extend_m2_tree_alphabets(&mut alphabets);
    alphabets.push(REFERENCE_ALPHABET);
    chassis_contexts(M2_BINARY_CONTEXTS + M3_BINARY_CONTEXTS, &alphabets)
}

pub fn encode_m1_m2_m3_item(
    source: &[u8],
    table: &LossTable,
    item_index: u8,
) -> Result<(Tape, Ledger), ChassisError> {
    encode_chassis_item(
        source,
        table,
        m3_contexts()?,
        M3_ARM_ID,
        item_index,
        &mut m3_chain(),
    )
}

pub fn decode_m1_m2_m3_item(
    tape: &Tape,
    expected_ledger: Ledger,
    table: &LossTable,
    expected_item_index: u8,
) -> Result<Vec<u8>, ChassisError> {
    decode_chassis_item(
        tape,
        expected_ledger,
        table,
        m3_contexts()?,
        M3_ARM_ID,
        expected_item_index,
        &mut m3_chain(),
    )
}

#[cfg(test)]
mod tests {
    use super::super::chassis::{encode_m1_value, lane_key};
    use super::super::m2::encode_m1_m2_item;
    use super::*;

    fn round_trip(source: &[u8], item_index: u8) -> Ledger {
        let table = LossTable::generate();
        let (tape, ledger) = encode_m1_m2_m3_item(source, &table, item_index).unwrap();
        assert_eq!(
            decode_m1_m2_m3_item(&tape, ledger, &table, item_index).unwrap(),
            source
        );
        let (repeat_tape, repeat_ledger) =
            encode_m1_m2_m3_item(source, &table, item_index).unwrap();
        assert_eq!(repeat_tape.to_bytes(), tape.to_bytes());
        assert_eq!(repeat_ledger, ledger);
        ledger
    }

    #[test]
    fn repeated_session_values_round_trip_across_templates() {
        let mut source = Vec::new();
        for index in 0..6 {
            source.extend_from_slice(
                format!(
                    "{{\"sid\":\"9f8e7d6c-{index}\",\"msg\":\"m{index}\"}}\n{{\"user\":\"tom\",\"sid\":\"9f8e7d6c-{}\"}}\n",
                    index / 2
                )
                .as_bytes(),
            );
        }
        source.extend_from_slice(b"\n{bad}\n{\"sid\":\"9f8e7d6c-0\",\"msg\":\"tail\"}");
        round_trip(&source, 0);
    }

    #[test]
    fn session_hits_reduce_events_versus_the_m2_arm() {
        let table = LossTable::generate();
        let mut source = Vec::new();
        for index in 0..8 {
            source.extend_from_slice(
                format!(
                    "{{\"sid\":\"session-abcdef-{}\",\"n\":\"x{index}\"}}\n",
                    index % 2
                )
                .as_bytes(),
            );
        }
        let m3_ledger = round_trip(&source, 1);
        let (_, m2_ledger) = encode_m1_m2_item(&source, &table, 1).unwrap();
        assert!(
            m3_ledger.modeled_binary_events < m2_ledger.modeled_binary_events,
            "m3 {} !< m2 {}",
            m3_ledger.modeled_binary_events,
            m2_ledger.modeled_binary_events
        );
    }

    #[test]
    fn unrepeated_values_cost_exactly_one_extra_bit_each() {
        let table = LossTable::generate();
        // One miss teaches; two hit records carry two unique string values
        // each, so exactly four values reach M3 and miss.
        let source = b"{\"a\":\"q0\",\"b\":\"r0\"}\n{\"a\":\"q1\",\"b\":\"r1\"}\n{\"a\":\"q2\",\"b\":\"r2\"}\n";
        let (_, m2_ledger) = encode_m1_m2_item(source, &table, 2).unwrap();
        let m3_ledger = round_trip(source, 2);
        assert_eq!(
            m3_ledger.modeled_binary_events,
            m2_ledger.modeled_binary_events + 4
        );
    }

    #[test]
    fn m3_hit_charges_one_bit_plus_the_reference_identifier() {
        let table = LossTable::generate();
        let layout = JsonLayout::parse(b"{\"s\":\"abcd\"}").unwrap();
        let key = lane_key(layout.skeleton(), 0).unwrap();
        let mut coder = M3ValueCoder::with_inner(M1ValueCoder);
        coder.after_miss_insert(0, &layout).unwrap();
        assert!(coder.contains(b"\"abcd\""));

        let mut events = EventEncoder::new(&table, m3_contexts().unwrap(), M3_ARM_ID, 0);
        coder
            .encode_value(&mut events, 0, 0, key, b"\"abcd\"")
            .unwrap();
        assert_eq!(events.ledger().modeled_binary_events, 17);
    }

    #[test]
    fn m3_miss_charges_one_bit_over_the_inner_coder() {
        let table = LossTable::generate();
        let layout = JsonLayout::parse(b"{\"s\":\"abcd\"}").unwrap();
        let key = lane_key(layout.skeleton(), 0).unwrap();

        let mut plain = EventEncoder::new(&table, m3_contexts().unwrap(), M3_ARM_ID, 0);
        encode_m1_value(&mut plain, key, b"\"wxyz\"").unwrap();
        let inner_cost = plain.ledger().modeled_binary_events;

        let mut coder = M3ValueCoder::with_inner(M1ValueCoder);
        let mut events = EventEncoder::new(&table, m3_contexts().unwrap(), M3_ARM_ID, 0);
        coder
            .encode_value(&mut events, 0, 0, key, b"\"wxyz\"")
            .unwrap();
        assert_eq!(events.ledger().modeled_binary_events, inner_cost + 1);
        assert!(coder.contains(b"\"wxyz\""));
    }

    #[test]
    fn duplicate_values_within_one_record_hit_after_the_first_lane() {
        let table = LossTable::generate();
        let layout = JsonLayout::parse(b"{\"a\":\"dup\",\"b\":\"dup\"}").unwrap();
        let key0 = lane_key(layout.skeleton(), 0).unwrap();
        let key1 = lane_key(layout.skeleton(), 1).unwrap();
        let mut coder = M3ValueCoder::with_inner(M1ValueCoder);
        let mut events = EventEncoder::new(&table, m3_contexts().unwrap(), M3_ARM_ID, 0);
        coder
            .encode_value(&mut events, 0, 0, key0, b"\"dup\"")
            .unwrap();
        let after_first = events.ledger().modeled_binary_events;
        coder
            .encode_value(&mut events, 0, 1, key1, b"\"dup\"")
            .unwrap();
        assert_eq!(events.ledger().modeled_binary_events - after_first, 17);
    }

    #[test]
    fn cache_boundary_is_exactly_128_bytes() {
        let mut coder = M3ValueCoder::with_inner(M1ValueCoder);
        let cacheable = vec![b'a'; M3_SLOT_VALUE_BYTES];
        let oversized = vec![b'b'; M3_SLOT_VALUE_BYTES + 1];
        coder.store.insert(&cacheable).unwrap();
        coder.store.insert(&oversized).unwrap();
        assert!(coder.contains(&cacheable));
        assert!(!coder.contains(&oversized));

        // An oversized value still round-trips exactly through the chain.
        let long_value = "z".repeat(200);
        let source = format!("{{\"v\":\"{long_value}\"}}\n{{\"v\":\"{long_value}\"}}\n");
        round_trip(source.as_bytes(), 3);
    }

    #[test]
    fn eviction_follows_the_frozen_clock_with_reference_protection() {
        let mut store = SessionStore::new();
        for index in 0..M3_SESSION_SLOTS {
            store.insert(format!("v{index:05}").as_bytes()).unwrap();
        }
        // Referencing slot 0's value protects it; the next insertion clears
        // that reference bit while scanning and claims slot 1 instead.
        assert_eq!(store.lookup(b"v00000"), Some(0));
        store.insert(b"overflow-one").unwrap();
        assert_eq!(store.lookup(b"v00000"), Some(0));
        assert_eq!(store.lookup(b"v00001"), None);
        assert_eq!(store.lookup(b"overflow-one"), Some(1));

        // The hand advanced past the claim; slot 0's bit was cleared during
        // the scan, so the next insertion evicts slot 2's original value.
        store.insert(b"overflow-two").unwrap();
        assert_eq!(store.lookup(b"v00002"), None);
        assert_eq!(store.lookup(b"overflow-two"), Some(2));
    }

    #[test]
    fn values_consumed_by_m2_hits_never_touch_m3_state() {
        let table = LossTable::generate();
        let layout = JsonLayout::parse(b"{\"id\":100}").unwrap();
        let key = lane_key(layout.skeleton(), 0).unwrap();
        let mut chain = m3_chain();
        chain.after_miss_insert(0, &layout).unwrap();
        assert!(chain.inner_mut().contains(b"100"));

        let mut events = EventEncoder::new(&table, m3_contexts().unwrap(), M3_ARM_ID, 0);
        chain.encode_value(&mut events, 0, 0, key, b"101").unwrap();
        assert!(!chain.inner_mut().contains(b"101"));

        // An M2 escape reaches M3 and is taught there.
        chain
            .encode_value(&mut events, 0, 0, key, b"\"esc\"")
            .unwrap();
        assert!(chain.inner_mut().contains(b"\"esc\""));
    }

    #[test]
    fn decoder_rejects_references_to_unoccupied_slots() {
        let table = LossTable::generate();
        let layout = JsonLayout::parse(b"{\"s\":\"abcd\"}").unwrap();
        let key = lane_key(layout.skeleton(), 0).unwrap();
        let mut events = EventEncoder::new(&table, m3_contexts().unwrap(), M3_ARM_ID, 0);
        events.bit(M3_HIT_BASE + bucket(key), true).unwrap();
        events.symbol(REFERENCE_TREE, 5).unwrap();
        let (tape, _) = events.finish();

        let mut coder = M3ValueCoder::with_inner(M1ValueCoder);
        let mut decoder = EventDecoder::new(&table, m3_contexts().unwrap(), &tape);
        assert_eq!(
            coder.decode_value(&mut decoder, 0, 0, key),
            Err(ChassisError::SessionReference)
        );
    }

    #[test]
    fn arm_and_item_identity_are_bound() {
        let table = LossTable::generate();
        let source = b"{\"a\":\"x\"}\n";
        let (tape, ledger) = encode_m1_m2_m3_item(source, &table, 4).unwrap();
        assert_eq!(
            decode_m1_m2_m3_item(&tape, ledger, &table, 5),
            Err(ChassisError::TapeIdentityMismatch)
        );
        let (m2_tape, m2_ledger) = encode_m1_m2_item(source, &table, 4).unwrap();
        assert_eq!(
            decode_m1_m2_m3_item(&m2_tape, m2_ledger, &table, 4),
            Err(ChassisError::TapeIdentityMismatch)
        );
    }

    #[test]
    fn full_chain_round_trip_survives_a_clock_eviction_cycle() {
        // More unique cacheable values than session slots, all flowing
        // through the arm-3 entry points, so both the encoder and the decoder
        // run CLOCK evictions mid-stream. A recently taught value then hits
        // after evictions began, and the very first value — already evicted —
        // misses again and still round-trips exactly.
        let table = LossTable::generate();
        let total = M3_SESSION_SLOTS + 40;
        let mut source = Vec::with_capacity(total * 16 + 48);
        for index in 0..total {
            source.extend_from_slice(format!("{{\"s\":\"a{index:06}\"}}\n").as_bytes());
        }
        source.extend_from_slice(format!("{{\"s\":\"a{:06}\"}}\n", total - 2).as_bytes());
        source.extend_from_slice(b"{\"s\":\"a000000\"}\n");

        let (tape, ledger) = encode_m1_m2_m3_item(&source, &table, 5).unwrap();
        assert_eq!(
            decode_m1_m2_m3_item(&tape, ledger, &table, 5).unwrap(),
            source
        );
    }

    #[test]
    fn declared_state_is_fixed_and_slot_table_never_grows() {
        let mut coder = M3ValueCoder::with_inner(M1ValueCoder);
        assert_eq!(coder.declared_state_bytes(), M3_DECLARED_STATE_BYTES);
        for index in 0..2 * M3_SESSION_SLOTS {
            coder
                .store
                .insert(format!("s{index:06}").as_bytes())
                .unwrap();
        }
        assert_eq!(coder.store.slots.len(), M3_SESSION_SLOTS);
        assert_eq!(coder.declared_state_bytes(), M3_DECLARED_STATE_BYTES);
        let resident: usize = coder
            .store
            .slots
            .iter()
            .map(|slot| slot.bytes.as_deref().map_or(0, <[u8]>::len))
            .sum();
        assert!(resident <= M3_SESSION_SLOTS * M3_SLOT_VALUE_BYTES);
    }
}
