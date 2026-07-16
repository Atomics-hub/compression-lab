use std::collections::HashMap;
use std::ffi::c_void;
use std::slice;

const OK: i32 = 0;
const NULL_POINTER: i32 = 1;
const INVALID_INPUT: i32 = 2;
const OUTPUT_TOO_SMALL: i32 = 3;
const ALLOCATION_FAILED: i32 = 4;
const ZSTD_ERROR: i32 = 5;
const STX_MAGIC: &[u8; 4] = b"STX1";
const STX_MARKER: u8 = 0xff;
const STX_ESCAPED_MARKER: u8 = 0xfe;
const STX_MAX_DICTIONARY: usize = 254;
const STX_MAX_TOKEN_SIZE: usize = 64;
const STX_MAX_STREAM_CHUNK: usize = 16 * 1024 * 1024;

#[repr(C)]
pub struct ZstdInBuffer {
    src: *const c_void,
    size: usize,
    pos: usize,
}

#[repr(C)]
pub struct ZstdOutBuffer {
    dst: *mut c_void,
    size: usize,
    pos: usize,
}

type ZstdCreateDStream = unsafe extern "C" fn() -> *mut c_void;
type ZstdFreeDStream = unsafe extern "C" fn(*mut c_void) -> usize;
type ZstdInitDStream = unsafe extern "C" fn(*mut c_void) -> usize;
type ZstdDecompressStream =
    unsafe extern "C" fn(*mut c_void, *mut ZstdOutBuffer, *mut ZstdInBuffer) -> usize;
type ZstdIsError = unsafe extern "C" fn(usize) -> u32;

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

fn representative_ranges(data: &[u8], sample_budget: usize) -> Vec<(usize, usize)> {
    if sample_budget == 0 || data.len() <= sample_budget {
        return vec![(0, data.len())];
    }
    let block = (sample_budget / 3).max(1);
    let tail = sample_budget.saturating_sub(2 * block).max(1);
    let middle = data.len() / 2 - block / 2;
    let mut ranges = vec![
        (0, block.min(data.len())),
        (middle, (middle + block).min(data.len())),
        (data.len().saturating_sub(tail), data.len()),
    ];
    for (start, end) in &mut ranges {
        while *start > 0
            && *start < data.len()
            && token_continue(data[*start - 1])
            && token_continue(data[*start])
        {
            *start += 1;
        }
        while *end > *start
            && *end < data.len()
            && token_continue(data[*end - 1])
            && token_continue(data[*end])
        {
            *end -= 1;
        }
    }
    ranges
}

fn ranked_dictionary(data: &[u8], limit: usize, sample_budget: usize) -> Vec<Vec<u8>> {
    let mut counts: HashMap<TokenKey, Vec<(Vec<u8>, usize)>> = HashMap::new();
    for (range_start, range_end) in representative_ranges(data, sample_budget) {
        let sample = &data[range_start..range_end];
        visit_token_ranges(sample, |start, end| {
            let token = &sample[start..end];
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
    }
    let mut ranked: Vec<(usize, usize, Vec<u8>)> = counts
        .into_iter()
        .flat_map(|(_, bucket)| bucket)
        .filter_map(|(token, count)| {
            let gain = count * token.len().saturating_sub(2);
            let overhead = token.len() + 1;
            if count >= 2 && gain > overhead {
                Some((gain - overhead, count, token))
            } else {
                None
            }
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

fn encode_structured_text(data: &[u8], limit: usize, sample_budget: usize) -> Vec<u8> {
    let dictionary = ranked_dictionary(data, limit, sample_budget);
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

fn structured_text_dictionary_end(data: &[u8]) -> Option<(usize, usize)> {
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
    Some((offset, count))
}

fn split_structured_text_channels(data: &[u8]) -> Option<(Vec<u8>, Vec<u8>)> {
    let (body_start, dictionary_count) = structured_text_dictionary_end(data)?;
    let mut skeleton = Vec::with_capacity(data.len());
    skeleton.extend_from_slice(&data[..body_start]);
    let mut side = Vec::new();
    let mut offset = body_start;
    while offset < data.len() {
        let value = data[offset];
        offset += 1;
        skeleton.push(value);
        if value != STX_MARKER {
            continue;
        }
        let code = *data.get(offset)?;
        offset += 1;
        if code != STX_ESCAPED_MARKER && code as usize >= dictionary_count {
            return None;
        }
        side.push(code);
    }
    Some((skeleton, side))
}

#[cfg(test)]
fn join_structured_text_channels(
    skeleton: &[u8],
    side: &[u8],
    expected_size: usize,
) -> Option<Vec<u8>> {
    let (body_start, dictionary_count) = structured_text_dictionary_end(skeleton)?;
    if skeleton.len().checked_add(side.len())? != expected_size {
        return None;
    }
    let mut transformed = Vec::with_capacity(expected_size);
    transformed.extend_from_slice(&skeleton[..body_start]);
    let mut side_offset = 0;
    for &value in &skeleton[body_start..] {
        transformed.push(value);
        if value != STX_MARKER {
            continue;
        }
        let code = *side.get(side_offset)?;
        side_offset += 1;
        if code != STX_ESCAPED_MARKER && code as usize >= dictionary_count {
            return None;
        }
        transformed.push(code);
    }
    (side_offset == side.len()).then_some(transformed)
}

fn decode_structured_text_channels(
    skeleton: &[u8],
    side: &[u8],
    expected_size: usize,
) -> Option<Vec<u8>> {
    let (body_start, dictionary_count) = structured_text_dictionary_end(skeleton)?;
    let mut dictionary: Vec<&[u8]> = Vec::with_capacity(dictionary_count);
    let mut offset = 6;
    for _ in 0..dictionary_count {
        let size = skeleton[offset] as usize;
        offset += 1;
        dictionary.push(&skeleton[offset..offset + size]);
        offset += size;
    }
    let mut output = Vec::with_capacity(expected_size);
    let mut side_offset = 0;
    for &value in &skeleton[body_start..] {
        if value != STX_MARKER {
            if output.len() == expected_size {
                return None;
            }
            output.push(value);
            continue;
        }
        let code = *side.get(side_offset)?;
        side_offset += 1;
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
    (side_offset == side.len() && output.len() == expected_size).then_some(output)
}

struct StreamingTextDecoder {
    expected_size: usize,
    output_pos: usize,
    header: Vec<u8>,
    dictionary_count: Option<usize>,
    dictionary: Vec<Vec<u8>>,
    pending_token_size: Option<usize>,
    pending_token: Vec<u8>,
    marker_pending: bool,
    invalid: bool,
}

impl StreamingTextDecoder {
    fn new(expected_size: usize) -> Self {
        Self {
            expected_size,
            output_pos: 0,
            header: Vec::with_capacity(6),
            dictionary_count: None,
            dictionary: Vec::new(),
            pending_token_size: None,
            pending_token: Vec::new(),
            marker_pending: false,
            invalid: false,
        }
    }

    fn append(&mut self, value: &[u8], output: &mut [u8]) -> bool {
        if value.len() > self.expected_size.saturating_sub(self.output_pos)
            || self.output_pos + value.len() > output.len()
        {
            self.invalid = true;
            return false;
        }
        output[self.output_pos..self.output_pos + value.len()].copy_from_slice(value);
        self.output_pos += value.len();
        true
    }

    fn update(&mut self, input: &[u8], output: &mut [u8]) -> bool {
        if self.invalid {
            return false;
        }
        let mut offset = 0;
        while offset < input.len() {
            if self.header.len() < 6 {
                let needed = 6 - self.header.len();
                let take = needed.min(input.len() - offset);
                self.header.extend_from_slice(&input[offset..offset + take]);
                offset += take;
                if self.header.len() == 6 {
                    if &self.header[..4] != STX_MAGIC {
                        self.invalid = true;
                        return false;
                    }
                    let count = u16::from_be_bytes([self.header[4], self.header[5]]) as usize;
                    if count > STX_MAX_DICTIONARY {
                        self.invalid = true;
                        return false;
                    }
                    self.dictionary_count = Some(count);
                    self.dictionary.reserve(count);
                }
                continue;
            }

            let dictionary_count = self.dictionary_count.unwrap_or(0);
            if self.dictionary.len() < dictionary_count {
                if self.pending_token_size.is_none() {
                    let size = input[offset] as usize;
                    offset += 1;
                    if size == 0 || size > STX_MAX_TOKEN_SIZE {
                        self.invalid = true;
                        return false;
                    }
                    self.pending_token_size = Some(size);
                    self.pending_token.clear();
                }
                let size = self.pending_token_size.unwrap_or(0);
                let needed = size - self.pending_token.len();
                let take = needed.min(input.len() - offset);
                self.pending_token
                    .extend_from_slice(&input[offset..offset + take]);
                offset += take;
                if self.pending_token.len() == size {
                    if !valid_dictionary_token(&self.pending_token)
                        || self.dictionary.contains(&self.pending_token)
                    {
                        self.invalid = true;
                        return false;
                    }
                    self.dictionary.push(self.pending_token.clone());
                    self.pending_token_size = None;
                }
                continue;
            }

            if self.marker_pending {
                let value = input[offset];
                offset += 1;
                self.marker_pending = false;
                if value == STX_ESCAPED_MARKER {
                    if !self.append(&[STX_MARKER], output) {
                        return false;
                    }
                } else if let Some(token) = self.dictionary.get(value as usize) {
                    if token.len() > self.expected_size.saturating_sub(self.output_pos)
                        || self.output_pos + token.len() > output.len()
                    {
                        self.invalid = true;
                        return false;
                    }
                    output[self.output_pos..self.output_pos + token.len()].copy_from_slice(token);
                    self.output_pos += token.len();
                } else {
                    self.invalid = true;
                    return false;
                }
                continue;
            }

            if let Some(relative) = input[offset..]
                .iter()
                .position(|&value| value == STX_MARKER)
            {
                if !self.append(&input[offset..offset + relative], output) {
                    return false;
                }
                offset += relative + 1;
                self.marker_pending = true;
            } else {
                if !self.append(&input[offset..], output) {
                    return false;
                }
                offset = input.len();
            }
        }
        true
    }

    fn finish(&self) -> bool {
        !self.invalid
            && self.header.len() == 6
            && self.dictionary_count == Some(self.dictionary.len())
            && self.pending_token_size.is_none()
            && !self.marker_pending
            && self.output_pos == self.expected_size
    }
}

#[no_mangle]
pub extern "C" fn clab_structured_text_decoder_create(expected_size: usize) -> *mut c_void {
    Box::into_raw(Box::new(StreamingTextDecoder::new(expected_size))) as *mut c_void
}

#[no_mangle]
/// Feed transformed bytes into a streaming decoder.
///
/// # Safety
///
/// `decoder` must be a live pointer returned by
/// `clab_structured_text_decoder_create`. `input` and `output` must be non-null
/// and valid for reads or writes of their declared lengths for the duration of
/// this call. The regions must not alias in a way that violates Rust's rules.
pub unsafe extern "C" fn clab_structured_text_decoder_update(
    decoder: *mut c_void,
    input: *const u8,
    len: usize,
    output: *mut u8,
    output_capacity: usize,
) -> i32 {
    if decoder.is_null() || input.is_null() || output.is_null() {
        return NULL_POINTER;
    }
    let state = &mut *(decoder as *mut StreamingTextDecoder);
    let source = slice::from_raw_parts(input, len);
    let destination = slice::from_raw_parts_mut(output, output_capacity);
    if state.update(source, destination) {
        OK
    } else {
        INVALID_INPUT
    }
}

#[no_mangle]
/// Validate that a streaming decoder consumed a complete STX1 stream.
///
/// # Safety
///
/// `decoder` must be a live pointer returned by
/// `clab_structured_text_decoder_create` and must not be concurrently mutated.
pub unsafe extern "C" fn clab_structured_text_decoder_finish(decoder: *mut c_void) -> i32 {
    if decoder.is_null() {
        return NULL_POINTER;
    }
    if (&*(decoder as *mut StreamingTextDecoder)).finish() {
        OK
    } else {
        INVALID_INPUT
    }
}

#[no_mangle]
/// Release a streaming decoder. A null pointer is accepted as a no-op.
///
/// # Safety
///
/// A non-null `decoder` must have been returned by
/// `clab_structured_text_decoder_create`, must not have been freed already, and
/// must not be used after this call.
pub unsafe extern "C" fn clab_structured_text_decoder_free(decoder: *mut c_void) {
    if !decoder.is_null() {
        drop(Box::from_raw(decoder as *mut StreamingTextDecoder));
    }
}

#[allow(clippy::too_many_arguments)]
unsafe fn decode_structured_text_zstd_stream(
    input: *const u8,
    len: usize,
    transformed_size: usize,
    output: *mut u8,
    expected_size: usize,
    chunk_size: usize,
    stream: *mut c_void,
    decompress_stream: ZstdDecompressStream,
    is_error: ZstdIsError,
) -> i32 {
    let mut source_buffer = ZstdInBuffer {
        src: input as *const c_void,
        size: len,
        pos: 0,
    };
    let destination = slice::from_raw_parts_mut(output, expected_size);
    let buffer_size = chunk_size.min(transformed_size.max(1));
    let mut chunk = vec![0_u8; buffer_size];
    let mut decoder = StreamingTextDecoder::new(expected_size);
    let mut total_transformed = 0_usize;

    loop {
        let input_position = source_buffer.pos;
        let mut chunk_buffer = ZstdOutBuffer {
            dst: chunk.as_mut_ptr() as *mut c_void,
            size: chunk.len(),
            pos: 0,
        };
        let remaining = decompress_stream(stream, &mut chunk_buffer, &mut source_buffer);
        if is_error(remaining) != 0 {
            return ZSTD_ERROR;
        }
        let Some(updated_total) = total_transformed.checked_add(chunk_buffer.pos) else {
            return INVALID_INPUT;
        };
        total_transformed = updated_total;
        if total_transformed > transformed_size
            || !decoder.update(&chunk[..chunk_buffer.pos], destination)
        {
            return INVALID_INPUT;
        }
        if remaining == 0 {
            if source_buffer.pos != source_buffer.size {
                return INVALID_INPUT;
            }
            break;
        }
        if source_buffer.pos == input_position && chunk_buffer.pos == 0 {
            return INVALID_INPUT;
        }
    }

    if total_transformed != transformed_size || !decoder.finish() {
        INVALID_INPUT
    } else {
        OK
    }
}

#[no_mangle]
/// Decompress a Zstandard-wrapped STX1 stream directly into output memory.
///
/// # Safety
///
/// `input` and `output` must be non-null and valid for their declared lengths.
/// Every supplied function pointer must follow the Zstandard C ABI and remain
/// valid for the complete call. The output region must not alias the input.
pub unsafe extern "C" fn clab_structured_text_zstd_decode(
    input: *const u8,
    len: usize,
    transformed_size: usize,
    output: *mut u8,
    expected_size: usize,
    chunk_size: usize,
    create_stream: Option<ZstdCreateDStream>,
    free_stream: Option<ZstdFreeDStream>,
    init_stream: Option<ZstdInitDStream>,
    decompress_stream: Option<ZstdDecompressStream>,
    is_error: Option<ZstdIsError>,
) -> i32 {
    if input.is_null() || output.is_null() || chunk_size == 0 || chunk_size > STX_MAX_STREAM_CHUNK {
        return NULL_POINTER;
    }
    let (
        Some(create_stream),
        Some(free_stream),
        Some(init_stream),
        Some(decompress_stream),
        Some(is_error),
    ) = (
        create_stream,
        free_stream,
        init_stream,
        decompress_stream,
        is_error,
    )
    else {
        return NULL_POINTER;
    };
    let stream = create_stream();
    if stream.is_null() {
        return ALLOCATION_FAILED;
    }
    let init_result = init_stream(stream);
    let status = if is_error(init_result) != 0 {
        ZSTD_ERROR
    } else {
        decode_structured_text_zstd_stream(
            input,
            len,
            transformed_size,
            output,
            expected_size,
            chunk_size,
            stream,
            decompress_stream,
            is_error,
        )
    };
    let free_result = free_stream(stream);
    if status == OK && is_error(free_result) != 0 {
        ZSTD_ERROR
    } else {
        status
    }
}

#[no_mangle]
/// Encode bytes with the STX1 transform.
///
/// # Safety
///
/// `input`, `output`, and `output_len` must be non-null. The input must be
/// readable for `len` bytes, the output writable for `output_capacity` bytes,
/// and `output_len` writable for one `usize`. Input and output must not alias.
pub unsafe extern "C" fn clab_structured_text_encode(
    input: *const u8,
    len: usize,
    dictionary_limit: usize,
    sample_budget: usize,
    output: *mut u8,
    output_capacity: usize,
    output_len: *mut usize,
) -> i32 {
    if input.is_null() || output.is_null() || output_len.is_null() {
        return NULL_POINTER;
    }
    let source = slice::from_raw_parts(input, len);
    let encoded = encode_structured_text(source, dictionary_limit, sample_budget);
    if encoded.len() > output_capacity {
        return OUTPUT_TOO_SMALL;
    }
    slice::from_raw_parts_mut(output, output_capacity)[..encoded.len()].copy_from_slice(&encoded);
    *output_len = encoded.len();
    OK
}

#[no_mangle]
/// Decode a complete STX1 transform.
///
/// # Safety
///
/// `input` and `output` must be non-null and valid for reads of `len` bytes and
/// writes of `expected_size` bytes respectively. The regions must not alias.
pub unsafe extern "C" fn clab_structured_text_decode(
    input: *const u8,
    len: usize,
    output: *mut u8,
    expected_size: usize,
) -> i32 {
    if input.is_null() || output.is_null() {
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
/// Split a valid STX1 stream into skeleton and token-code channels.
///
/// # Safety
///
/// All five pointers must be non-null. `input` must be readable for `len`
/// bytes, both outputs writable for their capacities, and both length pointers
/// writable for one `usize`. No mutable output region may alias another region.
pub unsafe extern "C" fn clab_structured_text_split_channels(
    input: *const u8,
    len: usize,
    skeleton_output: *mut u8,
    skeleton_capacity: usize,
    skeleton_len: *mut usize,
    side_output: *mut u8,
    side_capacity: usize,
    side_len: *mut usize,
) -> i32 {
    if input.is_null()
        || skeleton_output.is_null()
        || side_output.is_null()
        || skeleton_len.is_null()
        || side_len.is_null()
    {
        return NULL_POINTER;
    }
    let source = slice::from_raw_parts(input, len);
    let Some((skeleton, side)) = split_structured_text_channels(source) else {
        return INVALID_INPUT;
    };
    if skeleton.len() > skeleton_capacity || side.len() > side_capacity {
        return OUTPUT_TOO_SMALL;
    }
    slice::from_raw_parts_mut(skeleton_output, skeleton_capacity)[..skeleton.len()]
        .copy_from_slice(&skeleton);
    slice::from_raw_parts_mut(side_output, side_capacity)[..side.len()].copy_from_slice(&side);
    *skeleton_len = skeleton.len();
    *side_len = side.len();
    OK
}

#[no_mangle]
/// Recombine and decode STX1 skeleton and token-code channels.
///
/// # Safety
///
/// `skeleton`, `side`, and `output` must be non-null and valid for their
/// declared read or write lengths. The output region must not alias either
/// input region.
pub unsafe extern "C" fn clab_structured_text_decode_channels(
    skeleton: *const u8,
    skeleton_len: usize,
    side: *const u8,
    side_len: usize,
    output: *mut u8,
    expected_size: usize,
) -> i32 {
    if skeleton.is_null() || side.is_null() || output.is_null() {
        return NULL_POINTER;
    }
    let skeleton_source = slice::from_raw_parts(skeleton, skeleton_len);
    let side_source = slice::from_raw_parts(side, side_len);
    let Some(decoded) =
        decode_structured_text_channels(skeleton_source, side_source, expected_size)
    else {
        return INVALID_INPUT;
    };
    slice::from_raw_parts_mut(output, expected_size).copy_from_slice(&decoded);
    OK
}

#[no_mangle]
/// Apply 32-bit delta coding and byte-plane transpose.
///
/// # Safety
///
/// `input` and `output` must be non-null and valid for reads and writes of
/// `len` bytes. The regions must not overlap.
pub unsafe extern "C" fn clab_delta_transpose(
    input: *const u8,
    len: usize,
    output: *mut u8,
) -> i32 {
    if input.is_null() || output.is_null() {
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
/// Reverse 32-bit delta coding and byte-plane transpose.
///
/// # Safety
///
/// `input` and `output` must be non-null and valid for reads and writes of
/// `len` bytes. The regions must not overlap.
pub unsafe extern "C" fn clab_inverse_delta_transpose(
    input: *const u8,
    len: usize,
    output: *mut u8,
) -> i32 {
    if input.is_null() || output.is_null() {
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
    use std::ptr;

    #[test]
    fn ffi_rejects_null_zero_length_buffers() {
        unsafe {
            assert_eq!(
                clab_delta_transpose(ptr::null(), 0, ptr::null_mut()),
                NULL_POINTER
            );
            assert_eq!(
                clab_inverse_delta_transpose(ptr::null(), 0, ptr::null_mut()),
                NULL_POINTER
            );
            let mut output_len = 0_usize;
            assert_eq!(
                clab_structured_text_encode(
                    ptr::null(),
                    0,
                    0,
                    0,
                    ptr::null_mut(),
                    0,
                    &mut output_len,
                ),
                NULL_POINTER
            );
            assert_eq!(
                clab_structured_text_decode(ptr::null(), 0, ptr::null_mut(), 0),
                NULL_POINTER
            );
        }
    }

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
        let encoded = encode_structured_text(source, 16, source.len());
        assert_eq!(
            decode_structured_text(&encoded, source.len()),
            Some(source.to_vec())
        );
    }

    #[test]
    fn streaming_structured_text_decoder_handles_single_byte_chunks() {
        let source = b"repeated_identifier other repeated_identifier \xff tail";
        let encoded = encode_structured_text(source, 16, source.len());
        let mut decoder = StreamingTextDecoder::new(source.len());
        let mut output = vec![0_u8; source.len()];
        for value in &encoded {
            assert!(decoder.update(&[*value], &mut output));
        }
        assert!(decoder.finish());
        assert_eq!(output, source);
    }

    #[test]
    fn structured_text_channels_round_trip_and_reject_invalid_side_data() {
        let source = b"alpha_token beta_token alpha_token \xff tail";
        let transformed = encode_structured_text(source, 16, usize::MAX);
        let (skeleton, side) = split_structured_text_channels(&transformed).unwrap();
        assert!(skeleton.len() < transformed.len());
        assert_eq!(
            join_structured_text_channels(&skeleton, &side, transformed.len()).unwrap(),
            transformed
        );
        assert_eq!(
            decode_structured_text_channels(&skeleton, &side, source.len()).unwrap(),
            source
        );
        assert!(join_structured_text_channels(
            &skeleton,
            &side[..side.len() - 1],
            transformed.len()
        )
        .is_none());
        let mut invalid = side.clone();
        invalid[0] = 0xff;
        assert!(join_structured_text_channels(&skeleton, &invalid, transformed.len()).is_none());
        assert!(decode_structured_text_channels(&skeleton, &invalid, source.len()).is_none());
    }
}
