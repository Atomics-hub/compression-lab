use sha2::{Digest, Sha256};
use std::error::Error;
use std::fmt::{Display, Formatter};

const MAGIC: &[u8; 4] = b"S0T1";
const DIGEST_BYTES: usize = 32;
const HEADER_BYTES: usize = 4 + 1 + 1 + 8;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Tape {
    arm_id: u8,
    item_index: u8,
    bit_count: u64,
    bit_bytes: Vec<u8>,
    literals: Vec<u8>,
}

impl Tape {
    pub fn from_bytes(data: &[u8]) -> Result<Self, TapeError> {
        if data.len() < HEADER_BYTES + 8 + DIGEST_BYTES || data.get(..4) != Some(MAGIC) {
            return Err(TapeError::InvalidHeader);
        }
        let payload_end = data.len() - DIGEST_BYTES;
        let expected_digest = Sha256::digest(&data[..payload_end]);
        if expected_digest.as_slice() != &data[payload_end..] {
            return Err(TapeError::DigestMismatch);
        }

        let arm_id = data[4];
        let item_index = data[5];
        let bit_count = read_u64(data, 6)?;
        let bit_bytes_len =
            usize::try_from(bit_count.div_ceil(8)).map_err(|_| TapeError::Overflow)?;
        let bit_start = HEADER_BYTES;
        let bit_end = bit_start
            .checked_add(bit_bytes_len)
            .ok_or(TapeError::Overflow)?;
        let literal_count = read_u64(data, bit_end)?;
        let literal_start = bit_end.checked_add(8).ok_or(TapeError::Overflow)?;
        let literal_count = usize::try_from(literal_count).map_err(|_| TapeError::Overflow)?;
        let literal_end = literal_start
            .checked_add(literal_count)
            .ok_or(TapeError::Overflow)?;
        if literal_end != payload_end {
            return Err(TapeError::TrailingOrTruncatedData);
        }
        if bit_count % 8 != 0 && bit_bytes_len != 0 {
            let unused = 8 - (bit_count % 8) as u8;
            let mask = (1_u8 << unused) - 1;
            if data[bit_end - 1] & mask != 0 {
                return Err(TapeError::NonCanonicalPadding);
            }
        }
        Ok(Self {
            arm_id,
            item_index,
            bit_count,
            bit_bytes: data[bit_start..bit_end].to_vec(),
            literals: data[literal_start..literal_end].to_vec(),
        })
    }

    #[must_use]
    pub fn arm_id(&self) -> u8 {
        self.arm_id
    }

    #[must_use]
    pub fn item_index(&self) -> u8 {
        self.item_index
    }

    #[must_use]
    pub fn to_bytes(&self) -> Vec<u8> {
        let mut output = Vec::with_capacity(
            HEADER_BYTES + self.bit_bytes.len() + 8 + self.literals.len() + DIGEST_BYTES,
        );
        output.extend_from_slice(MAGIC);
        output.push(self.arm_id);
        output.push(self.item_index);
        output.extend_from_slice(&self.bit_count.to_le_bytes());
        output.extend_from_slice(&self.bit_bytes);
        output.extend_from_slice(&(self.literals.len() as u64).to_le_bytes());
        output.extend_from_slice(&self.literals);
        let digest = Sha256::digest(&output);
        output.extend_from_slice(&digest);
        output
    }

    #[must_use]
    pub fn reader(&self) -> TapeReader<'_> {
        TapeReader {
            tape: self,
            bit_offset: 0,
            literal_offset: 0,
        }
    }
}

#[derive(Clone, Debug)]
pub struct TapeWriter {
    arm_id: u8,
    item_index: u8,
    bit_count: u64,
    bit_bytes: Vec<u8>,
    literals: Vec<u8>,
}

impl TapeWriter {
    #[must_use]
    pub fn new(arm_id: u8, item_index: u8) -> Self {
        Self {
            arm_id,
            item_index,
            bit_count: 0,
            bit_bytes: Vec::new(),
            literals: Vec::new(),
        }
    }

    pub fn push_bit(&mut self, bit: bool) -> Result<(), TapeError> {
        let byte_offset = usize::try_from(self.bit_count / 8).map_err(|_| TapeError::Overflow)?;
        let bit_offset = (self.bit_count % 8) as u8;
        if bit_offset == 0 {
            self.bit_bytes.push(0);
        }
        if bit {
            self.bit_bytes[byte_offset] |= 1 << (7 - bit_offset);
        }
        self.bit_count = self.bit_count.checked_add(1).ok_or(TapeError::Overflow)?;
        Ok(())
    }

    pub fn push_literals(&mut self, bytes: &[u8]) -> Result<(), TapeError> {
        self.literals
            .len()
            .checked_add(bytes.len())
            .ok_or(TapeError::Overflow)?;
        self.literals.extend_from_slice(bytes);
        Ok(())
    }

    #[must_use]
    pub fn finish(self) -> Tape {
        Tape {
            arm_id: self.arm_id,
            item_index: self.item_index,
            bit_count: self.bit_count,
            bit_bytes: self.bit_bytes,
            literals: self.literals,
        }
    }
}

pub struct TapeReader<'a> {
    tape: &'a Tape,
    bit_offset: u64,
    literal_offset: usize,
}

impl TapeReader<'_> {
    pub fn read_bit(&mut self) -> Result<bool, TapeError> {
        if self.bit_offset >= self.tape.bit_count {
            return Err(TapeError::ExhaustedBits);
        }
        let byte_offset = usize::try_from(self.bit_offset / 8).map_err(|_| TapeError::Overflow)?;
        let bit_offset = (self.bit_offset % 8) as u8;
        let bit = self.tape.bit_bytes[byte_offset] & (1 << (7 - bit_offset)) != 0;
        self.bit_offset += 1;
        Ok(bit)
    }

    pub fn read_literals(&mut self, count: usize) -> Result<&[u8], TapeError> {
        let end = self
            .literal_offset
            .checked_add(count)
            .ok_or(TapeError::Overflow)?;
        let bytes = self
            .tape
            .literals
            .get(self.literal_offset..end)
            .ok_or(TapeError::ExhaustedLiterals)?;
        self.literal_offset = end;
        Ok(bytes)
    }

    #[must_use]
    pub fn is_finished(&self) -> bool {
        self.bit_offset == self.tape.bit_count && self.literal_offset == self.tape.literals.len()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TapeError {
    InvalidHeader,
    DigestMismatch,
    TrailingOrTruncatedData,
    NonCanonicalPadding,
    ExhaustedBits,
    ExhaustedLiterals,
    Overflow,
}

impl Display for TapeError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "S0 tape error: {self:?}")
    }
}

impl Error for TapeError {}

fn read_u64(data: &[u8], offset: usize) -> Result<u64, TapeError> {
    let end = offset.checked_add(8).ok_or(TapeError::Overflow)?;
    let bytes: [u8; 8] = data
        .get(offset..end)
        .ok_or(TapeError::TrailingOrTruncatedData)?
        .try_into()
        .map_err(|_| TapeError::TrailingOrTruncatedData)?;
    Ok(u64::from_le_bytes(bytes))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tape_round_trips_bits_literals_and_identity() {
        let mut writer = TapeWriter::new(7, 2);
        for bit in [true, false, true, true, false, false, true, false, true] {
            writer.push_bit(bit).unwrap();
        }
        writer.push_literals(b"exact bytes\n").unwrap();
        let encoded = writer.finish().to_bytes();
        let tape = Tape::from_bytes(&encoded).unwrap();
        assert_eq!(tape.arm_id, 7);
        assert_eq!(tape.item_index, 2);
        let mut reader = tape.reader();
        for expected in [true, false, true, true, false, false, true, false, true] {
            assert_eq!(reader.read_bit().unwrap(), expected);
        }
        assert_eq!(reader.read_literals(12).unwrap(), b"exact bytes\n");
        assert!(reader.is_finished());
    }

    #[test]
    fn tape_rejects_corruption_noncanonical_padding_and_trailing_data() {
        let mut writer = TapeWriter::new(1, 0);
        writer.push_bit(true).unwrap();
        writer.push_literals(b"x").unwrap();
        let canonical = writer.finish().to_bytes();

        let mut corrupt = canonical.clone();
        corrupt[4] ^= 1;
        assert_eq!(Tape::from_bytes(&corrupt), Err(TapeError::DigestMismatch));

        let mut padded = canonical.clone();
        padded[HEADER_BYTES] |= 1;
        let digest_start = padded.len() - DIGEST_BYTES;
        let digest = Sha256::digest(&padded[..digest_start]);
        padded[digest_start..].copy_from_slice(&digest);
        assert_eq!(
            Tape::from_bytes(&padded),
            Err(TapeError::NonCanonicalPadding)
        );

        let mut trailing = canonical[..canonical.len() - DIGEST_BYTES].to_vec();
        trailing.push(0);
        let digest = Sha256::digest(&trailing);
        trailing.extend_from_slice(&digest);
        assert_eq!(
            Tape::from_bytes(&trailing),
            Err(TapeError::TrailingOrTruncatedData)
        );
    }

    #[test]
    fn reader_fails_closed_on_exhaustion() {
        let tape = TapeWriter::new(0, 0).finish();
        let mut reader = tape.reader();
        assert_eq!(reader.read_bit(), Err(TapeError::ExhaustedBits));
        assert_eq!(reader.read_literals(1), Err(TapeError::ExhaustedLiterals));
        assert!(reader.is_finished());
    }
}
