use crate::jls2;
use sha2::{Digest, Sha256};
use std::fs;
use std::io::{self, Write};
use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

const STREAM_HEADER_SIZE: usize = 84;
const SEGMENT_HEADER_SIZE: usize = 16;
const FRAME_HEADER_SIZE: usize = 88;
const COLUMN_HEADER_SIZE: usize = 68;
const COLUMN_ENTRY_SIZE: usize = 16;
const A2_LOGICAL_CPUS: usize = 4;
const PROPOSED_BATCH_BUDGET: usize = 32 * 1024 * 1024;
const MAX_CHANNELS: usize = 256;
const MAX_RAW_EXPANSION: usize = 4;
const MAX_RAW_OVERHEAD: usize = 4096;

#[derive(Clone, Copy, Default)]
struct Snapshot {
    rss: usize,
    in_use: usize,
    free_arena: usize,
    mmap: usize,
}

#[repr(C)]
#[derive(Clone, Copy, Default)]
#[allow(dead_code)] // Constructed by glibc across the mallinfo2 FFI boundary.
struct Mallinfo2 {
    arena: usize,
    ordblks: usize,
    smblks: usize,
    hblks: usize,
    hblkhd: usize,
    usmblks: usize,
    fsmblks: usize,
    uordblks: usize,
    fordblks: usize,
    keepcost: usize,
}

#[cfg(target_env = "gnu")]
unsafe extern "C" {
    fn mallinfo2() -> Mallinfo2;
    fn malloc_trim(pad: usize) -> i32;
}

#[derive(Clone, Debug)]
struct Segment {
    index: usize,
    mode: &'static str,
    frame_bytes: usize,
    output_bytes: usize,
    skeleton_raw_bytes: usize,
    channel_raw_bytes: Vec<usize>,
    live_working_bytes: usize,
    a2_batch: usize,
    a2_batch_bytes: usize,
    proposed_batch: usize,
    proposed_batch_bytes: usize,
}

#[derive(Default)]
struct DigestWriter {
    digest: Sha256,
    bytes: usize,
}

impl Write for DigestWriter {
    fn write(&mut self, buffer: &[u8]) -> io::Result<usize> {
        self.digest.update(buffer);
        self.bytes = self
            .bytes
            .checked_add(buffer.len())
            .ok_or_else(|| io::Error::other("audit output size overflows"))?;
        Ok(buffer.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

fn read_u32(data: &[u8], offset: usize, label: &str) -> Result<u32, String> {
    let end = offset
        .checked_add(4)
        .ok_or_else(|| format!("{label} offset overflows"))?;
    let bytes: [u8; 4] = data
        .get(offset..end)
        .ok_or_else(|| format!("{label} is truncated"))?
        .try_into()
        .map_err(|_| format!("{label} is truncated"))?;
    Ok(u32::from_be_bytes(bytes))
}

fn read_u64(data: &[u8], offset: usize, label: &str) -> Result<usize, String> {
    let end = offset
        .checked_add(8)
        .ok_or_else(|| format!("{label} offset overflows"))?;
    let bytes: [u8; 8] = data
        .get(offset..end)
        .ok_or_else(|| format!("{label} is truncated"))?
        .try_into()
        .map_err(|_| format!("{label} is truncated"))?;
    usize::try_from(u64::from_be_bytes(bytes)).map_err(|_| format!("{label} exceeds this platform"))
}

fn hex_digest(data: &[u8]) -> String {
    Sha256::digest(data)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn rss_bytes() -> Result<usize, String> {
    let content = fs::read_to_string("/proc/self/smaps_rollup")
        .or_else(|_| fs::read_to_string("/proc/self/status"))
        .map_err(|error| format!("cannot read Linux RSS: {error}"))?;
    let line = content
        .lines()
        .find(|line| line.starts_with("Rss:") || line.starts_with("VmRSS:"))
        .ok_or_else(|| "Linux RSS field is missing".to_owned())?;
    let kib = line
        .split_whitespace()
        .nth(1)
        .ok_or_else(|| "Linux RSS value is missing".to_owned())?
        .parse::<usize>()
        .map_err(|_| "Linux RSS value is invalid".to_owned())?;
    kib.checked_mul(1024)
        .ok_or_else(|| "Linux RSS value overflows".to_owned())
}

fn allocator() -> Result<(usize, usize, usize), String> {
    #[cfg(target_env = "gnu")]
    {
        // SAFETY: mallinfo2 has no arguments and returns process-local allocator counters.
        let info = unsafe { mallinfo2() };
        return Ok((info.uordblks, info.fordblks, info.hblkhd));
    }
    #[allow(unreachable_code)]
    Err("mallinfo2 is unavailable".to_owned())
}

fn snapshot() -> Result<Snapshot, String> {
    let (in_use, free_arena, mmap) = allocator()?;
    Ok(Snapshot {
        rss: rss_bytes()?,
        in_use,
        free_arena,
        mmap,
    })
}

fn parse_segments(encoded: &[u8]) -> Result<Vec<Segment>, String> {
    if encoded.len() < STREAM_HEADER_SIZE || encoded.get(..4) != Some(b"JLS2") {
        return Err("audit input is not a complete JLS2 stream".to_owned());
    }
    if encoded[4] != 1 || encoded[5..8] != [0, 0, 0] {
        return Err("audit input has unsupported JLS2 version or flags".to_owned());
    }
    let original_size = read_u64(encoded, 8, "JLS2 original size")?;
    let segment_count = usize::try_from(read_u32(encoded, 80, "segment count")?)
        .map_err(|_| "segment count exceeds this platform".to_owned())?;
    let mut segments = Vec::with_capacity(segment_count);
    let mut offset = STREAM_HEADER_SIZE;
    let mut declared_total = 0usize;
    for index in 0..segment_count {
        let output_bytes = read_u64(encoded, offset, "segment output size")?;
        let frame_bytes = read_u64(encoded, offset + 8, "segment frame size")?;
        let frame_start = offset
            .checked_add(SEGMENT_HEADER_SIZE)
            .ok_or_else(|| "segment header overflows".to_owned())?;
        let frame_end = frame_start
            .checked_add(frame_bytes)
            .ok_or_else(|| "segment frame overflows".to_owned())?;
        let frame = encoded
            .get(frame_start..frame_end)
            .ok_or_else(|| "segment frame is truncated".to_owned())?;
        if frame.get(..4) != Some(b"JLF2") || frame.len() < FRAME_HEADER_SIZE {
            return Err("nested JLF2 frame is invalid".to_owned());
        }
        if frame[4] != 1 || frame[6..8] != [0, 0] {
            return Err("nested JLF2 version or flags are invalid".to_owned());
        }
        if read_u64(frame, 8, "nested output size")? != output_bytes {
            return Err("nested output declaration mismatch".to_owned());
        }
        let payload_bytes = read_u64(frame, 16, "nested payload size")?;
        if payload_bytes != frame.len().saturating_sub(FRAME_HEADER_SIZE) {
            return Err("nested payload size mismatch".to_owned());
        }
        let (mode, skeleton_raw_bytes, channel_raw_bytes, live_working_bytes) = match frame[5] {
            0 => ("direct", 0, Vec::new(), output_bytes),
            1 => {
                let column = &frame[FRAME_HEADER_SIZE..];
                if column.get(..4) != Some(b"JLC1") || column.len() < COLUMN_HEADER_SIZE {
                    return Err("nested JLC1 frame is invalid".to_owned());
                }
                if column[4] != 1 || column[5..8] != [0, 0, 0] {
                    return Err("nested JLC1 version or flags are invalid".to_owned());
                }
                if read_u64(column, 8, "column output size")? != output_bytes {
                    return Err("column output declaration mismatch".to_owned());
                }
                let channel_count = usize::try_from(read_u32(column, 48, "column channel count")?)
                    .map_err(|_| "channel count exceeds this platform".to_owned())?;
                if channel_count > MAX_CHANNELS {
                    return Err("column channel count exceeds bound".to_owned());
                }
                let skeleton = read_u64(column, 52, "column skeleton raw size")?;
                let skeleton_payload = read_u64(column, 60, "column skeleton payload size")?;
                let maximum_raw = output_bytes
                    .checked_mul(MAX_RAW_EXPANSION)
                    .and_then(|value| value.checked_add(MAX_RAW_OVERHEAD))
                    .ok_or_else(|| "column raw-size bound overflows".to_owned())?;
                if skeleton > maximum_raw {
                    return Err("column skeleton raw size exceeds bound".to_owned());
                }
                let table_bytes = channel_count
                    .checked_mul(COLUMN_ENTRY_SIZE)
                    .ok_or_else(|| "column table size overflows".to_owned())?;
                let header_end = COLUMN_HEADER_SIZE
                    .checked_add(table_bytes)
                    .ok_or_else(|| "column table size overflows".to_owned())?;
                if header_end > column.len() {
                    return Err("column table is truncated".to_owned());
                }
                let mut channels = Vec::with_capacity(channel_count);
                let mut raw_total = skeleton;
                let mut payload_total = skeleton_payload;
                for channel in 0..channel_count {
                    let entry = COLUMN_HEADER_SIZE + channel * COLUMN_ENTRY_SIZE;
                    let raw = read_u64(column, entry, "column channel raw size")?;
                    let payload = read_u64(column, entry + 8, "column channel payload size")?;
                    raw_total = raw_total
                        .checked_add(raw)
                        .ok_or_else(|| "column raw sizes overflow".to_owned())?;
                    if raw > maximum_raw || raw_total > maximum_raw {
                        return Err("column raw sizes exceed bound".to_owned());
                    }
                    payload_total = payload_total
                        .checked_add(payload)
                        .ok_or_else(|| "column payload sizes overflow".to_owned())?;
                    channels.push(raw);
                }
                if header_end.checked_add(payload_total) != Some(column.len()) {
                    return Err("column payload declarations mismatch".to_owned());
                }
                let live = output_bytes
                    .checked_add(raw_total)
                    .ok_or_else(|| "declared live working bytes overflow".to_owned())?;
                ("columnar", skeleton, channels, live)
            }
            mode => return Err(format!("unsupported JLF2 mode: {mode}")),
        };
        segments.push(Segment {
            index,
            mode,
            frame_bytes,
            output_bytes,
            skeleton_raw_bytes,
            channel_raw_bytes,
            live_working_bytes,
            a2_batch: index / A2_LOGICAL_CPUS,
            a2_batch_bytes: 0,
            proposed_batch: 0,
            proposed_batch_bytes: 0,
        });
        declared_total = declared_total
            .checked_add(output_bytes)
            .ok_or_else(|| "declared output total overflows".to_owned())?;
        offset = frame_end;
    }
    if offset != encoded.len() {
        return Err("JLS2 stream has trailing data".to_owned());
    }
    if declared_total != original_size {
        return Err("JLS2 declared output total mismatch".to_owned());
    }
    let a2_batches = segments
        .chunks(A2_LOGICAL_CPUS)
        .map(|batch| batch.iter().map(|segment| segment.live_working_bytes).sum())
        .collect::<Vec<usize>>();
    for segment in &mut segments {
        segment.a2_batch_bytes = a2_batches[segment.a2_batch];
    }
    let mut proposed_batch = 0;
    let mut proposed_sum = 0usize;
    for segment in &mut segments {
        if proposed_sum != 0
            && proposed_sum.saturating_add(segment.live_working_bytes) > PROPOSED_BATCH_BUDGET
        {
            proposed_batch += 1;
            proposed_sum = 0;
        }
        segment.proposed_batch = proposed_batch;
        proposed_sum = proposed_sum
            .checked_add(segment.live_working_bytes)
            .ok_or_else(|| "proposed batch size overflows".to_owned())?;
    }
    let proposed_count = segments
        .last()
        .map_or(0, |segment| segment.proposed_batch + 1);
    let mut proposed_sums = vec![0usize; proposed_count];
    for segment in &segments {
        proposed_sums[segment.proposed_batch] = proposed_sums[segment.proposed_batch]
            .checked_add(segment.live_working_bytes)
            .ok_or_else(|| "proposed batch size overflows".to_owned())?;
    }
    for segment in &mut segments {
        segment.proposed_batch_bytes = proposed_sums[segment.proposed_batch];
    }
    Ok(segments)
}

fn json_escape(value: &str) -> String {
    let mut output = String::with_capacity(value.len() + 2);
    output.push('"');
    for character in value.chars() {
        match character {
            '"' => output.push_str("\\\""),
            '\\' => output.push_str("\\\\"),
            '\n' => output.push_str("\\n"),
            '\r' => output.push_str("\\r"),
            '\t' => output.push_str("\\t"),
            character if character.is_control() => {
                output.push_str(&format!("\\u{:04x}", character as u32));
            }
            character => output.push(character),
        }
    }
    output.push('"');
    output
}

fn snapshot_json(phase: &str, batch: Option<usize>, value: Snapshot) -> String {
    let batch = batch.map_or_else(|| "null".to_owned(), |value| value.to_string());
    format!(
        "{{\"phase\":{},\"batch_index\":{},\"rss_bytes\":{},\"allocator_in_use_bytes\":{},\"allocator_free_arena_bytes\":{},\"allocator_mmap_bytes\":{}}}",
        json_escape(phase), batch, value.rss, value.in_use, value.free_arena, value.mmap
    )
}

pub fn run(
    input: &Path,
    fixture_id: &str,
    expected_output_sha256: &str,
    output_path: &Path,
) -> Result<(), String> {
    if !cfg!(all(target_os = "linux", target_env = "gnu")) {
        return Err("A3 audit requires Linux glibc mallinfo2".to_owned());
    }
    let encoded = fs::read(input).map_err(|error| format!("cannot read input: {error}"))?;
    let encoded_capacity = encoded.capacity();
    let segments = parse_segments(&encoded)?;
    let input_loaded = snapshot()?;
    let before_batch = snapshot()?;
    let running = Arc::new(AtomicBool::new(true));
    let maximum = Arc::new(Mutex::new(snapshot()?));
    let sampler_running = Arc::clone(&running);
    let sampler_maximum = Arc::clone(&maximum);
    let sampler = thread::spawn(move || {
        while sampler_running.load(Ordering::Relaxed) {
            if let Ok(observed) = snapshot() {
                let mut current = sampler_maximum.lock().expect("sampler mutex poisoned");
                if observed.rss > current.rss {
                    *current = observed;
                }
            }
            thread::sleep(Duration::from_micros(200));
        }
    });
    let mut restored = DigestWriter::default();
    let stats = jls2::decode_to_writer(&encoded, &mut restored, None)?;
    running.store(false, Ordering::Relaxed);
    sampler
        .join()
        .map_err(|_| "RSS sampler thread panicked".to_owned())?;
    let maximum_live = *maximum.lock().map_err(|_| "sampler mutex poisoned")?;
    let after_decoded_drop = snapshot()?;
    let output_bytes = restored.bytes;
    let output_sha256 = restored
        .digest
        .clone()
        .finalize()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    let exact = output_sha256 == expected_output_sha256;
    drop(restored);
    let after_output_drop = snapshot()?;
    #[cfg(target_env = "gnu")]
    // SAFETY: this diagnostic-only child calls glibc malloc_trim after all output drops.
    unsafe {
        malloc_trim(0);
    }
    let after_trim = snapshot()?;
    if !exact {
        return Err("diagnostic output SHA-256 mismatch".to_owned());
    }
    if stats.segment_count as usize != segments.len()
        || stats.restored_bytes as usize != output_bytes
    {
        return Err("product decoder stats mismatch diagnostic topology".to_owned());
    }
    let a2_peak = segments
        .iter()
        .map(|segment| segment.a2_batch_bytes)
        .max()
        .unwrap_or(0);
    let proposed_peak = segments
        .iter()
        .map(|segment| segment.proposed_batch_bytes)
        .max()
        .unwrap_or(0);
    let potential = a2_peak.saturating_sub(proposed_peak);
    let rss_reduction = maximum_live.rss.saturating_sub(after_decoded_drop.rss);
    let allocator_release = maximum_live
        .in_use
        .saturating_sub(after_decoded_drop.in_use);
    let credited = rss_reduction.min(potential.saturating_add(allocator_release));
    let unclassified = maximum_live.rss.saturating_sub(
        maximum_live
            .in_use
            .saturating_add(maximum_live.free_arena)
            .saturating_add(maximum_live.mmap),
    );
    let segment_json = segments
        .iter()
        .map(|segment| {
            let channel_sizes = segment
                .channel_raw_bytes
                .iter()
                .map(usize::to_string)
                .collect::<Vec<_>>()
                .join(",");
            format!(
                "{{\"segment_index\":{},\"mode\":{},\"encoded_frame_bytes\":{},\"encoded_frame_borrowed\":true,\"declared_output_bytes\":{},\"declared_skeleton_raw_bytes\":{},\"declared_channel_raw_bytes\":[{}],\"declared_live_working_bytes\":{},\"a2_batch_index\":{},\"a2_batch_declared_live_working_bytes\":{},\"proposed_batch_index\":{},\"proposed_batch_declared_live_working_bytes\":{}}}",
                segment.index,
                json_escape(segment.mode),
                segment.frame_bytes,
                segment.output_bytes,
                segment.skeleton_raw_bytes,
                channel_sizes,
                segment.live_working_bytes,
                segment.a2_batch,
                segment.a2_batch_bytes,
                segment.proposed_batch,
                segment.proposed_batch_bytes,
            )
        })
        .collect::<Vec<_>>()
        .join(",");
    let phases = [
        snapshot_json("input_loaded", None, input_loaded),
        snapshot_json("before_batch", Some(0), before_batch),
        snapshot_json("maximum_live_batch", None, maximum_live),
        snapshot_json("after_decoded_buffers_drop", None, after_decoded_drop),
        snapshot_json("after_output_buffers_drop", None, after_output_drop),
        snapshot_json("after_malloc_trim", None, after_trim),
    ]
    .join(",");
    let json = format!(
        "{{\"schema_version\":1,\"fixture_id\":{},\"encoded_bytes\":{},\"encoded_capacity_bytes\":{},\"encoded_sha256\":{},\"output_bytes\":{},\"output_sha256\":{},\"segment_count\":{},\"exact\":true,\"segments\":[{}],\"phase_snapshots\":[{}],\"attribution\":{{\"decoded_concurrency_potential_bytes\":{},\"phase_correlated_rss_reduction_bytes\":{},\"phase_correlated_allocator_release_bytes\":{},\"credited_bytes\":{},\"live_encoded_bytes_report_only\":{},\"encoded_lifetime_authorization_credit_bytes\":0,\"unclassified_resident_bytes\":{}}},\"corruption_results\":{{\"product_regression_suite\":\"verified separately by frozen workflow before corpus access\"}}}}\n",
        json_escape(fixture_id),
        encoded.len(),
        encoded_capacity,
        json_escape(&hex_digest(&encoded)),
        output_bytes,
        json_escape(&output_sha256),
        segments.len(),
        segment_json,
        phases,
        potential,
        rss_reduction,
        allocator_release,
        credited,
        encoded.len(),
        unclassified,
    );
    fs::write(output_path, json).map_err(|error| format!("cannot write audit JSON: {error}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn direct_frame(output_bytes: usize) -> Vec<u8> {
        let mut frame = vec![0_u8; FRAME_HEADER_SIZE];
        frame[..4].copy_from_slice(b"JLF2");
        frame[4] = 1;
        frame[5] = 0;
        frame[8..16].copy_from_slice(&(output_bytes as u64).to_be_bytes());
        frame
    }

    fn column_frame(output_bytes: usize, channel_count: u32, raw_size: usize) -> Vec<u8> {
        let table_bytes = channel_count as usize * COLUMN_ENTRY_SIZE;
        let mut column = vec![0_u8; COLUMN_HEADER_SIZE + table_bytes + 2];
        column[..4].copy_from_slice(b"JLC1");
        column[4] = 1;
        column[8..16].copy_from_slice(&(output_bytes as u64).to_be_bytes());
        column[48..52].copy_from_slice(&channel_count.to_be_bytes());
        column[52..60].copy_from_slice(&10_u64.to_be_bytes());
        column[60..68].copy_from_slice(&1_u64.to_be_bytes());
        if channel_count > 0 {
            column[68..76].copy_from_slice(&(raw_size as u64).to_be_bytes());
            column[76..84].copy_from_slice(&1_u64.to_be_bytes());
        }
        let mut frame = vec![0_u8; FRAME_HEADER_SIZE];
        frame[..4].copy_from_slice(b"JLF2");
        frame[4] = 1;
        frame[5] = 1;
        frame[8..16].copy_from_slice(&(output_bytes as u64).to_be_bytes());
        frame[16..24].copy_from_slice(&(column.len() as u64).to_be_bytes());
        frame.extend_from_slice(&column);
        frame
    }

    fn stream(rows: &[(usize, Vec<u8>)]) -> Vec<u8> {
        let original_size: usize = rows.iter().map(|(size, _)| size).sum();
        let mut encoded = vec![0_u8; STREAM_HEADER_SIZE];
        encoded[..4].copy_from_slice(b"JLS2");
        encoded[4] = 1;
        encoded[8..16].copy_from_slice(&(original_size as u64).to_be_bytes());
        encoded[80..84].copy_from_slice(&(rows.len() as u32).to_be_bytes());
        for (size, frame) in rows {
            encoded.extend_from_slice(&(*size as u64).to_be_bytes());
            encoded.extend_from_slice(&(frame.len() as u64).to_be_bytes());
            encoded.extend_from_slice(frame);
        }
        encoded
    }

    #[test]
    fn parses_direct_and_columnar_declared_topology() {
        let encoded = stream(&[(20, direct_frame(20)), (100, column_frame(100, 1, 20))]);
        let segments = parse_segments(&encoded).unwrap();
        assert_eq!(segments.len(), 2);
        assert_eq!(segments[0].mode, "direct");
        assert_eq!(segments[0].live_working_bytes, 20);
        assert_eq!(segments[1].mode, "columnar");
        assert_eq!(segments[1].skeleton_raw_bytes, 10);
        assert_eq!(segments[1].channel_raw_bytes, vec![20]);
        assert_eq!(segments[1].live_working_bytes, 130);
        assert_eq!(segments[0].a2_batch_bytes, 150);
        assert_eq!(segments[1].proposed_batch_bytes, 150);
    }

    #[test]
    fn rejects_truncation_and_output_total_mismatch() {
        let mut truncated = stream(&[(20, direct_frame(20))]);
        truncated.pop();
        assert!(parse_segments(&truncated)
            .unwrap_err()
            .contains("truncated"));

        let mut mismatch = stream(&[(20, direct_frame(20))]);
        mismatch[8..16].copy_from_slice(&21_u64.to_be_bytes());
        assert!(parse_segments(&mismatch)
            .unwrap_err()
            .contains("output total mismatch"));
    }

    #[test]
    fn rejects_channel_count_and_raw_size_bounds() {
        let too_many = stream(&[(100, column_frame(100, 257, 1))]);
        assert!(parse_segments(&too_many)
            .unwrap_err()
            .contains("channel count exceeds bound"));

        let raw_overflow = stream(&[(100, column_frame(100, 1, 10_000))]);
        assert!(parse_segments(&raw_overflow)
            .unwrap_err()
            .contains("raw sizes exceed bound"));
    }
}
