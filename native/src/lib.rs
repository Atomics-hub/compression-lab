use std::collections::HashMap;
use std::slice;

const OK: i32 = 0;
const NULL_POINTER: i32 = 1;
const INVALID_INPUT: i32 = 2;
const OUTPUT_TOO_SMALL: i32 = 3;
const STX_MAGIC: &[u8; 4] = b"STX1";
const STX_MARKER: u8 = 0xff;
const STX_ESCAPED_MARKER: u8 = 0xfe;
const STX_MAX_DICTIONARY: usize = 254;
const STX_MAX_TOKEN_SIZE: usize = 64;

fn token_start(value: u8) -> bool {
    value.is_ascii_alphabetic() || value == b'_'
}

fn token_continue(value: u8) -> bool {
    value.is_ascii_alphanumeric() || value == b'_'
}

fn visit_token_ranges<F: FnMut(usize, usize)>(data: &[u8], mut visit: F) {
    let mut offset = 0;
    while offset < data.len() {
        if !token_start(data[offset]) {
            offset += 1;
            continue;
        }
        let start = offset;
        offset += 1;
        while offset < data.len()
            && offset - start < STX_MAX_TOKEN_SIZE
            && token_continue(data[offset])
        {
            offset += 1;
        }
        if offset - start >= 3 {
            visit(start, offset);
        }
    }
}

#[derive(Clone, Copy, Eq, Hash, PartialEq)]
struct TokenKey(u64, u64);

fn token_key(token: &[u8]) -> TokenKey {
    let mut first = 0xcbf29ce484222325_u64;
    let mut second = 0x9e3779b97f4a7c15_u64;
    for &value in token {
        first ^= value as u64;
        first = first.wrapping_mul(0x100000001b3);
        second ^= (value as u64).wrapping_add(0x9e37);
        second = second.rotate_left(7).wrapping_mul(0x9ddfea08eb382d69);
    }
    TokenKey(first, second)
}

fn ranked_dictionary(data: &[u8], limit: usize) -> Vec<Vec<u8>> {
    let mut counts: HashMap<TokenKey, Vec<(Vec<u8>, usize)>> = HashMap::new();
    visit_token_ranges(data, |start, end| {
        let token = &data[start..end];
        let bucket = counts.entry(token_key(token)).or_default();
        if let Some((_, count)) = bucket
            .iter_mut()
            .find(|(stored, _)| stored.as_slice() == token)
        {
            *count += 1;
        } else {
            bucket.push((token.to_vec(), 1));
        }
    });
    let mut ranked: Vec<(usize, usize, Vec<u8>)> = counts
        .into_iter()
        .flat_map(|(_, bucket)| bucket)
        .filter_map(|(token, count)| {
            let gain = count * token.len().saturating_sub(2);
            let overhead = token.len() + 1;
            (count >= 2 && gain > overhead).then_some((gain - overhead, count, token))
        })
        .collect();
    ranked.sort_by(|left, right| {
        right
            .0
            .cmp(&left.0)
            .then_with(|| right.1.cmp(&left.1))
            .then_with(|| left.2.cmp(&right.2))
    });
    ranked
        .into_iter()
        .take(limit.min(STX_MAX_DICTIONARY))
        .map(|(_, _, token)| token)
        .collect()
}

fn encode_structured_text(data: &[u8], limit: usize) -> Vec<u8> {
    let dictionary = ranked_dictionary(data, limit);
    let mut codes: HashMap<TokenKey, Vec<(&[u8], u8)>> = HashMap::new();
    for (code, token) in dictionary.iter().enumerate() {
        codes
            .entry(token_key(token))
            .or_default()
            .push((token, code as u8));
    }
    let mut output = Vec::with_capacity(data.len() + 6);
    output.extend_from_slice(STX_MAGIC);
    output.extend_from_slice(&(dictionary.len() as u16).to_be_bytes());
    for token in &dictionary {
        output.push(token.len() as u8);
        output.extend_from_slice(token);
    }
    let mut copied = 0;
    visit_token_ranges(data, |start, end| {
        for &value in &data[copied..start] {
            output.push(value);
            if value == STX_MARKER {
                output.push(STX_ESCAPED_MARKER);
            }
        }
        let token = &data[start..end];
        let code = codes.get(&token_key(token)).and_then(|bucket| {
            bucket
                .iter()
                .find(|(stored, _)| *stored == token)
                .map(|(_, code)| *code)
        });
        if let Some(code) = code {
            output.extend_from_slice(&[STX_MARKER, code]);
        } else {
            output.extend_from_slice(&data[start..end]);
        }
        copied = end;
    });
    for &value in &data[copied..] {
        output.push(value);
        if value == STX_MARKER {
            output.push(STX_ESCAPED_MARKER);
        }
    }
    output
}

fn valid_dictionary_token(token: &[u8]) -> bool {
    (3..=STX_MAX_TOKEN_SIZE).contains(&token.len())
        && token_start(token[0])
        && token[1..].iter().all(|&value| token_continue(value))
}

fn decode_structured_text(data: &[u8], expected_size: usize) -> Option<Vec<u8>> {
    if data.len() < 6 || &data[..4] != STX_MAGIC {
        return None;
    }
    let count = u16::from_be_bytes([data[4], data[5]]) as usize;
    if count > STX_MAX_DICTIONARY {
        return None;
    }
    let mut offset = 6;
    let mut dictionary: Vec<&[u8]> = Vec::with_capacity(count);
    for _ in 0..count {
        let size = *data.get(offset)? as usize;
        offset += 1;
        let token = data.get(offset..offset.checked_add(size)?)?;
        offset += size;
        if !valid_dictionary_token(token) || dictionary.contains(&token) {
            return None;
        }
        dictionary.push(token);
    }
    let mut output = Vec::with_capacity(expected_size);
    while offset < data.len() {
        let value = data[offset];
        offset += 1;
        if value != STX_MARKER {
            if output.len() == expected_size {
                return None;
            }
            output.push(value);
            continue;
        }
        let code = *data.get(offset)?;
        offset += 1;
        let token = if code == STX_ESCAPED_MARKER {
            &[STX_MARKER][..]
        } else {
            *dictionary.get(code as usize)?
        };
        if token.len() > expected_size.saturating_sub(output.len()) {
            return None;
        }
        output.extend_from_slice(token);
    }
    (output.len() == expected_size).then_some(output)
}

#[no_mangle]
pub unsafe extern "C" fn clab_structured_text_encode(
    input: *const u8,
    len: usize,
    dictionary_limit: usize,
    output: *mut u8,
    output_capacity: usize,
    output_len: *mut usize,
) -> i32 {
    if ((input.is_null() || output.is_null()) && len != 0) || output_len.is_null() {
        return NULL_POINTER;
    }
    let source = slice::from_raw_parts(input, len);
    let encoded = encode_structured_text(source, dictionary_limit);
    if encoded.len() > output_capacity {
        return OUTPUT_TOO_SMALL;
    }
    slice::from_raw_parts_mut(output, output_capacity)[..encoded.len()]
        .copy_from_slice(&encoded);
    *output_len = encoded.len();
    OK
}

#[no_mangle]
pub unsafe extern "C" fn clab_structured_text_decode(
    input: *const u8,
    len: usize,
    output: *mut u8,
    expected_size: usize,
) -> i32 {
    if (input.is_null() && len != 0) || (output.is_null() && expected_size != 0) {
        return NULL_POINTER;
    }
    let source = slice::from_raw_parts(input, len);
    let Some(decoded) = decode_structured_text(source, expected_size) else {
        return INVALID_INPUT;
    };
    slice::from_raw_parts_mut(output, expected_size).copy_from_slice(&decoded);
    OK
}

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

    #[test]
    fn structured_text_round_trip_preserves_markers_and_tokens() {
        let source = b"repeated_identifier other repeated_identifier \xff tail";
        let encoded = encode_structured_text(source, 16);
        assert_eq!(decode_structured_text(&encoded, source.len()), Some(source.to_vec()));
    }
}
