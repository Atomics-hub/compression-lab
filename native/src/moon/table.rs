//! Shared open-addressed context table for the moonshot cycle-1 H1 floor arm.
//!
//! Development-only prescreen infrastructure, not a product codec. A single
//! fixed-size table of counter cells backs every hashed byte-order context; a
//! per-cell 8-bit check byte makes collisions detectable, so a mismatch either
//! evicts a weaker incumbent or probes a bounded number of neighbours before a
//! deterministic fail-closed eviction. Memory is fixed regardless of context
//! cardinality. Integer-only and deterministic: the encoder and decoder walk
//! the identical context sequence, so both evolve the table byte-for-byte.

/// Base-2 logarithm of the shared context table's cell count.
pub const H1_CONTEXT_CELL_BITS: u32 = 24;
/// Number of cells in the shared context table (2^24).
pub const H1_CONTEXT_CELLS: usize = 1 << H1_CONTEXT_CELL_BITS;
/// Declared logical bytes per cell: two u16 counters + check + priority.
pub const H1_CELL_BYTES: usize = 6;
/// Declared logical bytes of the whole context table (96 MiB).
pub const H1_CONTEXT_TABLE_BYTES: usize = H1_CONTEXT_CELLS * H1_CELL_BYTES;

/// Bounded, deterministic probe depth for a check-byte mismatch.
pub const H1_PROBE_DEPTH: usize = 4;
/// Claim strength of a freshly inserted context. An incumbent is evicted on a
/// probe only when its priority is strictly below this newcomer confidence.
pub const H1_NEWCOMER_PRIORITY: u8 = 1;
/// Counter ceiling. When either counter reaches it, both halve so the cell
/// tracks a moving average rather than a frozen lifetime frequency.
pub const H1_COUNTER_CEILING: u16 = 1 << 12;

/// One context cell: two adaptive bit counters, an 8-bit check byte that
/// detects hash collisions, and an eviction priority. An empty cell has
/// `check == 0`; every occupied cell forces its check byte nonzero.
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct Cell {
    pub zeros: u16,
    pub ones: u16,
    pub check: u8,
    pub priority: u8,
}

// The 6-byte cell width and the 96 MiB table size are load-bearing for the
// declared-state accounting; pin them at compile time.
const _: () = assert!(std::mem::size_of::<Cell>() == H1_CELL_BYTES);
const _: () = assert!(std::mem::align_of::<Cell>() == 2);
const _: () = assert!(H1_CONTEXT_TABLE_BYTES == 100_663_296);
const _: () = assert!(H1_CONTEXT_CELLS.is_power_of_two());
const _: () = assert!(H1_PROBE_DEPTH >= 1);

impl Cell {
    #[must_use]
    fn is_empty(self) -> bool {
        self.check == 0
    }

    /// Probability of a one for this context in Q16, from the two counters.
    /// An unseen (or freshly claimed) cell is maximally uncertain (one half).
    #[must_use]
    pub fn probability_of_one(self) -> u16 {
        let total = u32::from(self.zeros) + u32::from(self.ones);
        if total == 0 {
            return 1 << 15;
        }
        let scaled = (u32::from(self.ones) << 16) / total;
        scaled.clamp(1, 65_535) as u16
    }

    /// Confidence used to weight this cell when the mix is combined.
    #[must_use]
    pub fn confidence(self) -> u32 {
        u32::from(self.zeros) + u32::from(self.ones)
    }

    fn observe(&mut self, bit: bool) {
        if bit {
            self.ones = self.ones.saturating_add(1);
        } else {
            self.zeros = self.zeros.saturating_add(1);
        }
        if self.zeros >= H1_COUNTER_CEILING || self.ones >= H1_COUNTER_CEILING {
            self.zeros >>= 1;
            self.ones >>= 1;
        }
        // A u8 already saturates at 255, which is the priority ceiling.
        self.priority = self.priority.saturating_add(1);
    }
}

/// The shared context table. All eight modeled contexts of the H1 arm draw
/// their cells from this one open-addressed store.
#[derive(Clone)]
pub struct ContextTable {
    cells: Box<[Cell]>,
    mask: usize,
}

impl ContextTable {
    /// The frozen full-capacity table (2^24 cells, 96 MiB).
    #[must_use]
    pub fn new() -> Self {
        Self::with_cells(H1_CONTEXT_CELLS)
    }

    /// A table of `cells` slots (a power of two). Used at full capacity by the
    /// arm and at tiny capacity by the collision/eviction unit tests.
    #[must_use]
    pub fn with_cells(cells: usize) -> Self {
        assert!(cells.is_power_of_two(), "cell count must be a power of two");
        Self {
            cells: vec![Cell::default(); cells].into_boxed_slice(),
            mask: cells - 1,
        }
    }

    #[must_use]
    pub fn len(&self) -> usize {
        self.cells.len()
    }

    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.cells.is_empty()
    }

    /// Logical table bytes for the frozen accounting, excluding allocator
    /// overhead and O(1) scratch. Mirrors the s0 `modeled_state_bytes`
    /// convention: only the counter cells are charged.
    #[must_use]
    pub fn declared_state_bytes(&self) -> usize {
        self.cells.len() * H1_CELL_BYTES
    }

    /// Split a 64-bit context hash into its home slot and its nonzero check
    /// byte. The check byte is drawn from bits disjoint from the home index so
    /// two contexts sharing a home slot still almost always disagree on it.
    fn split(&self, hash: u64) -> (usize, u8) {
        let home = (hash as usize) & self.mask;
        let check = ((hash >> 40) as u8) | 1;
        (home, check)
    }

    /// Resolve a context hash to a cell index, applying check-byte collision
    /// eviction with a bounded deterministic probe. Never returns out of
    /// range; on probe exhaustion it evicts the weakest probed incumbent.
    pub fn resolve(&mut self, hash: u64) -> usize {
        let (home, check) = self.split(hash);
        let mut weakest = home;
        let mut weakest_priority = u16::MAX;
        for step in 0..H1_PROBE_DEPTH {
            let index = (home + step) & self.mask;
            let cell = self.cells[index];
            if cell.is_empty() {
                self.claim(index, check);
                return index;
            }
            if cell.check == check {
                return index;
            }
            // Check-byte mismatch: a genuine collision. Evict only when the
            // incumbent is weaker than the arriving context, else probe on.
            if u16::from(cell.priority) < u16::from(H1_NEWCOMER_PRIORITY) {
                self.claim(index, check);
                return index;
            }
            if u16::from(cell.priority) < weakest_priority {
                weakest_priority = u16::from(cell.priority);
                weakest = index;
            }
            // Age the incumbent so a repeatedly colliding cold cell eventually
            // drops below the newcomer confidence and becomes evictable.
            self.cells[index].priority = cell.priority.saturating_sub(1);
        }
        // Probe exhausted with no empty slot, no match, and no incumbent below
        // the newcomer confidence: fail-closed by evicting the weakest probed
        // incumbent. Deterministic and total.
        self.claim(weakest, check);
        weakest
    }

    fn claim(&mut self, index: usize, check: u8) {
        self.cells[index] = Cell {
            zeros: 0,
            ones: 0,
            check,
            priority: H1_NEWCOMER_PRIORITY,
        };
    }

    #[must_use]
    pub fn cell(&self, index: usize) -> Cell {
        self.cells[index]
    }

    /// Record an observed bit against a previously resolved cell.
    pub fn observe(&mut self, index: usize, bit: bool) {
        self.cells[index].observe(bit);
    }
}

impl Default for ContextTable {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn full_table_is_ninety_six_mebibytes_of_six_byte_cells() {
        assert_eq!(H1_CONTEXT_CELLS, 16_777_216);
        assert_eq!(H1_CONTEXT_TABLE_BYTES, 96 * 1024 * 1024);
        assert_eq!(std::mem::size_of::<Cell>(), 6);
        let table = ContextTable::new();
        assert_eq!(table.len(), H1_CONTEXT_CELLS);
        assert_eq!(table.declared_state_bytes(), H1_CONTEXT_TABLE_BYTES);
    }

    #[test]
    fn an_empty_home_slot_is_claimed_and_reused() {
        let mut table = ContextTable::with_cells(16);
        let hash = 0x1234_5678_9abc_def0;
        let first = table.resolve(hash);
        // Freshly claimed: uncertain, nonzero check, newcomer priority.
        let cell = table.cell(first);
        assert!(!cell.is_empty());
        assert_eq!(cell.priority, H1_NEWCOMER_PRIORITY);
        assert_eq!(cell.probability_of_one(), 1 << 15);
        // A second resolve of the same hash returns the same slot (a hit).
        assert_eq!(table.resolve(hash), first);
    }

    #[test]
    fn a_check_byte_mismatch_probes_before_it_evicts_a_strong_incumbent() {
        let mut table = ContextTable::with_cells(8);
        // Two hashes that share a home slot but differ in the check byte.
        let home = 3_u64;
        let incumbent = home | (0x11_u64 << 40);
        let newcomer = home | (0x22_u64 << 40);
        let incumbent_index = table.resolve(incumbent);
        // Make the incumbent strong so it is not evicted on sight.
        for _ in 0..10 {
            table.observe(incumbent_index, true);
        }
        assert!(table.cell(incumbent_index).priority > H1_NEWCOMER_PRIORITY);
        let newcomer_index = table.resolve(newcomer);
        // The strong incumbent kept its slot; the newcomer probed onward.
        assert_ne!(newcomer_index, incumbent_index);
        assert!(!table.cell(incumbent_index).is_empty());
        assert_eq!(table.cell(incumbent_index).check, 0x11 | 1);
    }

    #[test]
    fn a_cold_incumbent_is_evicted_by_confidence_order() {
        let mut table = ContextTable::with_cells(8);
        let home = 5_u64;
        let incumbent = home | (0x30_u64 << 40);
        let newcomer = home | (0x40_u64 << 40);
        let incumbent_index = table.resolve(incumbent);
        // A freshly claimed incumbent has priority == newcomer confidence, so
        // the first colliding resolve ages it rather than evicting it.
        let after_first = table.resolve(newcomer);
        assert_ne!(after_first, incumbent_index);
        assert_eq!(table.cell(incumbent_index).priority, 0);
        // Now the incumbent is below the newcomer confidence: it is evicted and
        // its slot re-checked to the newcomer.
        let evicted_to = table.resolve(newcomer | (1 << 60));
        assert_eq!(evicted_to, incumbent_index);
        assert_eq!(table.cell(incumbent_index).check, 0x40 | 1);
    }

    #[test]
    fn probe_exhaustion_is_total_and_evicts_the_weakest() {
        // A two-cell table forces exhaustion quickly: fill both slots with
        // strong incumbents that never match the newcomer's check byte.
        let mut table = ContextTable::with_cells(2);
        let a = table.resolve(0x10_u64 << 40);
        let b = table.resolve(1 | (0x20_u64 << 40));
        for _ in 0..50 {
            table.observe(a, true);
            table.observe(b, true);
        }
        // Distinct check byte, home slot 0; probe depth spans both cells.
        let newcomer = 0x33_u64 << 40;
        let resolved = table.resolve(newcomer);
        // Total function: a valid in-range slot, re-checked to the newcomer.
        assert!(resolved < table.len());
        assert_eq!(table.cell(resolved).check, 0x33 | 1);
    }

    #[test]
    fn counters_halve_at_the_ceiling_to_stay_adaptive() {
        let mut table = ContextTable::with_cells(4);
        let index = table.resolve(2 | (0x55_u64 << 40));
        for _ in 0..H1_COUNTER_CEILING {
            table.observe(index, true);
        }
        let cell = table.cell(index);
        assert!(cell.ones < H1_COUNTER_CEILING);
        assert!(cell.probability_of_one() > 60_000);
    }

    #[test]
    fn resolution_is_deterministic_across_identical_sequences() {
        fn run() -> ContextTable {
            let mut table = ContextTable::with_cells(1 << 10);
            for value in 0..5_000_u64 {
                let hash = value.wrapping_mul(0x9e37_79b9_7f4a_7c15);
                let index = table.resolve(hash);
                table.observe(index, value % 3 == 0);
            }
            table
        }
        assert_eq!(run().cells, run().cells);
    }
}
