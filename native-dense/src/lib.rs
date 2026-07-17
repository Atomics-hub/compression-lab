use std::cmp::Ordering;
use std::collections::{HashMap, HashSet};
use std::slice;

const OK: i32 = 0;
const NULL_POINTER: i32 = 1;
const INVALID_INPUT: i32 = 2;
const OUTPUT_TOO_SMALL: i32 = 3;
const DENSE_SEPARATOR_BYTES: &[u8] = b" \t,;|\r\n";
const DENSE_MAX_DICTIONARY: usize = 1 << 20;
const DENSE_MAX_MODEL_CELLS: usize = 64 * 1024 * 1024;
const DENSE_PARALLEL_LANES: usize = 7;

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

fn dense_is_separator(value: u8) -> bool {
    DENSE_SEPARATOR_BYTES.contains(&value)
}

fn dense_is_numeric(value: &[u8]) -> bool {
    if value.is_empty() {
        return false;
    }
    let mut offset = usize::from(matches!(value[0], b'+' | b'-'));
    if offset == value.len() {
        return false;
    }
    let mut dot_seen = false;
    let mut digit_seen = false;
    while offset < value.len() {
        match value[offset] {
            b'0'..=b'9' => digit_seen = true,
            b'.' if !dot_seen => dot_seen = true,
            _ => return false,
        }
        offset += 1;
    }
    digit_seen
}

#[derive(Clone)]
struct DenseDecimalOwned {
    negative: bool,
    significant: Vec<u8>,
    scale: usize,
}

fn dense_decimal_owned(value: &[u8]) -> DenseDecimalOwned {
    let negative = value.first() == Some(&b'-');
    let unsigned = if matches!(value.first(), Some(b'+') | Some(b'-')) {
        &value[1..]
    } else {
        value
    };
    let dot = unsigned.iter().position(|&byte| byte == b'.');
    let scale = dot.map_or(0, |index| unsigned.len() - index - 1);
    let mut digits: Vec<u8> = unsigned
        .iter()
        .copied()
        .filter(|&byte| byte != b'.')
        .collect();
    let Some(first) = digits.iter().position(|&byte| byte != b'0') else {
        return DenseDecimalOwned {
            negative: false,
            significant: Vec::new(),
            scale: 0,
        };
    };
    digits.drain(..first);
    DenseDecimalOwned {
        negative,
        significant: digits,
        scale,
    }
}

fn dense_decimal_cmp(left: &DenseDecimalOwned, right: &DenseDecimalOwned) -> Ordering {
    if left.significant.is_empty() && right.significant.is_empty() {
        return Ordering::Equal;
    }
    if left.negative != right.negative {
        return if left.negative {
            Ordering::Less
        } else {
            Ordering::Greater
        };
    }
    let left_integer_digits = left.significant.len() as isize - left.scale as isize;
    let right_integer_digits = right.significant.len() as isize - right.scale as isize;
    let mut magnitude = left_integer_digits.cmp(&right_integer_digits);
    if magnitude == Ordering::Equal {
        let width = left.significant.len().max(right.significant.len());
        for index in 0..width {
            let left_digit = left.significant.get(index).copied().unwrap_or(b'0');
            let right_digit = right.significant.get(index).copied().unwrap_or(b'0');
            magnitude = left_digit.cmp(&right_digit);
            if magnitude != Ordering::Equal {
                break;
            }
        }
    }
    if left.negative {
        magnitude.reverse()
    } else {
        magnitude
    }
}

type DenseRuns<'a> = (bool, Vec<&'a [u8]>, Vec<&'a [u8]>);

fn dense_split_runs(data: &[u8]) -> Option<DenseRuns<'_>> {
    if data.is_empty() {
        return Some((true, Vec::new(), Vec::new()));
    }
    let starts_with_token = !dense_is_separator(data[0]);
    let mut tokens = Vec::new();
    let mut separators = Vec::new();
    let mut start = 0;
    let mut is_separator = !starts_with_token;
    for offset in 1..data.len() {
        let next_is_separator = dense_is_separator(data[offset]);
        if next_is_separator == is_separator {
            continue;
        }
        if is_separator {
            separators.push(&data[start..offset]);
        } else {
            tokens.push(&data[start..offset]);
        }
        start = offset;
        is_separator = next_is_separator;
    }
    if is_separator {
        separators.push(&data[start..]);
    } else {
        tokens.push(&data[start..]);
    }
    Some((starts_with_token, tokens, separators))
}

type DenseDictionaries<'a> = (bool, Vec<&'a [u8]>, Vec<&'a [u8]>, usize, usize);

fn dense_insert_unique<'a>(
    small: &mut Vec<&'a [u8]>,
    large: &mut Option<HashSet<&'a [u8]>>,
    value: &'a [u8],
) {
    if let Some(entries) = large {
        entries.insert(value);
    } else if !small.contains(&value) {
        if small.len() < 8 {
            small.push(value);
        } else {
            let mut entries: HashSet<&[u8]> = small.drain(..).collect();
            entries.insert(value);
            *large = Some(entries);
        }
    }
}

fn dense_finish_unique<'a>(
    small: Vec<&'a [u8]>,
    large: Option<HashSet<&'a [u8]>>,
) -> Vec<&'a [u8]> {
    large.map_or(small, |entries| entries.into_iter().collect())
}

fn dense_unique_dictionaries(data: &[u8]) -> Option<DenseDictionaries<'_>> {
    if data.is_empty() {
        return None;
    }
    let starts_with_token = !dense_is_separator(data[0]);
    let mut small_tokens = Vec::new();
    let mut token_set = None;
    let mut small_separators = Vec::new();
    let mut separator_set = None;
    let mut token_count = 0_usize;
    let mut separator_count = 0_usize;
    let mut start = 0_usize;
    let mut is_separator = !starts_with_token;
    for offset in 1..=data.len() {
        let boundary = offset == data.len() || dense_is_separator(data[offset]) != is_separator;
        if !boundary {
            continue;
        }
        let run = &data[start..offset];
        if is_separator {
            dense_insert_unique(&mut small_separators, &mut separator_set, run);
            separator_count = separator_count.checked_add(1)?;
        } else {
            if !dense_is_numeric(run) {
                return None;
            }
            dense_insert_unique(&mut small_tokens, &mut token_set, run);
            token_count = token_count.checked_add(1)?;
        }
        if offset < data.len() {
            start = offset;
            is_separator = !is_separator;
        }
    }
    Some((
        starts_with_token,
        dense_finish_unique(small_tokens, token_set),
        dense_finish_unique(small_separators, separator_set),
        token_count,
        separator_count,
    ))
}

fn dense_map_runs_chunk(
    data: &[u8],
    token_lookup: &HashMap<&[u8], usize>,
    separator_lookup: &HashMap<&[u8], usize>,
    token_capacity: usize,
    separator_capacity: usize,
) -> Option<(Vec<usize>, Vec<usize>)> {
    let starts_with_token = !dense_is_separator(*data.first()?);
    let mut symbols = Vec::with_capacity(token_capacity);
    let mut separator_indices = Vec::with_capacity(separator_capacity);
    let mut start = 0_usize;
    let mut is_separator = !starts_with_token;
    for offset in 1..=data.len() {
        let boundary = offset == data.len() || dense_is_separator(data[offset]) != is_separator;
        if !boundary {
            continue;
        }
        let run = &data[start..offset];
        if is_separator {
            separator_indices.push(separator_lookup.get(run).copied()?);
        } else {
            symbols.push(token_lookup.get(run).copied()?);
        }
        if offset < data.len() {
            start = offset;
            is_separator = !is_separator;
        }
    }
    Some((symbols, separator_indices))
}

#[allow(clippy::too_many_arguments)]
fn dense_map_runs_parallel(
    data: &[u8],
    token_lookup: &HashMap<&[u8], usize>,
    separator_lookup: &HashMap<&[u8], usize>,
    rows: usize,
    columns: usize,
    lane_count: usize,
    token_count: usize,
    separator_count: usize,
) -> Option<(Vec<usize>, Vec<usize>)> {
    let mut row_offsets = Vec::with_capacity(rows.checked_add(1)?);
    row_offsets.push(0);
    row_offsets.extend(
        data.iter()
            .enumerate()
            .filter_map(|(index, &value)| (value == b'\n').then_some(index + 1)),
    );
    if row_offsets.last().copied() != Some(data.len()) {
        row_offsets.push(data.len());
    }
    if row_offsets.len() != rows.checked_add(1)? {
        return None;
    }
    for offset in row_offsets.iter_mut().take(rows).skip(1) {
        while *offset < data.len() && dense_is_separator(data[*offset]) {
            *offset += 1;
        }
    }
    let chunks = std::thread::scope(|scope| {
        let handles: Vec<_> = (0..lane_count)
            .map(|lane| {
                let start_row = rows * lane / lane_count;
                let end_row = rows * (lane + 1) / lane_count;
                let chunk = &data[row_offsets[start_row]..row_offsets[end_row]];
                let chunk_tokens = (end_row - start_row) * columns;
                scope.spawn(move || {
                    dense_map_runs_chunk(
                        chunk,
                        token_lookup,
                        separator_lookup,
                        chunk_tokens,
                        chunk_tokens,
                    )
                })
            })
            .collect();
        handles
            .into_iter()
            .map(|handle| handle.join().ok().flatten())
            .collect::<Option<Vec<_>>>()
    })?;
    let mut symbols = Vec::with_capacity(token_count);
    let mut separator_indices = Vec::with_capacity(separator_count);
    for (chunk_symbols, chunk_separators) in chunks {
        symbols.extend(chunk_symbols);
        separator_indices.extend(chunk_separators);
    }
    (symbols.len() == token_count && separator_indices.len() == separator_count)
        .then_some((symbols, separator_indices))
}

fn dense_matrix_shape(data: &[u8]) -> Option<(usize, usize)> {
    let mut rows = Vec::new();
    let mut row_tokens = 0_usize;
    let mut in_token = false;
    for &value in data {
        if value == b'\n' {
            rows.push(row_tokens);
            row_tokens = 0;
            in_token = false;
        } else if dense_is_separator(value) {
            in_token = false;
        } else if !in_token {
            row_tokens = row_tokens.checked_add(1)?;
            in_token = true;
        }
    }
    if data.last() != Some(&b'\n') {
        rows.push(row_tokens);
    }
    let columns = *rows.first()?;
    if columns == 0 || rows.iter().any(|&count| count != columns) {
        return None;
    }
    Some((rows.len(), columns))
}

fn dense_write_dictionary(output: &mut Vec<u8>, entries: &[&[u8]]) {
    encode_varint(entries.len(), output);
    for entry in entries {
        encode_varint(entry.len(), output);
        output.extend_from_slice(entry);
    }
}

fn dense_read_dictionary(data: &[u8], offset: &mut usize) -> Option<Vec<Vec<u8>>> {
    let count = decode_varint(data, offset)?;
    if count > DENSE_MAX_DICTIONARY {
        return None;
    }
    let mut entries = Vec::with_capacity(count);
    for _ in 0..count {
        let size = decode_varint(data, offset)?;
        let end = offset.checked_add(size)?;
        entries.push(data.get(*offset..end)?.to_vec());
        *offset = end;
    }
    let mut unique = entries.clone();
    unique.sort();
    unique.dedup();
    (unique.len() == entries.len()).then_some(entries)
}

fn dense_bit_width(count: usize) -> usize {
    if count <= 1 {
        0
    } else {
        usize::BITS as usize - (count - 1).leading_zeros() as usize
    }
}

fn dense_pack_indices(indices: &[usize], dictionary_size: usize) -> Option<Vec<u8>> {
    let width = dense_bit_width(dictionary_size);
    if width == 0 {
        return indices.iter().all(|&index| index == 0).then(Vec::new);
    }
    let bit_count = indices.len().checked_mul(width)?;
    let mut output = vec![0_u8; bit_count.checked_add(7)? / 8];
    let mut bit_offset = 0;
    for &index in indices {
        if index >= dictionary_size {
            return None;
        }
        for shift in 0..width {
            if index & (1 << shift) != 0 {
                output[bit_offset >> 3] |= 1 << (bit_offset & 7);
            }
            bit_offset += 1;
        }
    }
    Some(output)
}

fn dense_unpack_indices(data: &[u8], count: usize, dictionary_size: usize) -> Option<Vec<usize>> {
    let width = dense_bit_width(dictionary_size);
    let bit_count = count.checked_mul(width)?;
    if data.len() != bit_count.checked_add(7)? / 8 {
        return None;
    }
    if width == 0 {
        return (count == 0 || dictionary_size == 1).then(|| vec![0; count]);
    }
    let mut output = Vec::with_capacity(count);
    let mut bit_offset = 0;
    for _ in 0..count {
        let mut index = 0;
        for shift in 0..width {
            if data[bit_offset >> 3] & (1 << (bit_offset & 7)) != 0 {
                index |= 1 << shift;
            }
            bit_offset += 1;
        }
        if index >= dictionary_size {
            return None;
        }
        output.push(index);
    }
    if bit_offset & 7 != 0 {
        let mask = !((1_u8 << (bit_offset & 7)) - 1);
        if data.last().copied().unwrap_or(0) & mask != 0 {
            return None;
        }
    }
    Some(output)
}

struct DenseBitWriter {
    output: Vec<u8>,
    current: u8,
    used: u8,
}

impl DenseBitWriter {
    fn new() -> Self {
        Self {
            output: Vec::new(),
            current: 0,
            used: 0,
        }
    }

    fn write(&mut self, bit: u8) {
        self.current = (self.current << 1) | bit;
        self.used += 1;
        if self.used == 8 {
            self.output.push(self.current);
            self.current = 0;
            self.used = 0;
        }
    }

    fn finish(mut self) -> Vec<u8> {
        if self.used != 0 {
            self.output.push(self.current << (8 - self.used));
        }
        self.output
    }
}

struct DenseBitReader<'a> {
    data: &'a [u8],
    offset: usize,
}

impl DenseBitReader<'_> {
    fn read(&mut self) -> u64 {
        let byte_offset = self.offset >> 3;
        let shift = 7 - (self.offset & 7);
        self.offset += 1;
        self.data
            .get(byte_offset)
            .map_or(0, |byte| u64::from((byte >> shift) & 1))
    }
}

fn dense_update_model(counts: &mut [u32], total_after_increment: u32) -> u32 {
    if total_after_increment >= 16_384 {
        for count in counts.iter_mut() {
            *count = (*count).div_ceil(2);
        }
        counts.iter().sum()
    } else {
        total_after_increment
    }
}

fn dense_adaptive_encode(symbols: &[usize], columns: usize, alphabet: usize) -> Option<Vec<u8>> {
    let full = 1_u64 << 32;
    let half = full >> 1;
    let quarter = half >> 1;
    let three_quarters = quarter * 3;
    let mut low = 0_u64;
    let mut high = full - 1;
    let mut pending = 0_usize;
    let mut writer = DenseBitWriter::new();
    let model_cells = columns
        .checked_mul(alphabet.checked_add(1)?)?
        .checked_mul(alphabet)?;
    if model_cells > DENSE_MAX_MODEL_CELLS {
        return None;
    }
    let mut models = vec![1_u32; model_cells];
    let mut totals = vec![alphabet as u32; model_cells / alphabet];
    let sentinel = alphabet;
    let mut previous = sentinel;
    let mut column = 0_usize;

    for &symbol in symbols {
        if column == 0 {
            previous = sentinel;
        }
        let model = column
            .checked_mul(alphabet.checked_add(1)?)?
            .checked_add(previous)?;
        let start = model.checked_mul(alphabet)?;
        let counts = &mut models[start..start + alphabet];
        let cumulative_low: u64 = counts[..symbol].iter().map(|&count| u64::from(count)).sum();
        let cumulative_high = cumulative_low + u64::from(counts[symbol]);
        let total = u64::from(totals[model]);
        let interval = high - low + 1;
        high = low + interval * cumulative_high / total - 1;
        low += interval * cumulative_low / total;
        loop {
            let bit = if high < half {
                Some(0)
            } else if low >= half {
                low -= half;
                high -= half;
                Some(1)
            } else if low >= quarter && high < three_quarters {
                pending += 1;
                low -= quarter;
                high -= quarter;
                None
            } else {
                break;
            };
            if let Some(bit) = bit {
                writer.write(bit);
                while pending != 0 {
                    writer.write(bit ^ 1);
                    pending -= 1;
                }
            }
            low <<= 1;
            high = (high << 1) | 1;
        }
        counts[symbol] = counts[symbol].checked_add(1)?;
        totals[model] = dense_update_model(counts, totals[model].checked_add(1)?);
        previous = symbol;
        column += 1;
        if column == columns {
            column = 0;
        }
    }
    pending += 1;
    let bit = u8::from(low >= quarter);
    writer.write(bit);
    while pending != 0 {
        writer.write(bit ^ 1);
        pending -= 1;
    }
    Some(writer.finish())
}

fn dense_adaptive_decode(
    encoded: &[u8],
    count: usize,
    columns: usize,
    alphabet: usize,
) -> Option<Vec<usize>> {
    let full = 1_u64 << 32;
    let half = full >> 1;
    let quarter = half >> 1;
    let three_quarters = quarter * 3;
    let mut low = 0_u64;
    let mut high = full - 1;
    let mut reader = DenseBitReader {
        data: encoded,
        offset: 0,
    };
    let mut code = 0_u64;
    for _ in 0..32 {
        code = (code << 1) | reader.read();
    }
    let model_cells = columns
        .checked_mul(alphabet.checked_add(1)?)?
        .checked_mul(alphabet)?;
    if model_cells > DENSE_MAX_MODEL_CELLS {
        return None;
    }
    let mut models = vec![1_u32; model_cells];
    let mut totals = vec![alphabet as u32; model_cells / alphabet];
    let mut output = Vec::with_capacity(count);
    let sentinel = alphabet;
    let mut previous = sentinel;
    let mut column = 0_usize;
    for _ in 0..count {
        if column == 0 {
            previous = sentinel;
        }
        let model = column
            .checked_mul(alphabet.checked_add(1)?)?
            .checked_add(previous)?;
        let start = model.checked_mul(alphabet)?;
        let counts = &mut models[start..start + alphabet];
        let total = u64::from(totals[model]);
        let interval = high - low + 1;
        let scaled = ((code - low + 1) * total - 1) / interval;
        let mut cumulative = 0_u64;
        let symbol = counts.iter().position(|&frequency| {
            if cumulative + u64::from(frequency) > scaled {
                true
            } else {
                cumulative += u64::from(frequency);
                false
            }
        })?;
        high = low + interval * (cumulative + u64::from(counts[symbol])) / total - 1;
        low += interval * cumulative / total;
        loop {
            if high < half {
            } else if low >= half {
                low -= half;
                high -= half;
                code -= half;
            } else if low >= quarter && high < three_quarters {
                low -= quarter;
                high -= quarter;
                code -= quarter;
            } else {
                break;
            }
            low <<= 1;
            high = (high << 1) | 1;
            code = (code << 1) | reader.read();
        }
        output.push(symbol);
        counts[symbol] = counts[symbol].checked_add(1)?;
        totals[model] = dense_update_model(counts, totals[model].checked_add(1)?);
        previous = symbol;
        column += 1;
        if column == columns {
            column = 0;
        }
    }
    Some(output)
}

fn encode_dense_adaptive(data: &[u8]) -> Option<(bool, Vec<u8>)> {
    let (starts_with_token, tokens, separators) = dense_split_runs(data)?;
    if tokens.is_empty() || tokens.iter().any(|token| !dense_is_numeric(token)) {
        return None;
    }
    let (rows, columns) = dense_matrix_shape(data)?;
    if tokens.len() != rows.checked_mul(columns)? {
        return None;
    }
    let mut token_dictionary = tokens.clone();
    token_dictionary.sort();
    token_dictionary.dedup();
    token_dictionary.sort_by(|left, right| {
        dense_decimal_cmp(&dense_decimal_owned(left), &dense_decimal_owned(right))
            .then_with(|| left.cmp(right))
    });
    let mut separator_dictionary = separators.clone();
    separator_dictionary.sort();
    separator_dictionary.dedup();
    if token_dictionary.len() > DENSE_MAX_DICTIONARY
        || separator_dictionary.len() > DENSE_MAX_DICTIONARY
    {
        return None;
    }
    if token_dictionary.len() > DENSE_MAX_DICTIONARY
        || separator_dictionary.len() > DENSE_MAX_DICTIONARY
    {
        return None;
    }
    let token_lookup: HashMap<&[u8], usize> = token_dictionary
        .iter()
        .enumerate()
        .map(|(index, &token)| (token, index))
        .collect();
    let separator_lookup: HashMap<&[u8], usize> = separator_dictionary
        .iter()
        .enumerate()
        .map(|(index, &separator)| (separator, index))
        .collect();
    let symbols: Vec<usize> = tokens
        .iter()
        .map(|token| token_lookup.get(token).copied())
        .collect::<Option<_>>()?;
    let arithmetic = dense_adaptive_encode(&symbols, columns, token_dictionary.len())?;
    let separator_indices: Vec<usize> = separators
        .iter()
        .map(|separator| separator_lookup.get(separator).copied())
        .collect::<Option<_>>()?;
    let packed_separators = dense_pack_indices(&separator_indices, separator_dictionary.len())?;
    let mut output = Vec::new();
    dense_write_dictionary(&mut output, &token_dictionary);
    dense_write_dictionary(&mut output, &separator_dictionary);
    encode_varint(rows, &mut output);
    encode_varint(columns, &mut output);
    encode_varint(separators.len(), &mut output);
    encode_varint(arithmetic.len(), &mut output);
    output.extend_from_slice(&arithmetic);
    encode_varint(packed_separators.len(), &mut output);
    output.extend_from_slice(&packed_separators);
    Some((starts_with_token, output))
}

fn decode_dense_adaptive(
    transformed: &[u8],
    starts_with_token: bool,
    expected_size: usize,
) -> Option<Vec<u8>> {
    let mut offset = 0_usize;
    let token_dictionary = dense_read_dictionary(transformed, &mut offset)?;
    let separator_dictionary = dense_read_dictionary(transformed, &mut offset)?;
    if token_dictionary.is_empty() {
        return None;
    }
    if token_dictionary.is_empty() {
        return None;
    }
    let rows = decode_varint(transformed, &mut offset)?;
    let columns = decode_varint(transformed, &mut offset)?;
    let separator_count = decode_varint(transformed, &mut offset)?;
    let token_count = rows.checked_mul(columns)?;
    if rows == 0
        || columns == 0
        || token_count > expected_size.checked_add(1)?
        || separator_count > expected_size.checked_add(1)?
        || token_count.abs_diff(separator_count) > 1
    {
        return None;
    }
    let arithmetic_size = decode_varint(transformed, &mut offset)?;
    let arithmetic_end = offset.checked_add(arithmetic_size)?;
    let arithmetic = transformed.get(offset..arithmetic_end)?;
    offset = arithmetic_end;
    let symbols = dense_adaptive_decode(arithmetic, token_count, columns, token_dictionary.len())?;
    let separator_size = decode_varint(transformed, &mut offset)?;
    let separator_end = offset.checked_add(separator_size)?;
    if separator_end != transformed.len() {
        return None;
    }
    let separator_indices = dense_unpack_indices(
        &transformed[offset..separator_end],
        separator_count,
        separator_dictionary.len(),
    )?;
    let mut output = Vec::with_capacity(expected_size);
    let mut token_offset = 0;
    let mut separator_offset = 0;
    let mut is_token = starts_with_token;
    for _ in 0..token_count.checked_add(separator_count)? {
        let value = if is_token {
            let symbol = *symbols.get(token_offset)?;
            token_offset += 1;
            token_dictionary.get(symbol)?
        } else {
            let symbol = *separator_indices.get(separator_offset)?;
            separator_offset += 1;
            separator_dictionary.get(symbol)?
        };
        if value.len() > expected_size.saturating_sub(output.len()) {
            return None;
        }
        output.extend_from_slice(value);
        is_token = !is_token;
    }
    (output.len() == expected_size
        && token_offset == token_count
        && separator_offset == separator_count)
        .then_some(output)
}

fn encode_dense_parallel(data: &[u8]) -> Option<(bool, Vec<u8>)> {
    let (
        starts_with_token,
        mut token_dictionary,
        mut separator_dictionary,
        token_count,
        separator_count,
    ) = dense_unique_dictionaries(data)?;
    let (rows, columns) = dense_matrix_shape(data)?;
    if token_count != rows.checked_mul(columns)? {
        return None;
    }
    token_dictionary.sort_by(|left, right| {
        dense_decimal_cmp(&dense_decimal_owned(left), &dense_decimal_owned(right))
            .then_with(|| left.cmp(right))
    });
    separator_dictionary.sort();
    if token_dictionary.len() > DENSE_MAX_DICTIONARY
        || separator_dictionary.len() > DENSE_MAX_DICTIONARY
    {
        return None;
    }
    let token_lookup: HashMap<&[u8], usize> = token_dictionary
        .iter()
        .enumerate()
        .map(|(index, &token)| (token, index))
        .collect();
    let separator_lookup: HashMap<&[u8], usize> = separator_dictionary
        .iter()
        .enumerate()
        .map(|(index, &separator)| (separator, index))
        .collect();
    let requested_lanes = if token_dictionary.len() <= 8 { 7 } else { 6 };
    let lane_count = rows.min(requested_lanes);
    let (symbols, separator_indices) = dense_map_runs_parallel(
        data,
        &token_lookup,
        &separator_lookup,
        rows,
        columns,
        lane_count,
        token_count,
        separator_count,
    )?;
    let alphabet = token_dictionary.len();
    let streams = std::thread::scope(|scope| {
        let handles: Vec<_> = (0..lane_count)
            .map(|lane| {
                let start = (rows * lane / lane_count) * columns;
                let end = (rows * (lane + 1) / lane_count) * columns;
                let lane_symbols = &symbols[start..end];
                scope.spawn(move || dense_adaptive_encode(lane_symbols, columns, alphabet))
            })
            .collect();
        handles
            .into_iter()
            .map(|handle| handle.join().ok().flatten())
            .collect::<Option<Vec<_>>>()
    })?;
    let packed_separators = dense_pack_indices(&separator_indices, separator_dictionary.len())?;
    let mut output = Vec::new();
    dense_write_dictionary(&mut output, &token_dictionary);
    dense_write_dictionary(&mut output, &separator_dictionary);
    encode_varint(rows, &mut output);
    encode_varint(columns, &mut output);
    encode_varint(separator_count, &mut output);
    encode_varint(lane_count, &mut output);
    for stream in streams {
        encode_varint(stream.len(), &mut output);
        output.extend_from_slice(&stream);
    }
    encode_varint(packed_separators.len(), &mut output);
    output.extend_from_slice(&packed_separators);
    Some((starts_with_token, output))
}

fn decode_dense_parallel(
    transformed: &[u8],
    starts_with_token: bool,
    expected_size: usize,
) -> Option<Vec<u8>> {
    let mut offset = 0_usize;
    let token_dictionary = dense_read_dictionary(transformed, &mut offset)?;
    let separator_dictionary = dense_read_dictionary(transformed, &mut offset)?;
    if token_dictionary.is_empty() {
        return None;
    }
    let rows = decode_varint(transformed, &mut offset)?;
    let columns = decode_varint(transformed, &mut offset)?;
    let separator_count = decode_varint(transformed, &mut offset)?;
    let token_count = rows.checked_mul(columns)?;
    if rows == 0
        || columns == 0
        || token_count > expected_size.checked_add(1)?
        || separator_count > expected_size.checked_add(1)?
        || token_count.abs_diff(separator_count) > 1
    {
        return None;
    }
    let lane_count = decode_varint(transformed, &mut offset)?;
    if lane_count == 0 || lane_count > DENSE_PARALLEL_LANES || lane_count > rows {
        return None;
    }
    let mut streams = Vec::with_capacity(lane_count);
    for _ in 0..lane_count {
        let size = decode_varint(transformed, &mut offset)?;
        let end = offset.checked_add(size)?;
        streams.push(transformed.get(offset..end)?);
        offset = end;
    }
    let separator_size = decode_varint(transformed, &mut offset)?;
    let separator_end = offset.checked_add(separator_size)?;
    if separator_end != transformed.len() {
        return None;
    }
    let separator_indices = dense_unpack_indices(
        &transformed[offset..separator_end],
        separator_count,
        separator_dictionary.len(),
    )?;
    let alphabet = token_dictionary.len();
    let lane_symbols = std::thread::scope(|scope| {
        let handles: Vec<_> = streams
            .iter()
            .enumerate()
            .map(|(lane, &stream)| {
                let start_row = rows * lane / lane_count;
                let end_row = rows * (lane + 1) / lane_count;
                let count = (end_row - start_row) * columns;
                scope.spawn(move || dense_adaptive_decode(stream, count, columns, alphabet))
            })
            .collect();
        handles
            .into_iter()
            .map(|handle| handle.join().ok().flatten())
            .collect::<Option<Vec<_>>>()
    })?;
    if lane_symbols.iter().map(Vec::len).sum::<usize>() != token_count {
        return None;
    }
    let token_dictionary_ref = &token_dictionary;
    let separator_dictionary_ref = &separator_dictionary;
    let separator_indices_ref = &separator_indices;
    let chunks = std::thread::scope(|scope| {
        let handles: Vec<_> = lane_symbols
            .iter()
            .enumerate()
            .map(|(lane, symbols)| {
                let start_token = (rows * lane / lane_count) * columns;
                scope.spawn(move || {
                    let mut chunk = Vec::with_capacity(expected_size / lane_count + 1024);
                    for (relative, &symbol) in symbols.iter().enumerate() {
                        let token_index = start_token + relative;
                        let token = token_dictionary_ref.get(symbol)?;
                        let separator = separator_indices_ref
                            .get(token_index)
                            .and_then(|&index| separator_dictionary_ref.get(index));
                        if starts_with_token {
                            chunk.extend_from_slice(token);
                            if let Some(separator) = separator {
                                chunk.extend_from_slice(separator);
                            }
                        } else {
                            chunk.extend_from_slice(separator?);
                            chunk.extend_from_slice(token);
                        }
                    }
                    Some(chunk)
                })
            })
            .collect();
        handles
            .into_iter()
            .map(|handle| handle.join().ok().flatten())
            .collect::<Option<Vec<_>>>()
    })?;
    let mut output = Vec::with_capacity(expected_size);
    for chunk in chunks {
        output.extend_from_slice(&chunk);
    }
    if !starts_with_token && separator_count == token_count.checked_add(1)? {
        output.extend_from_slice(separator_dictionary.get(*separator_indices.last()?)?);
    }
    (output.len() == expected_size).then_some(output)
}

fn encode_dense_planes(data: &[u8]) -> Option<(bool, Vec<u8>)> {
    let (
        starts_with_token,
        mut token_dictionary,
        mut separator_dictionary,
        token_count,
        separator_count,
    ) = dense_unique_dictionaries(data)?;
    let (rows, columns) = dense_matrix_shape(data)?;
    token_dictionary.sort_by(|left, right| {
        dense_decimal_cmp(&dense_decimal_owned(left), &dense_decimal_owned(right))
            .then_with(|| left.cmp(right))
    });
    separator_dictionary.sort();
    if token_dictionary.len() > DENSE_MAX_DICTIONARY
        || separator_dictionary.len() > DENSE_MAX_DICTIONARY
    {
        return None;
    }
    let token_lookup: HashMap<&[u8], usize> = token_dictionary
        .iter()
        .enumerate()
        .map(|(index, &token)| (token, index))
        .collect();
    let separator_lookup: HashMap<&[u8], usize> = separator_dictionary
        .iter()
        .enumerate()
        .map(|(index, &separator)| (separator, index))
        .collect();
    let lane_count = rows.min(DENSE_PARALLEL_LANES);
    let (symbols, separator_indices) = dense_map_runs_parallel(
        data,
        &token_lookup,
        &separator_lookup,
        rows,
        columns,
        lane_count,
        token_count,
        separator_count,
    )?;
    let width = dense_bit_width(token_dictionary.len());
    let bytes_per_plane = token_count.checked_add(7)? / 8;
    let mut planes = vec![0_u8; bytes_per_plane.checked_mul(width)?];
    for (index, &symbol) in symbols.iter().enumerate() {
        for bit in 0..width {
            if symbol & (1 << bit) != 0 {
                planes[bit * bytes_per_plane + (index >> 3)] |= 1 << (index & 7);
            }
        }
    }
    let packed_separators = dense_pack_indices(&separator_indices, separator_dictionary.len())?;
    let mut output = Vec::new();
    dense_write_dictionary(&mut output, &token_dictionary);
    dense_write_dictionary(&mut output, &separator_dictionary);
    encode_varint(token_count, &mut output);
    encode_varint(separator_count, &mut output);
    encode_varint(planes.len(), &mut output);
    output.extend_from_slice(&planes);
    encode_varint(packed_separators.len(), &mut output);
    output.extend_from_slice(&packed_separators);
    Some((starts_with_token, output))
}

fn dense_sample_numeric_alphabet(data: &[u8], sample_size: usize) -> Option<usize> {
    let sample = data.get(..data.len().min(sample_size))?;
    if sample.is_empty() {
        return None;
    }
    let starts_with_token = !dense_is_separator(sample[0]);
    let mut entries: Vec<&[u8]> = Vec::new();
    let mut start = 0_usize;
    let mut is_separator = !starts_with_token;
    for offset in 1..=sample.len() {
        let boundary = offset == sample.len() || dense_is_separator(sample[offset]) != is_separator;
        if !boundary {
            continue;
        }
        if !is_separator {
            let token = &sample[start..offset];
            if !dense_is_numeric(token) {
                return None;
            }
            if !entries.contains(&token) {
                entries.push(token);
                if entries.len() > 4 {
                    return Some(entries.len());
                }
            }
        }
        if offset < sample.len() {
            start = offset;
            is_separator = !is_separator;
        }
    }
    Some(entries.len())
}

fn decode_dense_planes(
    transformed: &[u8],
    starts_with_token: bool,
    expected_size: usize,
) -> Option<Vec<u8>> {
    let mut offset = 0_usize;
    let token_dictionary = dense_read_dictionary(transformed, &mut offset)?;
    let separator_dictionary = dense_read_dictionary(transformed, &mut offset)?;
    let token_count = decode_varint(transformed, &mut offset)?;
    let separator_count = decode_varint(transformed, &mut offset)?;
    if token_count.checked_add(separator_count)? > expected_size.checked_add(1)?
        || token_count.abs_diff(separator_count) > 1
    {
        return None;
    }
    let width = dense_bit_width(token_dictionary.len());
    let bytes_per_plane = token_count.checked_add(7)? / 8;
    let expected_plane_size = bytes_per_plane.checked_mul(width)?;
    let plane_size = decode_varint(transformed, &mut offset)?;
    if plane_size != expected_plane_size {
        return None;
    }
    let plane_end = offset.checked_add(plane_size)?;
    let planes = transformed.get(offset..plane_end)?;
    let mut token_indices = vec![0_usize; token_count];
    for bit in 0..width {
        let plane = &planes[bit * bytes_per_plane..(bit + 1) * bytes_per_plane];
        for (index, symbol) in token_indices.iter_mut().enumerate() {
            *symbol |= usize::from((plane[index >> 3] >> (index & 7)) & 1) << bit;
        }
        if token_count & 7 != 0 {
            let mask = !((1_u8 << (token_count & 7)) - 1);
            if plane.last().copied().unwrap_or(0) & mask != 0 {
                return None;
            }
        }
    }
    if token_indices
        .iter()
        .any(|&index| index >= token_dictionary.len())
    {
        return None;
    }
    offset = plane_end;
    let separator_size = decode_varint(transformed, &mut offset)?;
    let separator_end = offset.checked_add(separator_size)?;
    if separator_end != transformed.len() {
        return None;
    }
    let separator_indices = dense_unpack_indices(
        &transformed[offset..separator_end],
        separator_count,
        separator_dictionary.len(),
    )?;
    let mut output = Vec::with_capacity(expected_size);
    let mut token_offset = 0;
    let mut separator_offset = 0;
    let mut is_token = starts_with_token;
    for _ in 0..token_count.checked_add(separator_count)? {
        let value = if is_token {
            let symbol = *token_indices.get(token_offset)?;
            token_offset += 1;
            token_dictionary.get(symbol)?
        } else {
            let symbol = *separator_indices.get(separator_offset)?;
            separator_offset += 1;
            separator_dictionary.get(symbol)?
        };
        if value.len() > expected_size.saturating_sub(output.len()) {
            return None;
        }
        output.extend_from_slice(value);
        is_token = !is_token;
    }
    (output.len() == expected_size).then_some(output)
}

#[no_mangle]
/// Encode a rectangular numeric matrix with the DMA1 adaptive transform.
///
/// # Safety
///
/// All pointers must be non-null and valid for their declared lengths. Input
/// and output must not alias.
pub unsafe extern "C" fn clab_dense_adaptive_transform(
    input: *const u8,
    len: usize,
    output: *mut u8,
    output_capacity: usize,
    output_len: *mut usize,
    starts_with_token: *mut u8,
) -> i32 {
    if input.is_null() || output.is_null() || output_len.is_null() || starts_with_token.is_null() {
        return NULL_POINTER;
    }
    let source = slice::from_raw_parts(input, len);
    let Some((starts, encoded)) = encode_dense_adaptive(source) else {
        return INVALID_INPUT;
    };
    *output_len = encoded.len();
    *starts_with_token = u8::from(starts);
    if encoded.len() > output_capacity {
        return OUTPUT_TOO_SMALL;
    }
    slice::from_raw_parts_mut(output, output_capacity)[..encoded.len()].copy_from_slice(&encoded);
    OK
}

#[no_mangle]
/// Reassemble a DMA1 adaptive transform into the original matrix bytes.
///
/// # Safety
///
/// Input and output must be non-null and valid for their declared lengths and
/// must not alias.
pub unsafe extern "C" fn clab_dense_adaptive_reassemble(
    input: *const u8,
    len: usize,
    starts_with_token: u8,
    output: *mut u8,
    expected_size: usize,
) -> i32 {
    if input.is_null() || output.is_null() || starts_with_token > 1 {
        return NULL_POINTER;
    }
    let source = slice::from_raw_parts(input, len);
    let Some(decoded) = decode_dense_adaptive(source, starts_with_token != 0, expected_size) else {
        return INVALID_INPUT;
    };
    slice::from_raw_parts_mut(output, expected_size).copy_from_slice(&decoded);
    OK
}

#[no_mangle]
/// Encode a numeric matrix as six independent adaptive arithmetic lanes.
///
/// # Safety
///
/// All pointers must be non-null and valid for their declared lengths. Input
/// and output must not alias.
pub unsafe extern "C" fn clab_dense_parallel_transform(
    input: *const u8,
    len: usize,
    output: *mut u8,
    output_capacity: usize,
    output_len: *mut usize,
    starts_with_token: *mut u8,
) -> i32 {
    if input.is_null() || output.is_null() || output_len.is_null() || starts_with_token.is_null() {
        return NULL_POINTER;
    }
    let source = slice::from_raw_parts(input, len);
    let Some((starts, encoded)) = encode_dense_parallel(source) else {
        return INVALID_INPUT;
    };
    *output_len = encoded.len();
    *starts_with_token = u8::from(starts);
    if encoded.len() > output_capacity {
        return OUTPUT_TOO_SMALL;
    }
    slice::from_raw_parts_mut(output, output_capacity)[..encoded.len()].copy_from_slice(&encoded);
    OK
}

#[no_mangle]
/// Reassemble a six-lane adaptive matrix transform.
///
/// # Safety
///
/// Input and output must be non-null and valid for their declared lengths and
/// must not alias.
pub unsafe extern "C" fn clab_dense_parallel_reassemble(
    input: *const u8,
    len: usize,
    starts_with_token: u8,
    output: *mut u8,
    expected_size: usize,
) -> i32 {
    if input.is_null() || output.is_null() || starts_with_token > 1 {
        return NULL_POINTER;
    }
    let source = slice::from_raw_parts(input, len);
    let Some(decoded) = decode_dense_parallel(source, starts_with_token != 0, expected_size) else {
        return INVALID_INPUT;
    };
    slice::from_raw_parts_mut(output, expected_size).copy_from_slice(&decoded);
    OK
}

#[no_mangle]
/// Encode numeric token IDs as row-major bit planes.
///
/// # Safety
///
/// All pointers must be non-null and valid for their declared lengths. Input
/// and output must not alias.
pub unsafe extern "C" fn clab_dense_plane_transform(
    input: *const u8,
    len: usize,
    output: *mut u8,
    output_capacity: usize,
    output_len: *mut usize,
    starts_with_token: *mut u8,
) -> i32 {
    if input.is_null() || output.is_null() || output_len.is_null() || starts_with_token.is_null() {
        return NULL_POINTER;
    }
    let source = slice::from_raw_parts(input, len);
    let Some((starts, encoded)) = encode_dense_planes(source) else {
        return INVALID_INPUT;
    };
    *output_len = encoded.len();
    *starts_with_token = u8::from(starts);
    if encoded.len() > output_capacity {
        return OUTPUT_TOO_SMALL;
    }
    slice::from_raw_parts_mut(output, output_capacity)[..encoded.len()].copy_from_slice(&encoded);
    OK
}

#[no_mangle]
/// Reassemble a row-major numeric bit-plane transform.
///
/// # Safety
///
/// Input and output must be non-null and valid for their declared lengths and
/// must not alias.
pub unsafe extern "C" fn clab_dense_plane_reassemble(
    input: *const u8,
    len: usize,
    starts_with_token: u8,
    output: *mut u8,
    expected_size: usize,
) -> i32 {
    if input.is_null() || output.is_null() || starts_with_token > 1 {
        return NULL_POINTER;
    }
    let source = slice::from_raw_parts(input, len);
    let Some(decoded) = decode_dense_planes(source, starts_with_token != 0, expected_size) else {
        return INVALID_INPUT;
    };
    slice::from_raw_parts_mut(output, expected_size).copy_from_slice(&decoded);
    OK
}

#[no_mangle]
/// Count up to five unique numeric lexemes in a bounded prefix.
///
/// # Safety
///
/// Input and output pointers must be non-null and valid for their declared
/// lengths.
pub unsafe extern "C" fn clab_dense_sample_alphabet(
    input: *const u8,
    len: usize,
    sample_size: usize,
    alphabet_size: *mut usize,
) -> i32 {
    if input.is_null() || alphabet_size.is_null() || sample_size == 0 {
        return NULL_POINTER;
    }
    let source = slice::from_raw_parts(input, len);
    let Some(size) = dense_sample_numeric_alphabet(source, sample_size) else {
        return INVALID_INPUT;
    };
    *alphabet_size = size;
    OK
}
