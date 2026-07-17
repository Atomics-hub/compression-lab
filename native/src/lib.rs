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
const LWX2_MAGIC: &[u8; 4] = b"LWX2";
const LWX2_SLOT_COUNT: usize = 1024;
const LWX2_MAX_RECORD_SIZE: usize = 32 * 1024;
const LWX2_MAX_RUN: usize = 128;
const LWX2_MODE_RAW: u8 = 0;
const LWX2_MODE_REFERENCE: u8 = 1;
const JCT1_MAGIC: &[u8; 4] = b"JCT1";
const JCT1_MARKER: u8 = 0xff;
const JCT1_MARKER_CHANNEL: u8 = 0x00;
const JCT1_MARKER_LITERAL: u8 = 0xfe;
const JCT1_MAX_CHANNELS: usize = 256;

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

fn encode_varint(mut value: usize, output: &mut Vec<u8>) {
    while value >= 0x80 {
        output.push(((value & 0x7f) as u8) | 0x80);
        value >>= 7;
    }
    output.push(value as u8);
}

fn decode_varint(data: &[u8], offset: &mut usize) -> Option<usize> {
    let first = *data.get(*offset)?;
    *offset += 1;
    if first < 0x80 {
        return Some(first as usize);
    }
    let mut value = (first & 0x7f) as usize;
    let mut shift = 7_u32;
    for _ in 1..10 {
        let byte = *data.get(*offset)?;
        *offset += 1;
        value |= ((byte & 0x7f) as usize).checked_shl(shift)?;
        if byte < 0x80 {
            return Some(value);
        }
        shift += 7;
        if shift >= usize::BITS {
            return None;
        }
    }
    None
}

fn encode_tabular_columns(data: &[u8], delimiter: u8) -> Option<Vec<u8>> {
    let mut columns: Vec<Vec<u8>> = Vec::new();
    let mut row_metadata = Vec::new();
    let mut row_count = 0_usize;
    let mut start = 0_usize;

    while start < data.len() {
        let newline = data[start..]
            .iter()
            .position(|&value| value == b'\n')
            .map(|relative| start + relative);
        let (end, terminated) = newline.map_or((data.len(), false), |end| (end, true));
        let row = &data[start..end];
        let arity = row
            .iter()
            .filter(|&&value| value == delimiter)
            .count()
            .checked_add(1)?;
        encode_varint(
            arity.checked_shl(1)? | usize::from(terminated),
            &mut row_metadata,
        );
        if arity > columns.len() {
            columns.resize_with(arity, Vec::new);
        }
        for (index, field) in row.split(|&value| value == delimiter).enumerate() {
            encode_varint(field.len(), &mut columns[index]);
            columns[index].extend_from_slice(field);
        }
        row_count = row_count.checked_add(1)?;
        if !terminated {
            break;
        }
        start = end.checked_add(1)?;
    }

    let column_bytes = columns
        .iter()
        .try_fold(0_usize, |total, column| total.checked_add(column.len()))?;
    let mut output = Vec::with_capacity(
        row_metadata
            .len()
            .checked_add(column_bytes)?
            .checked_add(columns.len().checked_mul(10)?)?
            .checked_add(30)?,
    );
    encode_varint(row_count, &mut output);
    encode_varint(columns.len(), &mut output);
    encode_varint(row_metadata.len(), &mut output);
    output.extend_from_slice(&row_metadata);
    for column in columns {
        encode_varint(column.len(), &mut output);
        output.extend_from_slice(&column);
    }
    Some(output)
}

fn decode_tabular_columns_into(transformed: &[u8], delimiter: u8, output: &mut [u8]) -> Option<()> {
    let expected_size = output.len();
    let mut offset = 0_usize;
    let row_count = decode_varint(transformed, &mut offset)?;
    let column_count = decode_varint(transformed, &mut offset)?;
    let metadata_size = decode_varint(transformed, &mut offset)?;
    let count_limit = expected_size.checked_add(1)?;
    if row_count > count_limit || column_count > count_limit {
        return None;
    }
    let metadata_end = offset.checked_add(metadata_size)?;
    if metadata_end > transformed.len() {
        return None;
    }
    if row_count > metadata_size {
        return None;
    }

    let mut arities = Vec::with_capacity(row_count);
    let mut terminators = Vec::with_capacity(row_count);
    let mut metadata_offset = offset;
    let mut total_fields = 0_usize;
    let field_limit = expected_size.checked_add(row_count)?.checked_add(1)?;
    for _ in 0..row_count {
        let packed = decode_varint(transformed, &mut metadata_offset)?;
        let arity = packed >> 1;
        if arity == 0 || arity > column_count {
            return None;
        }
        total_fields = total_fields.checked_add(arity)?;
        if total_fields > field_limit {
            return None;
        }
        arities.push(arity);
        terminators.push(packed & 1 != 0);
    }
    if metadata_offset != metadata_end {
        return None;
    }
    offset = metadata_end;

    if column_count > transformed.len().checked_sub(metadata_end)? {
        return None;
    }

    let mut columns = Vec::with_capacity(column_count);
    for _ in 0..column_count {
        let column_size = decode_varint(transformed, &mut offset)?;
        let column_end = offset.checked_add(column_size)?;
        columns.push(transformed.get(offset..column_end)?);
        offset = column_end;
    }
    if offset != transformed.len() {
        return None;
    }

    let mut column_offsets = vec![0_usize; column_count];
    let mut output_offset = 0_usize;
    for (row_index, arity) in arities.into_iter().enumerate() {
        for column_index in 0..arity {
            let column = columns[column_index];
            let field_size = decode_varint(column, &mut column_offsets[column_index])?;
            let field_start = column_offsets[column_index];
            let field_end = field_start.checked_add(field_size)?;
            let field = column.get(field_start..field_end)?;
            if column_index > 0 {
                *output.get_mut(output_offset)? = delimiter;
                output_offset += 1;
            }
            let output_end = output_offset.checked_add(field.len())?;
            output
                .get_mut(output_offset..output_end)?
                .copy_from_slice(field);
            output_offset = output_end;
            column_offsets[column_index] = field_end;
        }
        if terminators[row_index] {
            *output.get_mut(output_offset)? = b'\n';
            output_offset += 1;
        }
    }
    if output_offset != expected_size
        || column_offsets
            .iter()
            .zip(&columns)
            .any(|(&consumed, column)| consumed != column.len())
    {
        return None;
    }
    Some(())
}

fn log_slot(size: usize) -> usize {
    size % LWX2_SLOT_COUNT
}

fn matching_run(record: &[u8], reference: &[u8], offset: usize) -> usize {
    let limit = record.len().min(offset + LWX2_MAX_RUN);
    let mut end = offset;
    while end < limit && record[end] == reference[end] {
        end += 1;
    }
    end - offset
}

fn encode_log_residual(record: &[u8], reference: &[u8], output: &mut Vec<u8>) {
    output.clear();
    output.reserve(record.len() / 4);
    let mut offset = 0;
    while offset < record.len() {
        let matching = matching_run(record, reference, offset);
        if matching >= 2 {
            output.push(0x80 | ((matching - 1) as u8));
            offset += matching;
            continue;
        }

        let literal_start = offset;
        offset += matching.max(1);
        while offset < record.len() && offset - literal_start < LWX2_MAX_RUN {
            let matching = matching_run(record, reference, offset);
            if matching >= 2 {
                break;
            }
            offset += matching.max(1);
        }
        let literal_size = offset - literal_start;
        output.push((literal_size - 1) as u8);
        output.extend(
            record[literal_start..offset]
                .iter()
                .zip(&reference[literal_start..offset])
                .map(|(&actual, &predicted)| actual ^ predicted),
        );
    }
}

#[derive(Default)]
struct LogHistoryEntry {
    length: usize,
    valid: bool,
    record: Vec<u8>,
}

fn log_history() -> Vec<LogHistoryEntry> {
    std::iter::repeat_with(LogHistoryEntry::default)
        .take(LWX2_SLOT_COUNT)
        .collect()
}

fn decode_log_residual(
    transformed: &[u8],
    offset: &mut usize,
    reference: &[u8],
) -> Option<Vec<u8>> {
    let mut output = Vec::with_capacity(reference.len());
    while output.len() < reference.len() {
        let command = *transformed.get(*offset)?;
        *offset += 1;
        let size = ((command & 0x7f) as usize) + 1;
        if size > reference.len() - output.len() {
            return None;
        }
        let start = output.len();
        if command & 0x80 != 0 {
            output.extend_from_slice(&reference[start..start + size]);
            continue;
        }
        let residual = transformed.get(*offset..offset.checked_add(size)?)?;
        output.extend(
            residual
                .iter()
                .zip(&reference[start..start + size])
                .map(|(&value, &predicted)| value ^ predicted),
        );
        *offset += size;
    }
    Some(output)
}

fn encode_log_recent(data: &[u8]) -> Option<Vec<u8>> {
    let mut output = Vec::with_capacity(data.len() / 2 + 8);
    output.extend_from_slice(LWX2_MAGIC);
    output.extend_from_slice(&0_u32.to_be_bytes());
    let mut record_count = 0_u32;
    let mut history = log_history();
    let mut residual = Vec::new();
    let mut offset = 0;
    while offset < data.len() {
        let record_end = data[offset..]
            .iter()
            .position(|&value| value == b'\n')
            .map_or(data.len(), |relative| offset + relative + 1);
        let record = &data[offset..record_end];
        record_count = record_count.checked_add(1)?;
        encode_varint(record.len(), &mut output);
        let slot = log_slot(record.len());
        let use_reference = if record.len() <= LWX2_MAX_RECORD_SIZE {
            let entry = &history[slot];
            if entry.valid && entry.length == record.len() {
                encode_log_residual(record, &entry.record, &mut residual);
                residual.len() < record.len()
            } else {
                false
            }
        } else {
            false
        };
        if use_reference {
            output.push(LWX2_MODE_REFERENCE);
            output.extend_from_slice(&residual);
        } else {
            output.push(LWX2_MODE_RAW);
            output.extend_from_slice(record);
        }
        if record.len() <= LWX2_MAX_RECORD_SIZE {
            let entry = &mut history[slot];
            entry.length = record.len();
            entry.valid = true;
            entry.record.clear();
            entry.record.extend_from_slice(record);
        }
        offset = record_end;
    }
    output[4..8].copy_from_slice(&record_count.to_be_bytes());
    Some(output)
}

fn decode_log_recent(transformed: &[u8], expected_size: usize) -> Option<Vec<u8>> {
    if transformed.get(..4)? != LWX2_MAGIC {
        return None;
    }
    let record_count = u32::from_be_bytes(transformed.get(4..8)?.try_into().ok()?);
    let mut history = log_history();
    let mut output = Vec::with_capacity(expected_size);
    let mut offset = 8;
    for _ in 0..record_count {
        let size = decode_varint(transformed, &mut offset)?;
        if size > expected_size.checked_sub(output.len())? {
            return None;
        }
        let mode = *transformed.get(offset)?;
        offset += 1;
        let slot = log_slot(size);
        let record = if mode == LWX2_MODE_RAW {
            let end = offset.checked_add(size)?;
            let raw = transformed.get(offset..end)?.to_vec();
            offset = end;
            raw
        } else if mode == LWX2_MODE_REFERENCE {
            if size > LWX2_MAX_RECORD_SIZE {
                return None;
            }
            let entry = &history[slot];
            if !entry.valid || entry.length != size {
                return None;
            }
            decode_log_residual(transformed, &mut offset, &entry.record)?
        } else {
            return None;
        };
        output.extend_from_slice(&record);
        if size <= LWX2_MAX_RECORD_SIZE {
            let entry = &mut history[slot];
            entry.length = size;
            entry.valid = true;
            entry.record.clear();
            entry.record.extend_from_slice(&record);
        }
    }
    if offset != transformed.len() || output.len() != expected_size {
        return None;
    }
    Some(output)
}

#[derive(Clone, Copy)]
struct JsonField {
    key_start: usize,
    key_end: usize,
    value_start: usize,
    value_end: usize,
}

fn json_skip_whitespace(data: &[u8], mut offset: usize, limit: usize) -> usize {
    while offset < limit && matches!(data[offset], b' ' | b'\t' | b'\r' | b'\n') {
        offset += 1;
    }
    offset
}

fn json_string_end(data: &[u8], mut offset: usize, limit: usize) -> Option<usize> {
    if offset >= limit || data[offset] != b'"' {
        return None;
    }
    offset += 1;
    while offset < limit {
        let value = data[offset];
        offset += 1;
        if value == b'"' {
            return Some(offset);
        }
        if value == b'\\' {
            if offset >= limit {
                return None;
            }
            offset += 1;
        }
    }
    None
}

fn json_compound_end(data: &[u8], mut offset: usize, limit: usize) -> Option<usize> {
    let closing = if *data.get(offset)? == b'{' {
        b'}'
    } else {
        b']'
    };
    let mut stack = vec![closing];
    offset += 1;
    while offset < limit {
        let value = data[offset];
        if value == b'"' {
            offset = json_string_end(data, offset, limit)?;
            continue;
        }
        if value == b'{' {
            stack.push(b'}');
        } else if value == b'[' {
            stack.push(b']');
        } else if value == b'}' || value == b']' {
            if stack.pop()? != value {
                return None;
            }
            if stack.is_empty() {
                return Some(offset + 1);
            }
        }
        offset += 1;
    }
    None
}

fn valid_json_number(data: &[u8]) -> bool {
    if data.is_empty() {
        return false;
    }
    let mut offset = 0;
    if data[offset] == b'-' {
        offset += 1;
        if offset == data.len() {
            return false;
        }
    }
    if data[offset] == b'0' {
        offset += 1;
    } else if data[offset].is_ascii_digit() && data[offset] != b'0' {
        offset += 1;
        while offset < data.len() && data[offset].is_ascii_digit() {
            offset += 1;
        }
    } else {
        return false;
    }
    if offset < data.len() && data[offset] == b'.' {
        offset += 1;
        let start = offset;
        while offset < data.len() && data[offset].is_ascii_digit() {
            offset += 1;
        }
        if offset == start {
            return false;
        }
    }
    if offset < data.len() && matches!(data[offset], b'e' | b'E') {
        offset += 1;
        if offset < data.len() && matches!(data[offset], b'+' | b'-') {
            offset += 1;
        }
        let start = offset;
        while offset < data.len() && data[offset].is_ascii_digit() {
            offset += 1;
        }
        if offset == start {
            return false;
        }
    }
    offset == data.len()
}

fn json_value_end(data: &[u8], offset: usize, limit: usize) -> Option<usize> {
    let value = *data.get(offset)?;
    if value == b'"' {
        return json_string_end(data, offset, limit);
    }
    if value == b'{' || value == b'[' {
        return json_compound_end(data, offset, limit);
    }
    let mut end = offset;
    while end < limit && !matches!(data[end], b',' | b'}' | b' ' | b'\t' | b'\r' | b'\n') {
        end += 1;
    }
    if end == offset {
        return None;
    }
    let token = &data[offset..end];
    if matches!(token, b"true" | b"false" | b"null") || valid_json_number(token) {
        Some(end)
    } else {
        None
    }
}

fn json_top_level_fields(record: &[u8]) -> Option<Vec<JsonField>> {
    let mut content_limit = record.len();
    if record.ends_with(b"\r\n") {
        content_limit = content_limit.checked_sub(2)?;
    } else if record.ends_with(b"\n") {
        content_limit = content_limit.checked_sub(1)?;
    }
    let mut offset = json_skip_whitespace(record, 0, content_limit);
    if offset >= content_limit || record[offset] != b'{' {
        return None;
    }
    offset += 1;
    let mut fields = Vec::new();
    offset = json_skip_whitespace(record, offset, content_limit);
    if offset < content_limit && record[offset] == b'}' {
        offset += 1;
    } else {
        loop {
            offset = json_skip_whitespace(record, offset, content_limit);
            let key_start = offset;
            let key_end = json_string_end(record, offset, content_limit)?;
            offset = json_skip_whitespace(record, key_end, content_limit);
            if offset >= content_limit || record[offset] != b':' {
                return None;
            }
            offset = json_skip_whitespace(record, offset + 1, content_limit);
            let value_start = offset;
            let value_end = json_value_end(record, value_start, content_limit)?;
            fields.push(JsonField {
                key_start,
                key_end,
                value_start,
                value_end,
            });
            offset = json_skip_whitespace(record, value_end, content_limit);
            if offset >= content_limit {
                return None;
            }
            if record[offset] == b',' {
                offset += 1;
                continue;
            }
            if record[offset] == b'}' {
                offset += 1;
                break;
            }
            return None;
        }
    }
    offset = json_skip_whitespace(record, offset, content_limit);
    if offset == content_limit {
        Some(fields)
    } else {
        None
    }
}

fn append_json_literal(output: &mut Vec<u8>, data: &[u8]) {
    for &value in data {
        output.push(value);
        if value == JCT1_MARKER {
            output.push(JCT1_MARKER_LITERAL);
        }
    }
}

struct JsonColumnTransform {
    skeleton: Vec<u8>,
    channels: Vec<Vec<u8>>,
    record_count: u64,
    extracted_records: u64,
    extracted_values: u64,
}

fn transform_json_columns(data: &[u8]) -> Option<JsonColumnTransform> {
    let mut skeleton = Vec::with_capacity(data.len());
    let mut channels: Vec<Vec<u8>> = Vec::new();
    let mut channel_by_key: HashMap<Vec<u8>, usize> = HashMap::new();
    let mut record_count = 0_u64;
    let mut extracted_records = 0_u64;
    let mut extracted_values = 0_u64;
    let mut offset = 0;
    while offset < data.len() {
        let record_end = data[offset..]
            .iter()
            .position(|&value| value == b'\n')
            .map_or(data.len(), |relative| offset + relative + 1);
        let record = &data[offset..record_end];
        record_count = record_count.checked_add(1)?;
        let mut fields = json_top_level_fields(record);
        if let Some(candidate_fields) = &fields {
            let mut pending: Vec<Vec<u8>> = Vec::new();
            for field in candidate_fields {
                let key = &record[field.key_start..field.key_end];
                if !channel_by_key.contains_key(key)
                    && !pending.iter().any(|stored| stored.as_slice() == key)
                {
                    pending.push(key.to_vec());
                }
            }
            if channel_by_key.len().checked_add(pending.len())? > JCT1_MAX_CHANNELS {
                fields = None;
            } else {
                for key in pending {
                    let channel = channels.len();
                    channel_by_key.insert(key, channel);
                    channels.push(Vec::new());
                }
            }
        }
        if let Some(fields) = fields {
            let mut record_offset = 0;
            for field in fields {
                append_json_literal(&mut skeleton, &record[record_offset..field.value_start]);
                let key = &record[field.key_start..field.key_end];
                let channel = *channel_by_key.get(key)?;
                skeleton.extend_from_slice(&[JCT1_MARKER, JCT1_MARKER_CHANNEL]);
                encode_varint(channel, &mut skeleton);
                let value = &record[field.value_start..field.value_end];
                encode_varint(value.len(), &mut channels[channel]);
                channels[channel].extend_from_slice(value);
                extracted_values = extracted_values.checked_add(1)?;
                record_offset = field.value_end;
            }
            append_json_literal(&mut skeleton, &record[record_offset..]);
            extracted_records = extracted_records.checked_add(1)?;
        } else {
            append_json_literal(&mut skeleton, record);
        }
        offset = record_end;
    }
    Some(JsonColumnTransform {
        skeleton,
        channels,
        record_count,
        extracted_records,
        extracted_values,
    })
}

fn pack_json_column_transform(transformed: JsonColumnTransform) -> Option<Vec<u8>> {
    let channel_count = u32::try_from(transformed.channels.len()).ok()?;
    let skeleton_size = u64::try_from(transformed.skeleton.len()).ok()?;
    let mut output = Vec::with_capacity(
        40_usize
            .checked_add(transformed.channels.len().checked_mul(8)?)?
            .checked_add(transformed.skeleton.len())?
            .checked_add(transformed.channels.iter().map(Vec::len).sum())?,
    );
    output.extend_from_slice(JCT1_MAGIC);
    output.extend_from_slice(&channel_count.to_be_bytes());
    output.extend_from_slice(&skeleton_size.to_be_bytes());
    output.extend_from_slice(&transformed.record_count.to_be_bytes());
    output.extend_from_slice(&transformed.extracted_records.to_be_bytes());
    output.extend_from_slice(&transformed.extracted_values.to_be_bytes());
    for channel in &transformed.channels {
        output.extend_from_slice(&u64::try_from(channel.len()).ok()?.to_be_bytes());
    }
    output.extend_from_slice(&transformed.skeleton);
    for channel in transformed.channels {
        output.extend_from_slice(&channel);
    }
    Some(output)
}

fn encode_json_column_transform(data: &[u8]) -> Option<Vec<u8>> {
    pack_json_column_transform(transform_json_columns(data)?)
}

fn decode_json_column_transform_into(transformed: &[u8], output: &mut [u8]) -> Option<()> {
    if transformed.get(..4)? != JCT1_MAGIC {
        return None;
    }
    let channel_count = u32::from_be_bytes(transformed.get(4..8)?.try_into().ok()?) as usize;
    if channel_count > JCT1_MAX_CHANNELS {
        return None;
    }
    let skeleton_size =
        usize::try_from(u64::from_be_bytes(transformed.get(8..16)?.try_into().ok()?)).ok()?;
    let record_count = u64::from_be_bytes(transformed.get(16..24)?.try_into().ok()?);
    let extracted_records = u64::from_be_bytes(transformed.get(24..32)?.try_into().ok()?);
    let _extracted_values = u64::from_be_bytes(transformed.get(32..40)?.try_into().ok()?);
    if extracted_records > record_count {
        return None;
    }
    let mut offset = 40_usize;
    let mut channel_sizes = Vec::with_capacity(channel_count);
    for _ in 0..channel_count {
        let end = offset.checked_add(8)?;
        channel_sizes.push(
            usize::try_from(u64::from_be_bytes(
                transformed.get(offset..end)?.try_into().ok()?,
            ))
            .ok()?,
        );
        offset = end;
    }
    let skeleton_end = offset.checked_add(skeleton_size)?;
    let skeleton = transformed.get(offset..skeleton_end)?;
    offset = skeleton_end;
    let mut channels = Vec::with_capacity(channel_count);
    for size in channel_sizes {
        let end = offset.checked_add(size)?;
        channels.push(transformed.get(offset..end)?);
        offset = end;
    }
    if offset != transformed.len() {
        return None;
    }

    let mut channel_offsets = vec![0_usize; channel_count];
    let mut output_offset = 0_usize;
    offset = 0;
    while offset < skeleton.len() {
        let value = skeleton[offset];
        offset += 1;
        if value != JCT1_MARKER {
            *output.get_mut(output_offset)? = value;
            output_offset += 1;
            continue;
        }
        let tag = *skeleton.get(offset)?;
        offset += 1;
        if tag == JCT1_MARKER_LITERAL {
            *output.get_mut(output_offset)? = JCT1_MARKER;
            output_offset += 1;
            continue;
        }
        if tag != JCT1_MARKER_CHANNEL {
            return None;
        }
        let channel = decode_varint(skeleton, &mut offset)?;
        let channel_data = *channels.get(channel)?;
        let channel_offset = channel_offsets.get_mut(channel)?;
        let value_size = decode_varint(channel_data, channel_offset)?;
        let value_end = channel_offset.checked_add(value_size)?;
        let value = channel_data.get(*channel_offset..value_end)?;
        let output_end = output_offset.checked_add(value.len())?;
        output
            .get_mut(output_offset..output_end)?
            .copy_from_slice(value);
        output_offset = output_end;
        *channel_offset = value_end;
    }
    if output_offset != output.len()
        || channels
            .iter()
            .zip(channel_offsets)
            .any(|(channel, consumed)| channel.len() != consumed)
    {
        return None;
    }
    Some(())
}

#[cfg(test)]
fn decode_json_column_transform(transformed: &[u8], expected_size: usize) -> Option<Vec<u8>> {
    let mut output = vec![0_u8; expected_size];
    decode_json_column_transform_into(transformed, &mut output)?;
    Some(output)
}

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
        .into_values()
        .flatten()
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
/// Transpose byte-exact delimited rows into independently compressible columns.
///
/// # Safety
///
/// `input`, `output`, and `output_len` must be non-null. The input must be
/// readable for `len` bytes, the output writable for `output_capacity` bytes,
/// and `output_len` writable for one `usize`. Input and output must not alias.
pub unsafe extern "C" fn clab_tabular_transform(
    input: *const u8,
    len: usize,
    delimiter: u8,
    output: *mut u8,
    output_capacity: usize,
    output_len: *mut usize,
) -> i32 {
    if input.is_null() || output.is_null() || output_len.is_null() {
        return NULL_POINTER;
    }
    let source = slice::from_raw_parts(input, len);
    let Some(encoded) = encode_tabular_columns(source, delimiter) else {
        return INVALID_INPUT;
    };
    *output_len = encoded.len();
    if encoded.len() > output_capacity {
        return OUTPUT_TOO_SMALL;
    }
    slice::from_raw_parts_mut(output, output_capacity)[..encoded.len()].copy_from_slice(&encoded);
    OK
}

#[no_mangle]
/// Reassemble a byte-exact tabular column transform.
///
/// # Safety
///
/// `input` and `output` must be non-null and valid for reads of `len` bytes and
/// writes of `expected_size` bytes respectively. The regions must not alias.
pub unsafe extern "C" fn clab_tabular_reassemble(
    input: *const u8,
    len: usize,
    delimiter: u8,
    output: *mut u8,
    expected_size: usize,
) -> i32 {
    if input.is_null() || output.is_null() {
        return NULL_POINTER;
    }
    let source = slice::from_raw_parts(input, len);
    let destination = slice::from_raw_parts_mut(output, expected_size);
    if decode_tabular_columns_into(source, delimiter, destination).is_none() {
        return INVALID_INPUT;
    }
    OK
}

#[no_mangle]
/// Encode bytes with the bounded LWX2 same-length log transform.
///
/// # Safety
///
/// `input`, `output`, and `output_len` must be non-null. The input must be
/// readable for `len` bytes, the output writable for `output_capacity` bytes,
/// and `output_len` writable for one `usize`. Input and output must not alias.
pub unsafe extern "C" fn clab_log_transform_encode(
    input: *const u8,
    len: usize,
    output: *mut u8,
    output_capacity: usize,
    output_len: *mut usize,
) -> i32 {
    if input.is_null() || output.is_null() || output_len.is_null() {
        return NULL_POINTER;
    }
    let source = slice::from_raw_parts(input, len);
    let Some(encoded) = encode_log_recent(source) else {
        return INVALID_INPUT;
    };
    if encoded.len() > output_capacity {
        return OUTPUT_TOO_SMALL;
    }
    slice::from_raw_parts_mut(output, output_capacity)[..encoded.len()].copy_from_slice(&encoded);
    *output_len = encoded.len();
    OK
}

#[no_mangle]
/// Decode a complete LWX2 transform.
///
/// # Safety
///
/// `input` and `output` must be non-null and valid for reads of `len` bytes and
/// writes of `expected_size` bytes respectively. The regions must not alias.
pub unsafe extern "C" fn clab_log_transform_decode(
    input: *const u8,
    len: usize,
    output: *mut u8,
    expected_size: usize,
) -> i32 {
    if input.is_null() || output.is_null() {
        return NULL_POINTER;
    }
    let source = slice::from_raw_parts(input, len);
    let Some(decoded) = decode_log_recent(source, expected_size) else {
        return INVALID_INPUT;
    };
    slice::from_raw_parts_mut(output, expected_size).copy_from_slice(&decoded);
    OK
}

#[no_mangle]
/// Split newline-delimited flat JSON objects into a JCT1 skeleton and channels.
///
/// # Safety
///
/// `input`, `output`, and `output_len` must be non-null. The input must be
/// readable for `len` bytes, the output writable for `output_capacity` bytes,
/// and `output_len` writable for one `usize`. Input and output must not alias.
pub unsafe extern "C" fn clab_json_columnar_transform(
    input: *const u8,
    len: usize,
    output: *mut u8,
    output_capacity: usize,
    output_len: *mut usize,
) -> i32 {
    if input.is_null() || output.is_null() || output_len.is_null() {
        return NULL_POINTER;
    }
    let source = slice::from_raw_parts(input, len);
    let Some(encoded) = encode_json_column_transform(source) else {
        return INVALID_INPUT;
    };
    if encoded.len() > output_capacity {
        return OUTPUT_TOO_SMALL;
    }
    slice::from_raw_parts_mut(output, output_capacity)[..encoded.len()].copy_from_slice(&encoded);
    *output_len = encoded.len();
    OK
}

#[no_mangle]
/// Reassemble a complete JCT1 skeleton and channel transform.
///
/// # Safety
///
/// `input` and `output` must be non-null and valid for reads of `len` bytes and
/// writes of `expected_size` bytes respectively. The regions must not alias.
pub unsafe extern "C" fn clab_json_columnar_reassemble(
    input: *const u8,
    len: usize,
    output: *mut u8,
    expected_size: usize,
) -> i32 {
    if input.is_null() || output.is_null() {
        return NULL_POINTER;
    }
    let source = slice::from_raw_parts(input, len);
    let destination = slice::from_raw_parts_mut(output, expected_size);
    if decode_json_column_transform_into(source, destination).is_none() {
        return INVALID_INPUT;
    }
    OK
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
            assert_eq!(
                clab_log_transform_encode(ptr::null(), 0, ptr::null_mut(), 0, &mut output_len,),
                NULL_POINTER
            );
            assert_eq!(
                clab_log_transform_decode(ptr::null(), 0, ptr::null_mut(), 0),
                NULL_POINTER
            );
            assert_eq!(
                clab_json_columnar_transform(ptr::null(), 0, ptr::null_mut(), 0, &mut output_len,),
                NULL_POINTER
            );
            assert_eq!(
                clab_json_columnar_reassemble(ptr::null(), 0, ptr::null_mut(), 0),
                NULL_POINTER
            );
            assert_eq!(
                clab_tabular_transform(ptr::null(), 0, b',', ptr::null_mut(), 0, &mut output_len,),
                NULL_POINTER
            );
            assert_eq!(
                clab_tabular_reassemble(ptr::null(), 0, b',', ptr::null_mut(), 0),
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
    fn tabular_columns_round_trip_variable_rows_and_binary_fields() {
        let source = b"a,b,c\n1,,3\n\x00,\xff\nlast,row";
        let transformed = encode_tabular_columns(source, b',').unwrap();
        let mut restored = vec![0_u8; source.len()];
        assert_eq!(
            decode_tabular_columns_into(&transformed, b',', &mut restored),
            Some(())
        );
        assert_eq!(restored, source);
        assert_eq!(
            decode_tabular_columns_into(&transformed[..transformed.len() - 1], b',', &mut restored),
            None
        );
        let mut trailing = transformed;
        trailing.push(0);
        assert_eq!(
            decode_tabular_columns_into(&trailing, b',', &mut restored),
            None
        );
        let mut tiny = [0_u8; 1];
        let mut required = 0_usize;
        unsafe {
            assert_eq!(
                clab_tabular_transform(
                    source.as_ptr(),
                    source.len(),
                    b',',
                    tiny.as_mut_ptr(),
                    tiny.len(),
                    &mut required,
                ),
                OUTPUT_TOO_SMALL
            );
        }
        assert_eq!(
            required,
            encode_tabular_columns(source, b',').unwrap().len()
        );
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

    #[test]
    fn recent_log_transform_round_trips_and_rejects_corruption() {
        let mut source = Vec::new();
        for index in 0..10_000 {
            source.extend_from_slice(
                format!(
                    "{{\"event\":\"tick\",\"sequence\":{index:08},\"worker\":{}}}\n",
                    index % 8
                )
                .as_bytes(),
            );
        }
        let transformed = encode_log_recent(&source).unwrap();
        assert!(transformed.len() < source.len());
        assert_eq!(
            decode_log_recent(&transformed, source.len()),
            Some(source.clone())
        );
        assert_eq!(decode_log_recent(&transformed[..7], source.len()), None);
        assert_eq!(
            decode_log_recent(&transformed[..transformed.len() - 1], source.len()),
            None
        );
        let mut trailing = transformed.clone();
        trailing.push(0);
        assert_eq!(decode_log_recent(&trailing, source.len()), None);
    }

    #[test]
    fn json_columnar_transform_round_trips_and_rejects_corruption() {
        let source = b"{\"id\":1,\"event\":\"tick\",\"nested\":{\"ok\":true}}\r\n\
{\"event\":\"tock\",\"id\":2,\"nested\":[1,2,3]}\n\
not-json\xff\n\
{\"id\":3,\"event\":\"final\"}";
        let transformed = encode_json_column_transform(source).unwrap();
        assert_eq!(
            decode_json_column_transform(&transformed, source.len()),
            Some(source.to_vec())
        );
        assert_eq!(
            decode_json_column_transform(&transformed[..39], source.len()),
            None
        );
        assert_eq!(
            decode_json_column_transform(&transformed[..transformed.len() - 1], source.len()),
            None
        );
        let mut trailing = transformed.clone();
        trailing.push(0);
        assert_eq!(decode_json_column_transform(&trailing, source.len()), None);
        let mut invalid_magic = transformed;
        invalid_magic[0] ^= 1;
        assert_eq!(
            decode_json_column_transform(&invalid_magic, source.len()),
            None
        );
    }
}
