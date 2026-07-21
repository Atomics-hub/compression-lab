use std::error::Error;
use std::fmt::{Display, Formatter};

const MAX_RECORD_BYTES: usize = 1_048_576;
const MAX_DEPTH: usize = 32;
const MAX_FIELDS: usize = 256;
const MARKER: u8 = 0xff;
const PLACEHOLDER: u8 = 0x00;
const ESCAPED_MARKER: u8 = 0xfe;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Record<'a> {
    pub content: &'a [u8],
    pub terminated: bool,
}

#[must_use]
pub fn split_records(data: &[u8]) -> Vec<Record<'_>> {
    let mut records = Vec::new();
    let mut start = 0_usize;
    while start < data.len() {
        if let Some(relative) = data[start..].iter().position(|&byte| byte == b'\n') {
            let end = start + relative;
            records.push(Record {
                content: &data[start..end],
                terminated: true,
            });
            start = end + 1;
        } else {
            records.push(Record {
                content: &data[start..],
                terminated: false,
            });
            break;
        }
    }
    records
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct JsonLayout {
    skeleton: Vec<u8>,
    values: Vec<Vec<u8>>,
}

impl JsonLayout {
    pub fn parse(record: &[u8]) -> Result<Self, JsonLayoutError> {
        if record.len() > MAX_RECORD_BYTES {
            return Err(JsonLayoutError::RecordTooLarge);
        }
        std::str::from_utf8(record).map_err(|_| JsonLayoutError::InvalidUtf8)?;
        let fields = parse_top_level_object(record)?;
        let mut skeleton = Vec::with_capacity(record.len());
        let mut values = Vec::with_capacity(fields.len());
        let mut copied = 0_usize;
        for (start, end) in fields {
            append_skeleton_literal(&mut skeleton, &record[copied..start]);
            skeleton.extend_from_slice(&[MARKER, PLACEHOLDER]);
            values.push(record[start..end].to_vec());
            copied = end;
        }
        append_skeleton_literal(&mut skeleton, &record[copied..]);
        let layout = Self { skeleton, values };
        debug_assert_eq!(layout.reconstruct().as_deref(), Ok(record));
        Ok(layout)
    }

    #[must_use]
    pub fn skeleton(&self) -> &[u8] {
        &self.skeleton
    }

    #[must_use]
    pub fn values(&self) -> &[Vec<u8>] {
        &self.values
    }

    pub fn reconstruct(&self) -> Result<Vec<u8>, JsonLayoutError> {
        reconstruct(&self.skeleton, &self.values)
    }

    pub fn reconstruct_from(
        skeleton: &[u8],
        values: &[Vec<u8>],
    ) -> Result<Vec<u8>, JsonLayoutError> {
        reconstruct(skeleton, values)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum JsonLayoutError {
    RecordTooLarge,
    InvalidUtf8,
    InvalidJson,
    TooDeep,
    TooManyFields,
    InvalidSkeleton,
    PlaceholderMismatch,
    Overflow,
}

impl Display for JsonLayoutError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "S0 JSON layout error: {self:?}")
    }
}

impl Error for JsonLayoutError {}

fn reconstruct(skeleton: &[u8], values: &[Vec<u8>]) -> Result<Vec<u8>, JsonLayoutError> {
    let value_bytes = values.iter().try_fold(0_usize, |total, value| {
        total
            .checked_add(value.len())
            .ok_or(JsonLayoutError::Overflow)
    })?;
    let mut output = Vec::with_capacity(
        skeleton
            .len()
            .checked_add(value_bytes)
            .ok_or(JsonLayoutError::Overflow)?,
    );
    let mut offset = 0_usize;
    let mut value_index = 0_usize;
    while offset < skeleton.len() {
        if skeleton[offset] != MARKER {
            output.push(skeleton[offset]);
            offset += 1;
            continue;
        }
        let kind = *skeleton
            .get(offset + 1)
            .ok_or(JsonLayoutError::InvalidSkeleton)?;
        match kind {
            PLACEHOLDER => {
                let value = values
                    .get(value_index)
                    .ok_or(JsonLayoutError::PlaceholderMismatch)?;
                output.extend_from_slice(value);
                value_index += 1;
            }
            ESCAPED_MARKER => output.push(MARKER),
            _ => return Err(JsonLayoutError::InvalidSkeleton),
        }
        offset += 2;
    }
    if value_index != values.len() {
        return Err(JsonLayoutError::PlaceholderMismatch);
    }
    Ok(output)
}

fn append_skeleton_literal(output: &mut Vec<u8>, bytes: &[u8]) {
    for &byte in bytes {
        output.push(byte);
        if byte == MARKER {
            output.push(ESCAPED_MARKER);
        }
    }
}

fn parse_top_level_object(data: &[u8]) -> Result<Vec<(usize, usize)>, JsonLayoutError> {
    let mut offset = skip_whitespace(data, 0);
    if data.get(offset) != Some(&b'{') {
        return Err(JsonLayoutError::InvalidJson);
    }
    offset += 1;
    let mut fields = Vec::new();
    let mut total_fields = 0_usize;
    offset = skip_whitespace(data, offset);
    if data.get(offset) == Some(&b'}') {
        offset += 1;
    } else {
        loop {
            offset = skip_whitespace(data, offset);
            offset = parse_string(data, offset)?;
            offset = skip_whitespace(data, offset);
            if data.get(offset) != Some(&b':') {
                return Err(JsonLayoutError::InvalidJson);
            }
            add_field(&mut total_fields)?;
            offset = skip_whitespace(data, offset + 1);
            let value_start = offset;
            offset = parse_value(data, offset, 1, &mut total_fields)?;
            fields.push((value_start, offset));
            offset = skip_whitespace(data, offset);
            match data.get(offset) {
                Some(b',') => offset += 1,
                Some(b'}') => {
                    offset += 1;
                    break;
                }
                _ => return Err(JsonLayoutError::InvalidJson),
            }
        }
    }
    if skip_whitespace(data, offset) != data.len() {
        return Err(JsonLayoutError::InvalidJson);
    }
    Ok(fields)
}

fn parse_value(
    data: &[u8],
    offset: usize,
    parent_depth: usize,
    total_fields: &mut usize,
) -> Result<usize, JsonLayoutError> {
    match data.get(offset) {
        Some(b'"') => parse_string(data, offset),
        Some(b'{') => parse_object(data, offset, parent_depth + 1, total_fields),
        Some(b'[') => parse_array(data, offset, parent_depth + 1, total_fields),
        Some(b't') => parse_exact(data, offset, b"true"),
        Some(b'f') => parse_exact(data, offset, b"false"),
        Some(b'n') => parse_exact(data, offset, b"null"),
        Some(b'-' | b'0'..=b'9') => parse_number(data, offset),
        _ => Err(JsonLayoutError::InvalidJson),
    }
}

fn parse_object(
    data: &[u8],
    mut offset: usize,
    depth: usize,
    total_fields: &mut usize,
) -> Result<usize, JsonLayoutError> {
    if depth > MAX_DEPTH {
        return Err(JsonLayoutError::TooDeep);
    }
    offset += 1;
    offset = skip_whitespace(data, offset);
    if data.get(offset) == Some(&b'}') {
        return Ok(offset + 1);
    }
    loop {
        offset = parse_string(data, skip_whitespace(data, offset))?;
        offset = skip_whitespace(data, offset);
        if data.get(offset) != Some(&b':') {
            return Err(JsonLayoutError::InvalidJson);
        }
        add_field(total_fields)?;
        offset = parse_value(data, skip_whitespace(data, offset + 1), depth, total_fields)?;
        offset = skip_whitespace(data, offset);
        match data.get(offset) {
            Some(b',') => offset += 1,
            Some(b'}') => return Ok(offset + 1),
            _ => return Err(JsonLayoutError::InvalidJson),
        }
    }
}

fn parse_array(
    data: &[u8],
    mut offset: usize,
    depth: usize,
    total_fields: &mut usize,
) -> Result<usize, JsonLayoutError> {
    if depth > MAX_DEPTH {
        return Err(JsonLayoutError::TooDeep);
    }
    offset += 1;
    offset = skip_whitespace(data, offset);
    if data.get(offset) == Some(&b']') {
        return Ok(offset + 1);
    }
    loop {
        offset = parse_value(data, skip_whitespace(data, offset), depth, total_fields)?;
        offset = skip_whitespace(data, offset);
        match data.get(offset) {
            Some(b',') => offset += 1,
            Some(b']') => return Ok(offset + 1),
            _ => return Err(JsonLayoutError::InvalidJson),
        }
    }
}

fn parse_string(data: &[u8], offset: usize) -> Result<usize, JsonLayoutError> {
    if data.get(offset) != Some(&b'"') {
        return Err(JsonLayoutError::InvalidJson);
    }
    let mut cursor = offset + 1;
    while let Some(&byte) = data.get(cursor) {
        match byte {
            b'"' => return Ok(cursor + 1),
            b'\\' => {
                cursor += 1;
                match data.get(cursor) {
                    Some(b'"' | b'\\' | b'/' | b'b' | b'f' | b'n' | b'r' | b't') => {
                        cursor += 1;
                    }
                    Some(b'u') => {
                        let digits = data
                            .get(cursor + 1..cursor + 5)
                            .ok_or(JsonLayoutError::InvalidJson)?;
                        if !digits.iter().all(u8::is_ascii_hexdigit) {
                            return Err(JsonLayoutError::InvalidJson);
                        }
                        cursor += 5;
                    }
                    _ => return Err(JsonLayoutError::InvalidJson),
                }
            }
            0x00..=0x1f => return Err(JsonLayoutError::InvalidJson),
            _ => cursor += 1,
        }
    }
    Err(JsonLayoutError::InvalidJson)
}

fn parse_number(data: &[u8], mut offset: usize) -> Result<usize, JsonLayoutError> {
    if data.get(offset) == Some(&b'-') {
        offset += 1;
    }
    match data.get(offset) {
        Some(b'0') => offset += 1,
        Some(b'1'..=b'9') => {
            offset += 1;
            while matches!(data.get(offset), Some(b'0'..=b'9')) {
                offset += 1;
            }
        }
        _ => return Err(JsonLayoutError::InvalidJson),
    }
    if data.get(offset) == Some(&b'.') {
        offset += 1;
        let start = offset;
        while matches!(data.get(offset), Some(b'0'..=b'9')) {
            offset += 1;
        }
        if offset == start {
            return Err(JsonLayoutError::InvalidJson);
        }
    }
    if matches!(data.get(offset), Some(b'e' | b'E')) {
        offset += 1;
        if matches!(data.get(offset), Some(b'+' | b'-')) {
            offset += 1;
        }
        let start = offset;
        while matches!(data.get(offset), Some(b'0'..=b'9')) {
            offset += 1;
        }
        if offset == start {
            return Err(JsonLayoutError::InvalidJson);
        }
    }
    Ok(offset)
}

fn parse_exact(data: &[u8], offset: usize, expected: &[u8]) -> Result<usize, JsonLayoutError> {
    let end = offset
        .checked_add(expected.len())
        .ok_or(JsonLayoutError::Overflow)?;
    if data.get(offset..end) == Some(expected) {
        Ok(end)
    } else {
        Err(JsonLayoutError::InvalidJson)
    }
}

fn add_field(total_fields: &mut usize) -> Result<(), JsonLayoutError> {
    *total_fields = total_fields
        .checked_add(1)
        .ok_or(JsonLayoutError::Overflow)?;
    if *total_fields > MAX_FIELDS {
        return Err(JsonLayoutError::TooManyFields);
    }
    Ok(())
}

fn skip_whitespace(data: &[u8], mut offset: usize) -> usize {
    while matches!(data.get(offset), Some(b' ' | b'\t' | b'\r' | b'\n')) {
        offset += 1;
    }
    offset
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn record_split_preserves_empty_and_unterminated_records() {
        assert_eq!(split_records(b""), Vec::<Record<'_>>::new());
        assert_eq!(
            split_records(b"{}\n\n[]"),
            vec![
                Record {
                    content: b"{}",
                    terminated: true,
                },
                Record {
                    content: b"",
                    terminated: true,
                },
                Record {
                    content: b"[]",
                    terminated: false,
                },
            ]
        );
    }

    #[test]
    fn layout_round_trips_exact_spelling_order_and_nested_values() {
        let mut record = br#" { "z" : [1,{"x":"\u0061"}], "a":-2.30E+4, "z":true }"#.to_vec();
        record.push(b'\r');
        let layout = JsonLayout::parse(&record).unwrap();
        assert_eq!(layout.values().len(), 3);
        assert_eq!(layout.values()[0], br#"[1,{"x":"\u0061"}]"#);
        assert_eq!(layout.values()[1], b"-2.30E+4");
        assert_eq!(layout.reconstruct().unwrap(), record);
        assert_eq!(
            layout.skeleton().iter().filter(|&&b| b == MARKER).count(),
            3
        );
    }

    #[test]
    fn empty_object_and_unicode_round_trip() {
        for record in [b"{}".as_slice(), "{\"snow\":\"☃\"}".as_bytes()] {
            let layout = JsonLayout::parse(record).unwrap();
            assert_eq!(layout.reconstruct().unwrap(), record);
        }
    }

    #[test]
    fn malformed_non_object_and_invalid_utf8_are_rejected() {
        for record in [
            b"[]".as_slice(),
            b"{\"x\":01}",
            b"{\"x\":1,}",
            b"{\"x\":\"\\q\"}",
            b"{\"x\":true} trailing",
        ] {
            assert!(JsonLayout::parse(record).is_err(), "accepted {record:?}");
        }
        assert_eq!(
            JsonLayout::parse(b"{\"x\":\"\xff\"}"),
            Err(JsonLayoutError::InvalidUtf8)
        );
    }

    #[test]
    fn depth_and_field_limits_fail_closed() {
        let maximum_depth = format!("{{\"x\":{}}}", "[".repeat(31) + "0" + &"]".repeat(31));
        assert!(JsonLayout::parse(maximum_depth.as_bytes()).is_ok());
        let too_deep = format!("{{\"x\":{}}}", "[".repeat(32) + "0" + &"]".repeat(32));
        assert_eq!(
            JsonLayout::parse(too_deep.as_bytes()),
            Err(JsonLayoutError::TooDeep)
        );

        let too_wide = format!(
            "{{{}}}",
            (0..257)
                .map(|index| format!("\"k{index}\":0"))
                .collect::<Vec<_>>()
                .join(",")
        );
        assert_eq!(
            JsonLayout::parse(too_wide.as_bytes()),
            Err(JsonLayoutError::TooManyFields)
        );

        let nested_too_wide = format!("{{\"x\":{too_wide}}}");
        assert_eq!(
            JsonLayout::parse(nested_too_wide.as_bytes()),
            Err(JsonLayoutError::TooManyFields)
        );
    }

    #[test]
    fn reconstructed_skeleton_rejects_noncanonical_markers_and_count_mismatch() {
        assert_eq!(
            JsonLayout::reconstruct_from(&[MARKER], &[]),
            Err(JsonLayoutError::InvalidSkeleton)
        );
        assert_eq!(
            JsonLayout::reconstruct_from(&[MARKER, 7], &[]),
            Err(JsonLayoutError::InvalidSkeleton)
        );
        assert_eq!(
            JsonLayout::reconstruct_from(&[MARKER, PLACEHOLDER], &[]),
            Err(JsonLayoutError::PlaceholderMismatch)
        );
        assert_eq!(
            JsonLayout::reconstruct_from(b"{}", &[b"unused".to_vec()]),
            Err(JsonLayoutError::PlaceholderMismatch)
        );
    }
}
