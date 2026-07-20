use sha2::{Digest, Sha256};
use std::io::Write;
use std::thread;

const STREAM_MAGIC: &[u8; 4] = b"JLS2";
const FRAME_MAGIC: &[u8; 4] = b"JLF2";
const COLUMN_MAGIC: &[u8; 4] = b"JLC1";
const VERSION: u8 = 1;
const MODE_DIRECT: u8 = 0;
const MODE_COLUMNAR: u8 = 1;
const STREAM_HEADER_SIZE: usize = 84;
const SEGMENT_HEADER_SIZE: usize = 16;
const FRAME_HEADER_SIZE: usize = 88;
const COLUMN_HEADER_SIZE: usize = 68;
const COLUMN_ENTRY_SIZE: usize = 16;
const MAX_CHANNELS: usize = 256;
const MAX_RAW_EXPANSION: usize = 4;
const MAX_RAW_OVERHEAD: usize = 4096;
const MARKER: u8 = 0xff;
const MARKER_CHANNEL: u8 = 0x00;
const MARKER_LITERAL: u8 = 0xfe;
const MAX_ZSTD_WORKERS: usize = 8;
const MAX_SEGMENT_WORKERS: usize = 8;

#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub struct DecodeStats {
    pub encoded_bytes: u64,
    pub restored_bytes: u64,
    pub segment_count: u32,
}

type DecodeResult<T> = Result<T, String>;

fn checked_usize(value: u64, label: &str) -> DecodeResult<usize> {
    usize::try_from(value).map_err(|_| format!("{label} exceeds this platform's limits"))
}

fn read_u32(data: &[u8], offset: usize, label: &str) -> DecodeResult<u32> {
    let end = offset
        .checked_add(4)
        .ok_or_else(|| format!("{label} offset overflows"))?;
    Ok(u32::from_be_bytes(
        data.get(offset..end)
            .ok_or_else(|| format!("{label} is truncated"))?
            .try_into()
            .map_err(|_| format!("{label} is truncated"))?,
    ))
}

fn read_u64(data: &[u8], offset: usize, label: &str) -> DecodeResult<u64> {
    let end = offset
        .checked_add(8)
        .ok_or_else(|| format!("{label} offset overflows"))?;
    Ok(u64::from_be_bytes(
        data.get(offset..end)
            .ok_or_else(|| format!("{label} is truncated"))?
            .try_into()
            .map_err(|_| format!("{label} is truncated"))?,
    ))
}

fn read_digest(data: &[u8], offset: usize, label: &str) -> DecodeResult<[u8; 32]> {
    let end = offset
        .checked_add(32)
        .ok_or_else(|| format!("{label} offset overflows"))?;
    data.get(offset..end)
        .ok_or_else(|| format!("{label} is truncated"))?
        .try_into()
        .map_err(|_| format!("{label} is truncated"))
}

fn sha256(data: &[u8]) -> [u8; 32] {
    Sha256::digest(data).into()
}

fn decode_varint(data: &[u8], offset: &mut usize) -> DecodeResult<usize> {
    let mut value = 0_u64;
    let mut shift = 0_u32;
    for _ in 0..10 {
        let byte = *data
            .get(*offset)
            .ok_or_else(|| "JSON-column varint is truncated".to_owned())?;
        *offset += 1;
        let chunk = u64::from(byte & 0x7f)
            .checked_shl(shift)
            .ok_or_else(|| "JSON-column varint is too large".to_owned())?;
        value = value
            .checked_add(chunk)
            .ok_or_else(|| "JSON-column varint is too large".to_owned())?;
        if byte < 0x80 {
            return checked_usize(value, "JSON-column varint");
        }
        shift += 7;
    }
    Err("JSON-column varint is too long".to_owned())
}

fn decompress_zstd(payload: &[u8], expected_size: usize) -> DecodeResult<Vec<u8>> {
    let restored = zstd::bulk::decompress(payload, expected_size)
        .map_err(|error| format!("invalid zstd payload: {error}"))?;
    if restored.len() != expected_size {
        return Err("zstd output size mismatch".to_owned());
    }
    Ok(restored)
}

fn new_zstd_decompressor() -> DecodeResult<zstd::bulk::Decompressor<'static>> {
    zstd::bulk::Decompressor::new()
        .map_err(|error| format!("cannot initialize zstd decoder: {error}"))
}

fn decompress_zstd_with(
    decompressor: &mut zstd::bulk::Decompressor<'_>,
    payload: &[u8],
    expected_size: usize,
) -> DecodeResult<Vec<u8>> {
    let restored = decompressor
        .decompress(payload, expected_size)
        .map_err(|error| format!("invalid zstd payload: {error}"))?;
    if restored.len() != expected_size {
        return Err("zstd output size mismatch".to_owned());
    }
    Ok(restored)
}

fn decompress_streams(
    payloads: &[&[u8]],
    raw_sizes: &[usize],
    worker_limit: usize,
) -> DecodeResult<Vec<Vec<u8>>> {
    if payloads.len() != raw_sizes.len() {
        return Err("JSON-column stream table mismatch".to_owned());
    }
    if payloads.len() < 2 {
        let mut decompressor = new_zstd_decompressor()?;
        return payloads
            .iter()
            .zip(raw_sizes)
            .map(|(payload, &size)| decompress_zstd_with(&mut decompressor, payload, size))
            .collect();
    }
    let available = thread::available_parallelism().map_or(1, usize::from);
    let workers = payloads
        .len()
        .min(available)
        .min(MAX_ZSTD_WORKERS)
        .min(worker_limit.max(1));
    let mut decoded = vec![None; payloads.len()];
    if workers == 1 {
        let mut decompressor = new_zstd_decompressor()?;
        let mut rows = Vec::new();
        for index in (0..payloads.len()).step_by(workers) {
            rows.push((
                index,
                decompress_zstd_with(&mut decompressor, payloads[index], raw_sizes[index])?,
            ));
        }
        for (index, restored) in rows {
            decoded[index] = Some(restored);
        }
        return decoded
            .into_iter()
            .map(|item| item.ok_or_else(|| "zstd worker omitted a stream".to_owned()))
            .collect();
    }
    let worker_results = thread::scope(|scope| {
        let mut handles = Vec::with_capacity(workers);
        for worker in 0..workers {
            handles.push(scope.spawn(move || -> DecodeResult<Vec<(usize, Vec<u8>)>> {
                let mut decompressor = new_zstd_decompressor()?;
                let mut rows = Vec::new();
                for index in (worker..payloads.len()).step_by(workers) {
                    rows.push((
                        index,
                        decompress_zstd_with(&mut decompressor, payloads[index], raw_sizes[index])?,
                    ));
                }
                Ok(rows)
            }));
        }
        handles
            .into_iter()
            .map(|handle| handle.join().map_err(|_| "zstd worker panicked".to_owned()))
            .collect::<DecodeResult<Vec<_>>>()
    })?;
    for rows in worker_results {
        for (index, restored) in rows? {
            decoded[index] = Some(restored);
        }
    }
    decoded
        .into_iter()
        .map(|item| item.ok_or_else(|| "zstd worker omitted a stream".to_owned()))
        .collect()
}

fn reassemble_columns(
    skeleton: &[u8],
    channels: &[Vec<u8>],
    original_size: usize,
) -> DecodeResult<Vec<u8>> {
    let mut channel_offsets = vec![0_usize; channels.len()];
    let mut output = Vec::with_capacity(original_size);
    let mut offset = 0_usize;
    while offset < skeleton.len() {
        let marker = skeleton[offset..]
            .iter()
            .position(|&value| value == MARKER)
            .map_or(skeleton.len(), |relative| offset + relative);
        let literal = &skeleton[offset..marker];
        if literal.len() > original_size.saturating_sub(output.len()) {
            return Err("JSON-column output exceeds declared size".to_owned());
        }
        output.extend_from_slice(literal);
        if marker == skeleton.len() {
            break;
        }
        offset = marker + 1;
        let tag = *skeleton
            .get(offset)
            .ok_or_else(|| "JSON-column marker is truncated".to_owned())?;
        offset += 1;
        if tag == MARKER_LITERAL {
            if output.len() >= original_size {
                return Err("JSON-column output exceeds declared size".to_owned());
            }
            output.push(MARKER);
            continue;
        }
        if tag != MARKER_CHANNEL {
            return Err("JSON-column marker tag is invalid".to_owned());
        }
        let channel_id = decode_varint(skeleton, &mut offset)?;
        let channel = channels
            .get(channel_id)
            .ok_or_else(|| "JSON-column channel reference is invalid".to_owned())?;
        let channel_offset = channel_offsets
            .get_mut(channel_id)
            .ok_or_else(|| "JSON-column channel reference is invalid".to_owned())?;
        let value_size = decode_varint(channel, channel_offset)?;
        let value_end = channel_offset
            .checked_add(value_size)
            .ok_or_else(|| "JSON-column value size overflows".to_owned())?;
        let value = channel
            .get(*channel_offset..value_end)
            .ok_or_else(|| "JSON-column value is truncated".to_owned())?;
        if value.len() > original_size.saturating_sub(output.len()) {
            return Err("JSON-column output exceeds declared size".to_owned());
        }
        output.extend_from_slice(value);
        *channel_offset = value_end;
    }
    if channels
        .iter()
        .zip(channel_offsets)
        .any(|(channel, consumed)| channel.len() != consumed)
    {
        return Err("JSON-column channel has unconsumed values".to_owned());
    }
    if output.len() != original_size {
        return Err("JSON-column output size mismatch".to_owned());
    }
    Ok(output)
}

fn decode_columnar(
    frame: &[u8],
    maximum_output: usize,
    worker_limit: usize,
) -> DecodeResult<(Vec<u8>, [u8; 32])> {
    if frame.len() < COLUMN_HEADER_SIZE {
        return Err("JSON-column frame is truncated".to_owned());
    }
    if frame.get(..4) != Some(COLUMN_MAGIC) {
        return Err("JSON-column frame magic mismatch".to_owned());
    }
    if frame[4] != VERSION {
        return Err(format!("unsupported JSON-column version: {}", frame[4]));
    }
    if frame[5..8] != [0, 0, 0] {
        return Err("JSON-column reserved bits are nonzero".to_owned());
    }
    let original_size = checked_usize(
        read_u64(frame, 8, "JSON-column original size")?,
        "JSON-column original size",
    )?;
    if original_size > maximum_output {
        return Err("JSON-column output exceeds safety limit".to_owned());
    }
    let expected_sha256 = read_digest(frame, 16, "JSON-column original SHA-256")?;
    let channel_count = usize::try_from(read_u32(frame, 48, "JSON-column channel count")?)
        .map_err(|_| "JSON-column channel count exceeds this platform".to_owned())?;
    if channel_count > MAX_CHANNELS {
        return Err("JSON-column frame has too many channels".to_owned());
    }
    let skeleton_size = checked_usize(
        read_u64(frame, 52, "JSON-column skeleton size")?,
        "JSON-column skeleton size",
    )?;
    let skeleton_payload_size = checked_usize(
        read_u64(frame, 60, "JSON-column skeleton payload size")?,
        "JSON-column skeleton payload size",
    )?;
    let maximum_raw_size = original_size
        .checked_mul(MAX_RAW_EXPANSION)
        .and_then(|value| value.checked_add(MAX_RAW_OVERHEAD))
        .ok_or_else(|| "JSON-column raw-size bound overflows".to_owned())?;
    if skeleton_size > maximum_raw_size {
        return Err("JSON-column skeleton size exceeds its bound".to_owned());
    }
    let table_size = channel_count
        .checked_mul(COLUMN_ENTRY_SIZE)
        .ok_or_else(|| "JSON-column table size overflows".to_owned())?;
    let header_end = COLUMN_HEADER_SIZE
        .checked_add(table_size)
        .ok_or_else(|| "JSON-column table size overflows".to_owned())?;
    if header_end > frame.len() {
        return Err("JSON-column channel table is truncated".to_owned());
    }
    let mut raw_sizes = Vec::with_capacity(channel_count + 1);
    raw_sizes.push(skeleton_size);
    let mut payload_sizes = Vec::with_capacity(channel_count + 1);
    payload_sizes.push(skeleton_payload_size);
    let mut total_raw_size = skeleton_size;
    for channel in 0..channel_count {
        let entry = COLUMN_HEADER_SIZE + channel * COLUMN_ENTRY_SIZE;
        let raw_size = checked_usize(
            read_u64(frame, entry, "JSON-column channel size")?,
            "JSON-column channel size",
        )?;
        let payload_size = checked_usize(
            read_u64(frame, entry + 8, "JSON-column channel payload size")?,
            "JSON-column channel payload size",
        )?;
        total_raw_size = total_raw_size
            .checked_add(raw_size)
            .ok_or_else(|| "JSON-column raw sizes overflow".to_owned())?;
        if raw_size > maximum_raw_size || total_raw_size > maximum_raw_size {
            return Err("JSON-column channel sizes exceed their bound".to_owned());
        }
        raw_sizes.push(raw_size);
        payload_sizes.push(payload_size);
    }
    let mut payloads = Vec::with_capacity(payload_sizes.len());
    let mut offset = header_end;
    for payload_size in payload_sizes {
        let end = offset
            .checked_add(payload_size)
            .ok_or_else(|| "JSON-column payload size overflows".to_owned())?;
        payloads.push(
            frame
                .get(offset..end)
                .ok_or_else(|| "JSON-column payload is truncated".to_owned())?,
        );
        offset = end;
    }
    if offset != frame.len() {
        return Err("JSON-column frame has trailing data".to_owned());
    }
    let mut decoded = decompress_streams(&payloads, &raw_sizes, worker_limit)?;
    let channels = decoded.split_off(1);
    let skeleton = decoded
        .pop()
        .ok_or_else(|| "JSON-column skeleton is missing".to_owned())?;
    let restored = reassemble_columns(&skeleton, &channels, original_size)?;
    Ok((restored, expected_sha256))
}

fn decode_frame(
    frame: &[u8],
    declared_size: usize,
    channel_worker_limit: usize,
) -> DecodeResult<Vec<u8>> {
    if frame.len() < FRAME_HEADER_SIZE {
        return Err("JLF2 frame is truncated".to_owned());
    }
    if frame.get(..4) != Some(FRAME_MAGIC) {
        return Err("JLF2 magic mismatch".to_owned());
    }
    if frame[4] != VERSION {
        return Err(format!("unsupported JLF2 version: {}", frame[4]));
    }
    let mode = frame[5];
    if frame[6..8] != [0, 0] {
        return Err("JLF2 reserved bits are nonzero".to_owned());
    }
    let original_size = checked_usize(
        read_u64(frame, 8, "JLF2 original size")?,
        "JLF2 original size",
    )?;
    if original_size != declared_size {
        return Err("JLS2 nested frame size mismatch".to_owned());
    }
    let payload_size = checked_usize(
        read_u64(frame, 16, "JLF2 payload size")?,
        "JLF2 payload size",
    )?;
    let expected_original_sha256 = read_digest(frame, 24, "JLF2 original SHA-256")?;
    let expected_payload_sha256 = read_digest(frame, 56, "JLF2 payload SHA-256")?;
    if payload_size != frame.len() - FRAME_HEADER_SIZE {
        return Err("JLF2 payload size mismatch".to_owned());
    }
    let payload = &frame[FRAME_HEADER_SIZE..];
    if sha256(payload) != expected_payload_sha256 {
        return Err("JLF2 payload SHA-256 mismatch".to_owned());
    }
    let (restored, column_sha256) = match mode {
        MODE_DIRECT => (decompress_zstd(payload, original_size)?, None),
        MODE_COLUMNAR => {
            let (restored, expected) =
                decode_columnar(payload, original_size, channel_worker_limit)?;
            (restored, Some(expected))
        }
        _ => return Err(format!("unsupported JLF2 mode: {mode}")),
    };
    if restored.len() != original_size {
        return Err("JLF2 output size mismatch".to_owned());
    }
    let restored_sha256 = sha256(&restored);
    if restored_sha256 != expected_original_sha256 {
        return Err("JLF2 original SHA-256 mismatch".to_owned());
    }
    if column_sha256.is_some_and(|expected| expected != restored_sha256) {
        return Err("JSON-column original SHA-256 mismatch".to_owned());
    }
    Ok(restored)
}

pub fn decode_to_writer(
    encoded: &[u8],
    output: &mut impl Write,
    max_output_size: Option<u64>,
) -> DecodeResult<DecodeStats> {
    if encoded.len() < STREAM_HEADER_SIZE {
        return Err("JLS2 stream is truncated".to_owned());
    }
    if encoded.get(..4) != Some(STREAM_MAGIC) {
        return Err("JLS2 magic mismatch".to_owned());
    }
    if encoded[4] != VERSION {
        return Err(format!("unsupported JLS2 version: {}", encoded[4]));
    }
    if encoded[5] != 0 || encoded[6..8] != [0, 0] {
        return Err("JLS2 flags or reserved bits are nonzero".to_owned());
    }
    let original_size_u64 = read_u64(encoded, 8, "JLS2 original size")?;
    if max_output_size.is_some_and(|limit| original_size_u64 > limit) {
        return Err("JLS2 output exceeds safety limit".to_owned());
    }
    let original_size = checked_usize(original_size_u64, "JLS2 original size")?;
    let expected_original_sha256 = read_digest(encoded, 16, "JLS2 original SHA-256")?;
    let expected_encoded_sha256 = read_digest(encoded, 48, "JLS2 encoded SHA-256")?;
    let segment_count = read_u32(encoded, 80, "JLS2 segment count")?;
    if original_size == 0 && segment_count != 0 {
        return Err("empty JLS2 stream declares segments".to_owned());
    }
    if original_size > 0 && segment_count == 0 {
        return Err("nonempty JLS2 stream has no segments".to_owned());
    }
    if sha256(&encoded[STREAM_HEADER_SIZE..]) != expected_encoded_sha256 {
        return Err("JLS2 encoded SHA-256 mismatch".to_owned());
    }
    let mut offset = STREAM_HEADER_SIZE;
    let mut declared_size = 0_usize;
    let mut segments = Vec::with_capacity(segment_count as usize);
    for _ in 0..segment_count {
        let header_end = offset
            .checked_add(SEGMENT_HEADER_SIZE)
            .ok_or_else(|| "JLS2 segment header offset overflows".to_owned())?;
        if header_end > encoded.len() {
            return Err("JLS2 segment header is truncated".to_owned());
        }
        let segment_size = checked_usize(
            read_u64(encoded, offset, "JLS2 segment size")?,
            "JLS2 segment size",
        )?;
        let frame_size = checked_usize(
            read_u64(encoded, offset + 8, "JLS2 segment frame size")?,
            "JLS2 segment frame size",
        )?;
        if segment_size > original_size.saturating_sub(declared_size) {
            return Err("JLS2 segment exceeds declared output size".to_owned());
        }
        let frame_end = header_end
            .checked_add(frame_size)
            .ok_or_else(|| "JLS2 segment frame size overflows".to_owned())?;
        let frame = encoded
            .get(header_end..frame_end)
            .ok_or_else(|| "JLS2 segment frame is truncated".to_owned())?;
        segments.push((segment_size, frame));
        declared_size = declared_size
            .checked_add(segment_size)
            .ok_or_else(|| "JLS2 declared output size overflows".to_owned())?;
        offset = frame_end;
    }
    if offset != encoded.len() {
        return Err("JLS2 stream has trailing data".to_owned());
    }
    if declared_size != original_size {
        return Err("JLS2 declared segment sizes do not match output".to_owned());
    }

    let available = thread::available_parallelism().map_or(1, usize::from);
    let segment_workers = segments.len().min(available).clamp(1, MAX_SEGMENT_WORKERS);
    let channel_worker_limit = if segments.len() == 1 {
        MAX_ZSTD_WORKERS
    } else {
        1
    };
    let mut restored_size = 0_usize;
    let mut restored_digest = Sha256::new();
    for batch in segments.chunks(segment_workers) {
        let restored_batch = thread::scope(|scope| {
            let handles: Vec<_> = batch
                .iter()
                .map(|&(size, frame)| {
                    scope.spawn(move || decode_frame(frame, size, channel_worker_limit))
                })
                .collect();
            handles
                .into_iter()
                .map(|handle| {
                    handle
                        .join()
                        .map_err(|_| "JLS2 segment worker panicked".to_owned())?
                })
                .collect::<DecodeResult<Vec<_>>>()
        })?;
        for restored in restored_batch {
            output
                .write_all(&restored)
                .map_err(|error| format!("cannot write output: {error}"))?;
            restored_digest.update(&restored);
            restored_size = restored_size
                .checked_add(restored.len())
                .ok_or_else(|| "JLS2 output size overflows".to_owned())?;
        }
    }
    if restored_size != original_size {
        return Err("JLS2 output size mismatch".to_owned());
    }
    let restored_sha256: [u8; 32] = restored_digest.finalize().into();
    if restored_sha256 != expected_original_sha256 {
        return Err("JLS2 original SHA-256 mismatch".to_owned());
    }
    Ok(DecodeStats {
        encoded_bytes: encoded.len() as u64,
        restored_bytes: original_size_u64,
        segment_count,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn direct_stream(source: &[u8]) -> Vec<u8> {
        let payload = zstd::bulk::compress(source, 3).unwrap();
        let mut frame = Vec::new();
        frame.extend_from_slice(FRAME_MAGIC);
        frame.extend_from_slice(&[VERSION, MODE_DIRECT, 0, 0]);
        frame.extend_from_slice(&(source.len() as u64).to_be_bytes());
        frame.extend_from_slice(&(payload.len() as u64).to_be_bytes());
        frame.extend_from_slice(&sha256(source));
        frame.extend_from_slice(&sha256(&payload));
        frame.extend_from_slice(&payload);
        let mut stream_payload = Vec::new();
        stream_payload.extend_from_slice(&(source.len() as u64).to_be_bytes());
        stream_payload.extend_from_slice(&(frame.len() as u64).to_be_bytes());
        stream_payload.extend_from_slice(&frame);
        let mut stream = Vec::new();
        stream.extend_from_slice(STREAM_MAGIC);
        stream.extend_from_slice(&[VERSION, 0, 0, 0]);
        stream.extend_from_slice(&(source.len() as u64).to_be_bytes());
        stream.extend_from_slice(&sha256(source));
        stream.extend_from_slice(&sha256(&stream_payload));
        stream.extend_from_slice(&1_u32.to_be_bytes());
        stream.extend_from_slice(&stream_payload);
        stream
    }

    #[test]
    fn decodes_direct_stream() {
        let source = b"exact bytes\nwith another line\n";
        let stream = direct_stream(source);
        let mut restored = Vec::new();
        let stats = decode_to_writer(&stream, &mut restored, None).unwrap();
        assert_eq!(restored, source);
        assert_eq!(stats.restored_bytes, source.len() as u64);
        assert_eq!(stats.segment_count, 1);
    }

    #[test]
    fn decodes_empty_stream() {
        let mut stream = Vec::new();
        stream.extend_from_slice(STREAM_MAGIC);
        stream.extend_from_slice(&[VERSION, 0, 0, 0]);
        stream.extend_from_slice(&0_u64.to_be_bytes());
        stream.extend_from_slice(&sha256(b""));
        stream.extend_from_slice(&sha256(b""));
        stream.extend_from_slice(&0_u32.to_be_bytes());
        let mut restored = Vec::new();
        decode_to_writer(&stream, &mut restored, Some(0)).unwrap();
        assert!(restored.is_empty());
    }

    #[test]
    fn rejects_output_over_limit_before_decompression() {
        let stream = direct_stream(b"too large");
        let error = decode_to_writer(&stream, &mut Vec::new(), Some(3)).unwrap_err();
        assert_eq!(error, "JLS2 output exceeds safety limit");
    }

    #[test]
    fn rejects_corrupt_nested_original_digest() {
        let mut stream = direct_stream(b"digest me");
        let frame_digest_offset = STREAM_HEADER_SIZE + SEGMENT_HEADER_SIZE + 24;
        stream[frame_digest_offset] ^= 1;
        let encoded_digest = sha256(&stream[STREAM_HEADER_SIZE..]);
        stream[48..80].copy_from_slice(&encoded_digest);
        let error = decode_to_writer(&stream, &mut Vec::new(), None).unwrap_err();
        assert_eq!(error, "JLF2 original SHA-256 mismatch");
    }

    #[test]
    fn rejects_trailing_data_even_with_recomputed_outer_digest() {
        let mut stream = direct_stream(b"no trailers");
        stream.push(0);
        let encoded_digest = sha256(&stream[STREAM_HEADER_SIZE..]);
        stream[48..80].copy_from_slice(&encoded_digest);
        let error = decode_to_writer(&stream, &mut Vec::new(), None).unwrap_err();
        assert_eq!(error, "JLS2 stream has trailing data");
    }
}
