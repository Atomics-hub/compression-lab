//! Whole-line reference layer for the H6 hybrid arm.
//!
//! Development-only prescreen infrastructure. This is the byte-level analogue
//! of S0's whole-value reuse (the one strongly positive S0 mechanism): a
//! bounded cache of exact whole NDJSON lines with the frozen s0 M3 CLOCK
//! eviction, dimensioned identically to `s0::m3` by reusing its constants
//! read-only (`M3_SESSION_SLOTS` = 65,536 slots, `M3_SLOT_VALUE_BYTES` = 128).
//!
//! Why the cache is reimplemented rather than calling `s0::M3ValueCoder`
//! directly: `M3ValueCoder` exposes its cache only through the `ValueCoder`
//! trait, whose methods require the s0 `EventEncoder`/`EventDecoder` and charge
//! the event kernel's own tape and ledger. The H6 floor is the moon H1 coder,
//! which charges a raw tape through the moon logistic mixer; the two charging
//! paths cannot share one tape without editing frozen s0. So the CLOCK
//! mechanism, its parameters, and the m3 constants are reused faithfully here,
//! and the reference is charged through the H1 floor's estimator instead.

use crate::s0::{Probability, M3_DECLARED_STATE_BYTES, M3_SESSION_SLOTS, M3_SLOT_VALUE_BYTES};
use std::collections::HashMap;

/// A full binary tree over the 16-bit slot identifier: 2^16 - 1 internal
/// nodes, one probability each. Mirrors the m3 reference symbol's bit tree.
pub const REFERENCE_TREE_NODES: usize = (1 << 16) - 1;
pub const REFERENCE_TREE_BYTES: usize = REFERENCE_TREE_NODES * 2;

const REFERENCE_BITS: u32 = 16;

const FNV_OFFSET: u64 = 14_695_981_039_346_656_037;
const FNV_PRIME: u64 = 1_099_511_628_211;

fn line_hash(bytes: &[u8]) -> u64 {
    // A dedicated namespace so the line cache never collides with any other
    // moon hash space.
    let seed = FNV_OFFSET ^ 0x6d6f6f6e_6c696e65; // "moonline"
    bytes.iter().fold(seed, |hash, byte| {
        (hash ^ u64::from(*byte)).wrapping_mul(FNV_PRIME)
    })
}

#[derive(Clone, Debug, Default)]
struct LineSlot {
    hash: u64,
    bytes: Option<Box<[u8]>>,
    referenced: bool,
}

/// Bounded whole-line cache with the frozen s0 M3 CLOCK rule: the hand
/// advances only during insertion, reference bits are set on charged hits,
/// cleared while scanning, and the first zero-ref slot in ascending scan order
/// from the hand is claimed. Hashes only reject non-candidates; hit selection
/// always compares complete line bytes, in ascending slot order.
pub struct LineCache {
    slots: Box<[LineSlot]>,
    index: HashMap<u64, Vec<u32>>,
    hand: usize,
}

impl Default for LineCache {
    fn default() -> Self {
        Self::new()
    }
}

impl LineCache {
    #[must_use]
    pub fn new() -> Self {
        Self {
            slots: (0..M3_SESSION_SLOTS)
                .map(|_| LineSlot::default())
                .collect::<Vec<_>>()
                .into_boxed_slice(),
            index: HashMap::new(),
            hand: 0,
        }
    }

    /// Declared logical state bytes: identical to the s0 M3 cache it mirrors.
    #[must_use]
    pub fn declared_state_bytes(&self) -> usize {
        M3_DECLARED_STATE_BYTES
    }

    /// First slot holding exactly `line`, by ascending slot index, or `None`.
    /// Sets the reference bit; lookups happen only on charged hits, on both
    /// sides.
    pub fn lookup(&mut self, line: &[u8]) -> Option<usize> {
        let hash = line_hash(line);
        let candidates = self.index.get(&hash)?;
        let slot = candidates
            .iter()
            .copied()
            .map(|slot| slot as usize)
            .find(|&slot| {
                self.slots[slot].hash == hash && self.slots[slot].bytes.as_deref() == Some(line)
            })?;
        self.slots[slot].referenced = true;
        Some(slot)
    }

    /// Decoder-side selection by the fully charged reference identifier.
    /// Fail-closed on an out-of-range or unoccupied slot.
    pub fn select(&mut self, slot: usize) -> Option<Vec<u8>> {
        let candidate = self.slots.get_mut(slot)?;
        let bytes = candidate.bytes.as_deref()?.to_vec();
        candidate.referenced = true;
        Some(bytes)
    }

    /// Teach a completed line. Uncharged; both sides call it with identical
    /// bytes. Lines outside 1..=128 bytes or already present are ignored.
    pub fn insert(&mut self, line: &[u8]) {
        if line.is_empty() || line.len() > M3_SLOT_VALUE_BYTES {
            return;
        }
        let hash = line_hash(line);
        if self.index.get(&hash).is_some_and(|candidates| {
            candidates
                .iter()
                .any(|&slot| self.slots[slot as usize].bytes.as_deref() == Some(line))
        }) {
            return;
        }
        let target = self.next_victim();
        self.evict(target);
        self.slots[target] = LineSlot {
            hash,
            bytes: Some(line.to_vec().into_boxed_slice()),
            referenced: false,
        };
        let slot = target as u32;
        let candidates = self.index.entry(hash).or_default();
        let position = candidates.partition_point(|&existing| existing < slot);
        candidates.insert(position, slot);
    }

    fn next_victim(&mut self) -> usize {
        // Bounded scan: the CLOCK always finds a victim within two sweeps.
        for _ in 0..=self.slots.len() * 2 {
            let slot = self.hand;
            self.hand = (self.hand + 1) % self.slots.len();
            let candidate = &mut self.slots[slot];
            if candidate.bytes.is_none() || !candidate.referenced {
                return slot;
            }
            candidate.referenced = false;
        }
        // Unreachable for a non-empty table; fall back to the hand deterministically.
        self.hand
    }

    fn evict(&mut self, slot: usize) {
        let Some(bytes) = self.slots[slot].bytes.take() else {
            return;
        };
        let hash = self.slots[slot].hash;
        if let Some(candidates) = self.index.get_mut(&hash) {
            let slot = slot as u32;
            if let Some(position) = candidates.iter().position(|&candidate| candidate == slot) {
                candidates.remove(position);
            }
            if candidates.is_empty() {
                self.index.remove(&hash);
            }
        }
        drop(bytes);
    }

    #[cfg(test)]
    fn contains(&self, line: &[u8]) -> bool {
        let hash = line_hash(line);
        self.index.get(&hash).is_some_and(|candidates| {
            candidates
                .iter()
                .any(|&slot| self.slots[slot as usize].bytes.as_deref() == Some(line))
        })
    }
}

/// Bit-tree coder for the 16-bit slot reference, charged through the H1
/// floor's estimator. Mirrors the m3 reference symbol: 16 modeled bits over a
/// full binary tree, one probability per node.
pub struct ReferenceCoder {
    nodes: Box<[Probability]>,
}

impl Default for ReferenceCoder {
    fn default() -> Self {
        Self::new()
    }
}

impl ReferenceCoder {
    #[must_use]
    pub fn new() -> Self {
        Self {
            nodes: vec![Probability::default(); REFERENCE_TREE_NODES].into_boxed_slice(),
        }
    }

    #[must_use]
    pub fn declared_state_bytes(&self) -> usize {
        self.nodes.len() * 2
    }

    /// Node probability cell and its per-node event identity for tree node
    /// `node`, so the caller charges the bit through the H1 estimator.
    pub fn node(&mut self, node: usize) -> &mut Probability {
        &mut self.nodes[node]
    }
}

/// Iterate the 16 bits of a slot identifier MSB-first, yielding the tree node
/// to charge and advancing it. The encoder reads its fixed slot; the decoder
/// accumulates bits. Node indices stay within `REFERENCE_TREE_NODES`.
pub struct ReferenceWalk {
    slot: u32,
    decoded: u32,
    node: usize,
    shift: i32,
}

impl ReferenceWalk {
    #[must_use]
    pub fn encode(slot: u16) -> Self {
        Self {
            slot: u32::from(slot),
            decoded: 0,
            node: 0,
            shift: REFERENCE_BITS as i32 - 1,
        }
    }

    #[must_use]
    pub fn decode() -> Self {
        Self {
            slot: 0,
            decoded: 0,
            node: 0,
            shift: REFERENCE_BITS as i32 - 1,
        }
    }

    /// The next tree node to charge, or `None` when all 16 bits are done.
    #[must_use]
    pub fn next_node(&self) -> Option<usize> {
        if self.shift < 0 {
            None
        } else {
            Some(self.node)
        }
    }

    /// The encoder's bit at the current position (the fixed slot is not
    /// mutated as the walk advances).
    #[must_use]
    pub fn encode_bit(&self) -> bool {
        (self.slot >> self.shift) & 1 == 1
    }

    /// Advance after charging `bit`, folding it into the walked node and the
    /// decode accumulator.
    pub fn advance(&mut self, bit: bool) {
        self.decoded = (self.decoded << 1) | u32::from(bit);
        self.node = self.node * 2 + 1 + usize::from(bit);
        self.shift -= 1;
    }

    /// The decoded slot after all 16 bits (decode walk only).
    #[must_use]
    pub fn decoded_slot(&self) -> usize {
        (self.decoded & 0xffff) as usize
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn declared_state_matches_the_frozen_m3_cache() {
        let cache = LineCache::new();
        assert_eq!(cache.declared_state_bytes(), M3_DECLARED_STATE_BYTES);
        assert_eq!(M3_DECLARED_STATE_BYTES, 65_536 * 144);
        let reference = ReferenceCoder::new();
        assert_eq!(reference.declared_state_bytes(), REFERENCE_TREE_BYTES);
        assert_eq!(REFERENCE_TREE_BYTES, 131_070);
    }

    #[test]
    fn lookup_hits_only_on_exact_whole_lines() {
        let mut cache = LineCache::new();
        cache.insert(b"{\"a\":1}\n");
        assert_eq!(cache.lookup(b"{\"a\":1}\n"), Some(0));
        assert_eq!(cache.lookup(b"{\"a\":1}"), None);
        assert_eq!(cache.lookup(b"{\"a\":2}\n"), None);
    }

    #[test]
    fn oversized_and_empty_lines_are_never_cached() {
        let mut cache = LineCache::new();
        cache.insert(b"");
        assert!(!cache.contains(b""));
        let oversized = vec![b'z'; M3_SLOT_VALUE_BYTES + 1];
        cache.insert(&oversized);
        assert!(!cache.contains(&oversized));
        let boundary = vec![b'y'; M3_SLOT_VALUE_BYTES];
        cache.insert(&boundary);
        assert!(cache.contains(&boundary));
    }

    #[test]
    fn eviction_follows_the_clock_with_reference_protection() {
        let mut cache = LineCache::new();
        for index in 0..M3_SESSION_SLOTS {
            cache.insert(format!("v{index:05}\n").as_bytes());
        }
        // Referencing slot 0 protects it; the next insertion clears that bit
        // while scanning and claims slot 1 instead.
        assert_eq!(cache.lookup(b"v00000\n"), Some(0));
        cache.insert(b"overflow-one\n");
        assert_eq!(cache.lookup(b"v00000\n"), Some(0));
        assert_eq!(cache.lookup(b"v00001\n"), None);
        assert_eq!(cache.lookup(b"overflow-one\n"), Some(1));
    }

    #[test]
    fn select_is_fail_closed_on_bad_slots() {
        let mut cache = LineCache::new();
        assert_eq!(cache.select(0), None);
        assert_eq!(cache.select(M3_SESSION_SLOTS + 5), None);
        cache.insert(b"line\n");
        assert_eq!(cache.select(0).as_deref(), Some(b"line\n".as_slice()));
    }

    #[test]
    fn reference_walk_round_trips_every_bit() {
        for slot in [0_u16, 1, 255, 256, 65_535, 40_000] {
            let mut encoder = ReferenceWalk::encode(slot);
            let mut decoder = ReferenceWalk::decode();
            while let (Some(en), Some(dn)) = (encoder.next_node(), decoder.next_node()) {
                assert_eq!(en, dn);
                let bit = encoder.encode_bit();
                encoder.advance(bit);
                decoder.advance(bit);
            }
            assert_eq!(decoder.decoded_slot(), usize::from(slot));
        }
    }
}
