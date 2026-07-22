//! Deterministic bounded skeleton storage for the S0 M1 chassis.

use std::error::Error;
use std::fmt::{Display, Formatter};

pub const TEMPLATE_SLOTS: usize = 4_096;
pub const TEMPLATE_ARENA_BYTES: usize = 4 * 1_048_576;
pub const MAX_SKELETON_BYTES: usize = 65_536;
pub const DECLARED_SLOT_BYTES: usize = 64;
const _: () = assert!(std::mem::size_of::<Slot>() <= DECLARED_SLOT_BYTES);

const FNV_OFFSET: u64 = 14_695_981_039_346_656_037;
const FNV_PRIME: u64 = 1_099_511_628_211;

#[derive(Clone, Debug, Default, Eq, PartialEq)]
struct Slot {
    hash: u64,
    bytes: Option<Box<[u8]>>,
    referenced: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct TemplateHit {
    pub slot: usize,
    pub same_as_last: bool,
}

#[derive(Clone, Debug)]
pub struct TemplateStore {
    slots: Box<[Slot]>,
    arena_bytes: usize,
    arena_limit: usize,
    maximum_skeleton_bytes: usize,
    hand: usize,
    last_slot: Option<usize>,
}

impl Default for TemplateStore {
    fn default() -> Self {
        Self::new()
    }
}

impl TemplateStore {
    /// Construct the fixed empty item state. Item boundaries reset the store by
    /// dropping it and constructing a new instance; there is no partial reset.
    #[must_use]
    pub fn new() -> Self {
        Self::with_limits(TEMPLATE_SLOTS, TEMPLATE_ARENA_BYTES, MAX_SKELETON_BYTES)
            .expect("frozen template limits are valid")
    }

    fn with_limits(
        slot_count: usize,
        arena_limit: usize,
        maximum_skeleton_bytes: usize,
    ) -> Result<Self, TemplateError> {
        if slot_count == 0
            || arena_limit == 0
            || maximum_skeleton_bytes == 0
            || maximum_skeleton_bytes > arena_limit
        {
            return Err(TemplateError::InvalidLimits);
        }
        Ok(Self {
            slots: (0..slot_count)
                .map(|_| Slot::default())
                .collect::<Vec<_>>()
                .into_boxed_slice(),
            arena_bytes: 0,
            arena_limit,
            maximum_skeleton_bytes,
            hand: 0,
            last_slot: None,
        })
    }

    /// Encoder-side exact lookup. Hashes only reject non-candidates; equality
    /// always compares the complete skeleton bytes.
    pub fn lookup(&mut self, skeleton: &[u8]) -> Option<TemplateHit> {
        let hash = fnv1a64(skeleton);
        let slot = self.slots.iter().position(|candidate| {
            candidate.hash == hash && candidate.bytes.as_deref() == Some(skeleton)
        })?;
        let same_as_last = self.last_slot == Some(slot);
        self.slots[slot].referenced = true;
        self.last_slot = Some(slot);
        Some(TemplateHit { slot, same_as_last })
    }

    /// Decoder-side selection by the fully charged grammar slot.
    pub fn select(&mut self, slot: usize) -> Result<&[u8], TemplateError> {
        let candidate = self
            .slots
            .get_mut(slot)
            .ok_or(TemplateError::SlotOutOfRange)?;
        let bytes = candidate.bytes.as_deref().ok_or(TemplateError::EmptySlot)?;
        candidate.referenced = true;
        self.last_slot = Some(slot);
        Ok(bytes)
    }

    /// Insert an observed miss. Returns `None` for an explicitly uncacheable
    /// skeleton and clears `last_slot` on that path.
    pub fn insert(&mut self, skeleton: &[u8]) -> Result<Option<usize>, TemplateError> {
        if skeleton.len() > self.maximum_skeleton_bytes {
            self.last_slot = None;
            return Ok(None);
        }
        if self.contains_exact(skeleton) {
            return Err(TemplateError::AlreadyPresent);
        }

        let target = self.next_victim(None)?;
        self.evict(target)?;
        while self
            .arena_bytes
            .checked_add(skeleton.len())
            .ok_or(TemplateError::Overflow)?
            > self.arena_limit
        {
            let extra = self.next_victim(Some(target))?;
            self.evict(extra)?;
        }

        self.slots[target] = Slot {
            hash: fnv1a64(skeleton),
            bytes: Some(skeleton.to_vec().into_boxed_slice()),
            referenced: false,
        };
        self.arena_bytes = self
            .arena_bytes
            .checked_add(skeleton.len())
            .ok_or(TemplateError::Overflow)?;
        self.last_slot = Some(target);
        self.check_invariants()?;
        Ok(Some(target))
    }

    #[must_use]
    pub fn last_slot(&self) -> Option<usize> {
        self.last_slot
    }

    #[must_use]
    pub fn resident_bytes(&self) -> usize {
        self.arena_bytes
    }

    #[must_use]
    /// Conservative logical model-state charge. Actual RSS is measured
    /// separately by the eventual runner and is never inferred from this value.
    pub fn declared_state_bytes(&self) -> usize {
        self.arena_limit + self.slots.len() * DECLARED_SLOT_BYTES
    }

    fn contains_exact(&self, skeleton: &[u8]) -> bool {
        let hash = fnv1a64(skeleton);
        self.slots
            .iter()
            .any(|candidate| candidate.hash == hash && candidate.bytes.as_deref() == Some(skeleton))
    }

    /// Frozen CLOCK transition: inspect the hand; claim an empty or zero-ref
    /// slot, otherwise clear its ref bit and advance. The hand moves only here,
    /// during insertion, and points one past every claimed victim.
    fn next_victim(&mut self, excluded: Option<usize>) -> Result<usize, TemplateError> {
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
        Err(TemplateError::ClockInvariant)
    }

    fn evict(&mut self, slot: usize) -> Result<(), TemplateError> {
        let old = self.slots[slot].bytes.take();
        if let Some(bytes) = old {
            self.arena_bytes = self
                .arena_bytes
                .checked_sub(bytes.len())
                .ok_or(TemplateError::ArenaInvariant)?;
        }
        self.slots[slot] = Slot::default();
        if self.last_slot == Some(slot) {
            self.last_slot = None;
        }
        Ok(())
    }

    fn check_invariants(&self) -> Result<(), TemplateError> {
        let actual = self.slots.iter().try_fold(0_usize, |total, slot| {
            total.checked_add(slot.bytes.as_deref().map_or(0, <[u8]>::len))
        });
        if actual != Some(self.arena_bytes) || self.arena_bytes > self.arena_limit {
            return Err(TemplateError::ArenaInvariant);
        }
        if self
            .last_slot
            .is_some_and(|slot| self.slots[slot].bytes.is_none())
        {
            return Err(TemplateError::ClockInvariant);
        }
        Ok(())
    }
}

#[must_use]
pub fn fnv1a64(bytes: &[u8]) -> u64 {
    fnv1a64_extend(FNV_OFFSET, bytes)
}

#[must_use]
pub fn fnv1a64_extend(seed: u64, bytes: &[u8]) -> u64 {
    bytes.iter().fold(seed, |hash, byte| {
        (hash ^ u64::from(*byte)).wrapping_mul(FNV_PRIME)
    })
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TemplateError {
    InvalidLimits,
    SlotOutOfRange,
    EmptySlot,
    AlreadyPresent,
    Overflow,
    ArenaInvariant,
    ClockInvariant,
}

impl Display for TemplateError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "S0 template-store error: {self:?}")
    }
}

impl Error for TemplateError {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exact_lookup_tracks_same_slot_without_trusting_hashes() {
        let mut store = TemplateStore::with_limits(3, 32, 16).unwrap();
        assert_eq!(store.insert(b"alpha"), Ok(Some(0)));
        assert_eq!(
            store.lookup(b"alpha"),
            Some(TemplateHit {
                slot: 0,
                same_as_last: true
            })
        );
        store.slots[1] = Slot {
            hash: fnv1a64(b"alpha"),
            bytes: Some(b"collision".to_vec().into_boxed_slice()),
            referenced: false,
        };
        store.arena_bytes += b"collision".len();
        assert_eq!(store.lookup(b"not-alpha"), None);
        assert_eq!(store.select(1), Ok(b"collision".as_slice()));
        assert!(!store.lookup(b"alpha").unwrap().same_as_last);
    }

    #[test]
    fn clock_clears_references_and_evicts_in_ascending_order() {
        let mut store = TemplateStore::with_limits(3, 32, 16).unwrap();
        assert_eq!(store.insert(b"a"), Ok(Some(0)));
        assert_eq!(store.insert(b"b"), Ok(Some(1)));
        assert_eq!(store.insert(b"c"), Ok(Some(2)));
        store.lookup(b"a").unwrap();
        store.lookup(b"b").unwrap();

        assert_eq!(store.insert(b"d"), Ok(Some(2)));
        assert!(store.lookup(b"c").is_none());
        assert_eq!(store.insert(b"e"), Ok(Some(0)));
        assert!(store.lookup(b"a").is_none());
        assert!(store.lookup(b"b").is_some());
        assert!(store.lookup(b"d").is_some());
        assert!(store.lookup(b"e").is_some());
    }

    #[test]
    fn arena_pressure_causes_deterministic_multi_eviction() {
        let mut store = TemplateStore::with_limits(4, 5, 4).unwrap();
        assert_eq!(store.insert(b"aa"), Ok(Some(0)));
        assert_eq!(store.insert(b"bb"), Ok(Some(1)));
        assert_eq!(store.insert(b"c"), Ok(Some(2)));
        assert_eq!(store.resident_bytes(), 5);

        assert_eq!(store.insert(b"dddd"), Ok(Some(3)));
        assert!(store.lookup(b"aa").is_none());
        assert!(store.lookup(b"bb").is_none());
        assert!(store.lookup(b"c").is_some());
        assert!(store.lookup(b"dddd").is_some());
        assert_eq!(store.resident_bytes(), 5);
    }

    #[test]
    fn arena_pressure_never_reselects_a_reserved_empty_target() {
        let mut store = TemplateStore::with_limits(3, 4, 4).unwrap();
        // Leave slot zero empty while the two resident slots are referenced.
        store.hand = 1;
        store.insert(b"aa").unwrap();
        store.insert(b"bb").unwrap();
        store.lookup(b"aa").unwrap();
        store.lookup(b"bb").unwrap();
        store.hand = 0;

        assert_eq!(store.insert(b"cccc"), Ok(Some(0)));
        assert_eq!(store.resident_bytes(), 4);
        assert!(store.lookup(b"aa").is_none());
        assert!(store.lookup(b"bb").is_none());
        assert!(store.lookup(b"cccc").is_some());
    }

    #[test]
    fn arena_pressure_never_reselects_a_reserved_occupied_target() {
        let mut store = TemplateStore::with_limits(3, 6, 6).unwrap();
        store.insert(b"a").unwrap();
        store.insert(b"bb").unwrap();
        store.insert(b"ccc").unwrap();
        store.lookup(b"bb").unwrap();
        store.lookup(b"ccc").unwrap();

        assert_eq!(store.insert(b"dddd"), Ok(Some(0)));
        assert_eq!(store.resident_bytes(), 4);
        assert!(store.lookup(b"a").is_none());
        assert!(store.lookup(b"bb").is_none());
        assert!(store.lookup(b"ccc").is_none());
        assert!(store.lookup(b"dddd").is_some());
    }

    #[test]
    fn oversized_skeleton_is_skipped_and_clears_last_slot() {
        let mut store = TemplateStore::with_limits(2, 8, 4).unwrap();
        store.insert(b"ok").unwrap();
        assert_eq!(store.last_slot(), Some(0));
        assert_eq!(store.insert(b"12345"), Ok(None));
        assert_eq!(store.last_slot(), None);
        assert!(store.lookup(b"ok").is_some());
    }

    #[test]
    fn selection_and_duplicate_insertion_fail_closed() {
        assert!(matches!(
            TemplateStore::with_limits(0, 8, 4),
            Err(TemplateError::InvalidLimits)
        ));
        assert!(matches!(
            TemplateStore::with_limits(2, 4, 5),
            Err(TemplateError::InvalidLimits)
        ));
        let mut store = TemplateStore::with_limits(2, 8, 4).unwrap();
        assert_eq!(store.select(2), Err(TemplateError::SlotOutOfRange));
        assert_eq!(store.select(0), Err(TemplateError::EmptySlot));
        store.insert(b"x").unwrap();
        assert_eq!(store.insert(b"x"), Err(TemplateError::AlreadyPresent));
    }

    #[test]
    fn frozen_store_is_bounded_and_deterministic() {
        fn exercise() -> TemplateStore {
            let mut store = TemplateStore::new();
            for index in 0..10_000_u32 {
                let mut skeleton = format!("{{\"key-{index}\":").into_bytes();
                skeleton.extend_from_slice(&[0xff, 0, b'}']);
                store.insert(&skeleton).unwrap();
                if index % 7 == 0 {
                    store.lookup(&skeleton).unwrap();
                }
            }
            store
        }
        let first = exercise();
        let second = exercise();
        assert_eq!(first.slots, second.slots);
        assert_eq!(first.hand, second.hand);
        assert_eq!(first.last_slot, second.last_slot);
        assert_eq!(first.arena_bytes, second.arena_bytes);
        assert!(first.arena_bytes <= TEMPLATE_ARENA_BYTES);
        assert_eq!(
            first.declared_state_bytes(),
            TEMPLATE_ARENA_BYTES + TEMPLATE_SLOTS * DECLARED_SLOT_BYTES
        );
    }
}
