use std::slice;

const OK: i32 = 0;
const NULL_POINTER: i32 = 1;

#[no_mangle]
pub unsafe extern "C" fn clab_delta_transpose(
    input: *const u8,
    len: usize,
    output: *mut u8,
) -> i32 {
    if (input.is_null() || output.is_null()) && len != 0 {
        return NULL_POINTER;
    }
    let source = slice::from_raw_parts(input, len);
    let destination = slice::from_raw_parts_mut(output, len);
    let word_count = len / 4;
    let core_size = word_count * 4;
    let mut previous = 0_u32;

    for index in 0..word_count {
        let offset = index * 4;
        let value = u32::from_le_bytes([
            source[offset],
            source[offset + 1],
            source[offset + 2],
            source[offset + 3],
        ]);
        let delta = value.wrapping_sub(previous);
        previous = value;
        destination[index] = delta as u8;
        destination[word_count + index] = (delta >> 8) as u8;
        destination[2 * word_count + index] = (delta >> 16) as u8;
        destination[3 * word_count + index] = (delta >> 24) as u8;
    }
    destination[core_size..].copy_from_slice(&source[core_size..]);
    OK
}

#[no_mangle]
pub unsafe extern "C" fn clab_inverse_delta_transpose(
    input: *const u8,
    len: usize,
    output: *mut u8,
) -> i32 {
    if (input.is_null() || output.is_null()) && len != 0 {
        return NULL_POINTER;
    }
    let source = slice::from_raw_parts(input, len);
    let destination = slice::from_raw_parts_mut(output, len);
    let word_count = len / 4;
    let core_size = word_count * 4;
    let mut previous = 0_u32;

    for index in 0..word_count {
        let delta = (source[index] as u32)
            | ((source[word_count + index] as u32) << 8)
            | ((source[2 * word_count + index] as u32) << 16)
            | ((source[3 * word_count + index] as u32) << 24);
        let value = previous.wrapping_add(delta);
        destination[index * 4..index * 4 + 4].copy_from_slice(&value.to_le_bytes());
        previous = value;
    }
    destination[core_size..].copy_from_slice(&source[core_size..]);
    OK
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trip_preserves_words_and_tail() {
        let mut source = Vec::new();
        for value in 0_u32..8193 {
            source.extend_from_slice(&value.wrapping_mul(17).to_le_bytes());
        }
        source.extend_from_slice(b"xyz");
        let mut transformed = vec![0_u8; source.len()];
        let mut restored = vec![0_u8; source.len()];
        unsafe {
            assert_eq!(
                clab_delta_transpose(source.as_ptr(), source.len(), transformed.as_mut_ptr()),
                OK
            );
            assert_eq!(
                clab_inverse_delta_transpose(
                    transformed.as_ptr(),
                    transformed.len(),
                    restored.as_mut_ptr()
                ),
                OK
            );
        }
        assert_eq!(restored, source);
    }
}
