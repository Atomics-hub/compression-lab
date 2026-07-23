//! Deterministic accounting CLI for the preregistered S0 JSON/log screen.
//!
//! Research infrastructure, not a product codec. `encode` charges one arm on
//! one item, writes the exact event/literal tape, immediately re-decodes the
//! written tape bytes through the independent decoder ledger, and emits a
//! deterministic JSON receipt with the frozen per-item projection and the
//! diagnostic segment ledger. `decode` reproduces the exact source from a
//! tape plus its expected ledger. Receipts contain only content-derived
//! fields — no paths, timestamps, or host identity — so a clean-checkout
//! confirmation must reproduce them byte-for-byte.

#[path = "../s0/mod.rs"]
pub mod s0;

use s0::{
    decode_arm_item_with_bits, encode_arm_item_with_bits, Arm, Ledger, LossTable, SegmentSnapshot,
    Tape, ARMS, SEGMENT_BYTES, SSE_BASE_BUCKET_BITS, SSE_REFINED_BUCKET_BITS,
};
use sha2::{Digest, Sha256};
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::ExitCode;

const VERSION: &str = env!("CARGO_PKG_VERSION");

const HELP: &str = "clab-s0-kernel — deterministic S0 screen accounting kernel

Usage:
  clab-s0-kernel arms
  clab-s0-kernel encode --arm NAME --item-index N --input PATH
                        --tape-out PATH --receipt-out PATH
                        [--segment-bytes N] [--no-segments]
                        [--sse-bucket-bits 17|18] [--force]
  clab-s0-kernel decode --arm NAME --item-index N --tape PATH
                        --records N --modeled-binary-events N
                        --modeled-loss-q24 N --raw-literal-bytes N
                        --output PATH --receipt-out PATH
                        [--sse-bucket-bits 17|18] [--force]
  clab-s0-kernel --help
  clab-s0-kernel --version
";

fn main() -> ExitCode {
    let arguments: Vec<String> = env::args().skip(1).collect();
    let arguments: Vec<&str> = arguments.iter().map(String::as_str).collect();
    match arguments.split_first() {
        None => {
            eprint!("{HELP}");
            ExitCode::from(2)
        }
        Some((&"--help", [])) => {
            print!("{HELP}");
            ExitCode::SUCCESS
        }
        Some((&"--version", [])) => {
            println!("clab-s0-kernel {VERSION}");
            ExitCode::SUCCESS
        }
        Some((&"arms", [])) => {
            for arm in ARMS {
                println!("{} {}", arm.id(), arm.name());
            }
            ExitCode::SUCCESS
        }
        Some((&"encode", rest)) => run(encode_command(rest)),
        Some((&"decode", rest)) => run(decode_command(rest)),
        Some((command, _)) => {
            eprintln!("unknown or malformed command: {command}\n{HELP}");
            ExitCode::from(2)
        }
    }
}

fn run(result: Result<(), CommandError>) -> ExitCode {
    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(CommandError::Usage(message)) => {
            eprintln!("{message}\n{HELP}");
            ExitCode::from(2)
        }
        Err(CommandError::Failure(message)) => {
            eprintln!("clab-s0-kernel: {message}");
            ExitCode::FAILURE
        }
    }
}

enum CommandError {
    Usage(String),
    Failure(String),
}

fn usage(message: impl Into<String>) -> CommandError {
    CommandError::Usage(message.into())
}

fn failure(message: impl Into<String>) -> CommandError {
    CommandError::Failure(message.into())
}

#[derive(Default)]
struct Options {
    values: Vec<(String, String)>,
    force: bool,
    no_segments: bool,
}

fn parse_options(arguments: &[&str], allowed: &[&str]) -> Result<Options, CommandError> {
    let mut options = Options::default();
    let mut index = 0;
    while index < arguments.len() {
        let flag = arguments[index];
        match flag {
            "--force" => {
                options.force = true;
                index += 1;
            }
            "--no-segments" => {
                options.no_segments = true;
                index += 1;
            }
            _ => {
                let name = flag
                    .strip_prefix("--")
                    .filter(|name| allowed.contains(name))
                    .ok_or_else(|| usage(format!("unknown option: {flag}")))?;
                let value = arguments
                    .get(index + 1)
                    .ok_or_else(|| usage(format!("missing value for {flag}")))?;
                if options.values.iter().any(|(existing, _)| existing == name) {
                    return Err(usage(format!("duplicate option: {flag}")));
                }
                options.values.push((name.to_owned(), (*value).to_owned()));
                index += 2;
            }
        }
    }
    Ok(options)
}

impl Options {
    fn take(&self, name: &str) -> Result<&str, CommandError> {
        self.values
            .iter()
            .find(|(existing, _)| existing == name)
            .map(|(_, value)| value.as_str())
            .ok_or_else(|| usage(format!("missing required option: --{name}")))
    }

    fn take_optional(&self, name: &str) -> Option<&str> {
        self.values
            .iter()
            .find(|(existing, _)| existing == name)
            .map(|(_, value)| value.as_str())
    }
}

fn parse_arm(name: &str) -> Result<Arm, CommandError> {
    Arm::from_name(name).ok_or_else(|| {
        usage(format!(
            "unknown arm: {name} (expected one of {})",
            ARMS.map(Arm::name).join(", ")
        ))
    })
}

fn parse_number<T: std::str::FromStr>(name: &str, value: &str) -> Result<T, CommandError> {
    value
        .parse()
        .map_err(|_| usage(format!("invalid --{name}: {value}")))
}

/// Selects the capacity profile's SSE table size. Only the base (17) and the
/// single predeclared refined (18) bucket-bit counts are accepted; the default
/// is the base profile so an omitted flag reproduces the frozen base run.
fn parse_sse_bucket_bits(options: &Options) -> Result<u32, CommandError> {
    match options.take_optional("sse-bucket-bits") {
        None => Ok(SSE_BASE_BUCKET_BITS),
        Some(value) => {
            let bits: u32 = parse_number("sse-bucket-bits", value)?;
            if bits != SSE_BASE_BUCKET_BITS && bits != SSE_REFINED_BUCKET_BITS {
                return Err(usage(format!(
                    "--sse-bucket-bits must be {SSE_BASE_BUCKET_BITS} or {SSE_REFINED_BUCKET_BITS}: {bits}"
                )));
            }
            Ok(bits)
        }
    }
}

fn read_bytes(path: &str) -> Result<Vec<u8>, CommandError> {
    fs::read(path).map_err(|error| failure(format!("cannot read {path}: {error}")))
}

fn write_output(path: &str, bytes: &[u8], force: bool) -> Result<(), CommandError> {
    let destination = PathBuf::from(path);
    if let Some(parent) = destination
        .parent()
        .filter(|parent| *parent != Path::new(""))
    {
        fs::create_dir_all(parent)
            .map_err(|error| failure(format!("cannot create directory for {path}: {error}")))?;
    }
    if !force && destination.exists() {
        return Err(failure(format!(
            "refusing to overwrite {path} without --force"
        )));
    }
    fs::write(&destination, bytes).map_err(|error| failure(format!("cannot write {path}: {error}")))
}

/// Removes a written file again if the command fails before completing, so a
/// failed run never leaves a tape or decoded output without its receipt.
struct WrittenOutput<'a> {
    path: &'a str,
    published: bool,
}

impl<'a> WrittenOutput<'a> {
    fn pending(path: &'a str) -> Self {
        Self {
            path,
            published: false,
        }
    }

    fn keep(&mut self) {
        self.published = true;
    }
}

impl Drop for WrittenOutput<'_> {
    fn drop(&mut self) {
        if !self.published {
            let _ = fs::remove_file(self.path);
        }
    }
}

fn sha256_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    let mut hex = String::with_capacity(64);
    for byte in digest {
        hex.push_str(&format!("{byte:02x}"));
    }
    hex
}

fn ledger_json(ledger: Ledger) -> String {
    format!(
        "{{\"records\": {}, \"modeled_binary_events\": {}, \"modeled_loss_q24\": {}, \"raw_literal_bytes\": {}}}",
        ledger.records,
        ledger.modeled_binary_events,
        ledger.modeled_loss_q24,
        ledger.raw_literal_bytes
    )
}

fn projection_json(ledger: Ledger, source_bytes: u64) -> Result<String, CommandError> {
    let projection = ledger
        .project_item(source_bytes)
        .ok_or_else(|| failure("per-item projection overflowed"))?;
    Ok(format!(
        "{{\"payload_bytes\": {}, \"coder_allowance_bytes\": {}, \"block_allowance_bytes\": {}, \"stream_metadata_bytes\": {}, \"fixed_framing_bytes\": {}, \"complete_bytes\": {}}}",
        projection.payload_bytes,
        projection.coder_allowance_bytes,
        projection.block_allowance_bytes,
        projection.stream_metadata_bytes,
        projection.fixed_framing_bytes,
        projection.complete_bytes
    ))
}

fn segments_json(snapshots: &[SegmentSnapshot]) -> String {
    let entries: Vec<String> = snapshots
        .iter()
        .map(|snapshot| {
            format!(
                "    {{\"records\": {}, \"source_bytes\": {}, \"ledger\": {}}}",
                snapshot.records,
                snapshot.source_bytes,
                ledger_json(snapshot.ledger)
            )
        })
        .collect();
    if entries.is_empty() {
        "[]".to_owned()
    } else {
        format!("[\n{}\n  ]", entries.join(",\n"))
    }
}

fn encode_command(arguments: &[&str]) -> Result<(), CommandError> {
    let options = parse_options(
        arguments,
        &[
            "arm",
            "item-index",
            "input",
            "tape-out",
            "receipt-out",
            "segment-bytes",
            "sse-bucket-bits",
        ],
    )?;
    let arm = parse_arm(options.take("arm")?)?;
    let item_index: u8 = parse_number("item-index", options.take("item-index")?)?;
    let input = options.take("input")?;
    let tape_out = options.take("tape-out")?;
    let receipt_out = options.take("receipt-out")?;
    let sse_bucket_bits = parse_sse_bucket_bits(&options)?;
    let segment_bytes = match (options.no_segments, options.take_optional("segment-bytes")) {
        (true, Some(_)) => {
            return Err(usage("--segment-bytes conflicts with --no-segments"));
        }
        (true, None) => None,
        (false, Some(value)) => {
            let interval: u64 = parse_number("segment-bytes", value)?;
            if interval == 0 {
                return Err(usage("--segment-bytes must be positive"));
            }
            Some(interval)
        }
        (false, None) => Some(SEGMENT_BYTES),
    };

    let source = read_bytes(input)?;
    let table = LossTable::generate();
    let (tape, ledger, snapshots) = encode_arm_item_with_bits(
        arm,
        &source,
        &table,
        item_index,
        segment_bytes,
        sse_bucket_bits,
    )
    .map_err(|error| failure(format!("encode failed: {error}")))?;
    let tape_bytes = tape.to_bytes();
    write_output(tape_out, &tape_bytes, options.force)?;
    let mut written_tape = WrittenOutput::pending(tape_out);

    // Confirmation decode from the exact written bytes through the
    // independent decoder ledger; the receipt only reports a decode that
    // reproduced the source byte-for-byte.
    let written = read_bytes(tape_out)?;
    let reread = Tape::from_bytes(&written)
        .map_err(|error| failure(format!("written tape failed to parse: {error}")))?;
    let decoded =
        decode_arm_item_with_bits(arm, &reread, ledger, &table, item_index, sse_bucket_bits)
            .map_err(|error| failure(format!("confirmation decode failed: {error}")))?;
    if decoded != source {
        return Err(failure("confirmation decode did not reproduce the source"));
    }

    let source_bytes = source.len() as u64;
    let receipt = format!(
        "{{\n  \"schema\": \"clab-s0-kernel-encode-receipt-v1\",\n  \"kernel_version\": \"{VERSION}\",\n  \"arm\": \"{}\",\n  \"arm_id\": {},\n  \"item_index\": {},\n  \"source_bytes\": {},\n  \"source_sha256\": \"{}\",\n  \"tape_bytes\": {},\n  \"tape_sha256\": \"{}\",\n  \"segment_interval_bytes\": {},\n  \"sse_bucket_bits\": {},\n  \"ledger\": {},\n  \"event_limit_applies\": {},\n  \"event_limit_passes\": {},\n  \"item_projection\": {},\n  \"decoded_sha256\": \"{}\",\n  \"decode_matches_source\": true,\n  \"segments\": {}\n}}\n",
        arm.name(),
        arm.id(),
        item_index,
        source_bytes,
        sha256_hex(&source),
        tape_bytes.len(),
        sha256_hex(&tape_bytes),
        segment_bytes.map_or("null".to_owned(), |value| value.to_string()),
        sse_bucket_bits,
        ledger_json(ledger),
        arm.event_limit_applies(),
        ledger.event_limit_passes(),
        projection_json(ledger, source_bytes)?,
        sha256_hex(&decoded),
        segments_json(&snapshots),
    );
    write_output(receipt_out, receipt.as_bytes(), options.force)?;
    written_tape.keep();
    Ok(())
}

fn decode_command(arguments: &[&str]) -> Result<(), CommandError> {
    let options = parse_options(
        arguments,
        &[
            "arm",
            "item-index",
            "tape",
            "records",
            "modeled-binary-events",
            "modeled-loss-q24",
            "raw-literal-bytes",
            "output",
            "receipt-out",
            "sse-bucket-bits",
        ],
    )?;
    if options.no_segments {
        return Err(usage("--no-segments is an encode option"));
    }
    let arm = parse_arm(options.take("arm")?)?;
    let item_index: u8 = parse_number("item-index", options.take("item-index")?)?;
    let tape_path = options.take("tape")?;
    let output = options.take("output")?;
    let receipt_out = options.take("receipt-out")?;
    let sse_bucket_bits = parse_sse_bucket_bits(&options)?;
    let expected_ledger = Ledger {
        records: parse_number("records", options.take("records")?)?,
        modeled_binary_events: parse_number(
            "modeled-binary-events",
            options.take("modeled-binary-events")?,
        )?,
        modeled_loss_q24: parse_number("modeled-loss-q24", options.take("modeled-loss-q24")?)?,
        raw_literal_bytes: parse_number("raw-literal-bytes", options.take("raw-literal-bytes")?)?,
    };

    let tape_bytes = read_bytes(tape_path)?;
    let tape = Tape::from_bytes(&tape_bytes)
        .map_err(|error| failure(format!("tape failed to parse: {error}")))?;
    let table = LossTable::generate();
    let decoded = decode_arm_item_with_bits(
        arm,
        &tape,
        expected_ledger,
        &table,
        item_index,
        sse_bucket_bits,
    )
    .map_err(|error| failure(format!("decode failed: {error}")))?;
    write_output(output, &decoded, options.force)?;
    let mut written_output = WrittenOutput::pending(output);

    let receipt = format!(
        "{{\n  \"schema\": \"clab-s0-kernel-decode-receipt-v1\",\n  \"kernel_version\": \"{VERSION}\",\n  \"arm\": \"{}\",\n  \"arm_id\": {},\n  \"item_index\": {},\n  \"tape_bytes\": {},\n  \"tape_sha256\": \"{}\",\n  \"sse_bucket_bits\": {},\n  \"ledger\": {},\n  \"decoded_bytes\": {},\n  \"decoded_sha256\": \"{}\"\n}}\n",
        arm.name(),
        arm.id(),
        item_index,
        tape_bytes.len(),
        sha256_hex(&tape_bytes),
        sse_bucket_bits,
        ledger_json(expected_ledger),
        decoded.len(),
        sha256_hex(&decoded),
    );
    write_output(receipt_out, receipt.as_bytes(), options.force)?;
    written_output.keep();
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicU64, Ordering};

    static SCRATCH_COUNTER: AtomicU64 = AtomicU64::new(0);

    struct Scratch {
        root: PathBuf,
    }

    impl Scratch {
        fn new() -> Self {
            let serial = SCRATCH_COUNTER.fetch_add(1, Ordering::Relaxed);
            let root = env::temp_dir().join(format!(
                "clab-s0-kernel-test-{}-{serial}",
                std::process::id()
            ));
            fs::create_dir_all(&root).unwrap();
            Self { root }
        }

        fn path(&self, name: &str) -> String {
            self.root.join(name).to_str().unwrap().to_owned()
        }
    }

    impl Drop for Scratch {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.root);
        }
    }

    fn corpus() -> Vec<u8> {
        let mut source = Vec::new();
        for index in 0..40_u32 {
            source.extend_from_slice(
                format!(
                    "{{\"id\":{},\"ts\":\"2026-07-22T10:{:02}:30Z\",\"path\":\"/api/x/{}\"}}\n",
                    100 + index,
                    index % 60,
                    index % 4
                )
                .as_bytes(),
            );
        }
        source.extend_from_slice(b"{bad}\n\n{\"tail\":true}");
        source
    }

    fn receipt_field<'a>(receipt: &'a str, key: &str) -> &'a str {
        let marker = format!("\"{key}\": ");
        let start = receipt.find(&marker).unwrap() + marker.len();
        let rest = &receipt[start..];
        let end = rest.find([',', '}', '\n']).unwrap();
        rest[..end].trim_matches('"')
    }

    fn unwrap_message(result: Result<(), CommandError>) {
        result
            .map_err(|error| match error {
                CommandError::Usage(message) | CommandError::Failure(message) => message,
            })
            .unwrap();
    }

    #[test]
    fn encode_then_decode_reproduces_the_source_through_files() {
        let scratch = Scratch::new();
        let source = corpus();
        fs::write(scratch.path("item.ndjson"), &source).unwrap();

        for arm in ["raw-o3", "full"] {
            let tape = scratch.path(&format!("{arm}.tape"));
            let receipt_path = scratch.path(&format!("{arm}.receipt.json"));
            unwrap_message(encode_command(&[
                "--arm",
                arm,
                "--item-index",
                "1",
                "--input",
                &scratch.path("item.ndjson"),
                "--tape-out",
                &tape,
                "--receipt-out",
                &receipt_path,
                "--segment-bytes",
                "256",
            ]));

            let receipt = fs::read_to_string(&receipt_path).unwrap();
            assert_eq!(receipt_field(&receipt, "arm"), arm);
            assert_eq!(receipt_field(&receipt, "decode_matches_source"), "true");
            assert_eq!(
                receipt_field(&receipt, "source_sha256"),
                sha256_hex(&source)
            );
            assert_eq!(receipt_field(&receipt, "segment_interval_bytes"), "256");
            assert!(receipt.contains("\"segments\": [\n"));

            let output = scratch.path(&format!("{arm}.decoded"));
            let decode_receipt_path = scratch.path(&format!("{arm}.decode-receipt.json"));
            unwrap_message(decode_command(&[
                "--arm",
                arm,
                "--item-index",
                "1",
                "--tape",
                &tape,
                "--records",
                receipt_field(&receipt, "records"),
                "--modeled-binary-events",
                receipt_field(&receipt, "modeled_binary_events"),
                "--modeled-loss-q24",
                receipt_field(&receipt, "modeled_loss_q24"),
                "--raw-literal-bytes",
                receipt_field(&receipt, "raw_literal_bytes"),
                "--output",
                &output,
                "--receipt-out",
                &decode_receipt_path,
            ]));
            assert_eq!(fs::read(&output).unwrap(), source);
            let decode_receipt = fs::read_to_string(&decode_receipt_path).unwrap();
            assert_eq!(
                receipt_field(&decode_receipt, "decoded_sha256"),
                sha256_hex(&source)
            );
        }
    }

    #[test]
    fn receipts_are_deterministic_across_repeat_runs() {
        let scratch = Scratch::new();
        fs::write(scratch.path("item.ndjson"), corpus()).unwrap();
        let mut receipts = Vec::new();
        for run in 0..2 {
            let receipt_path = scratch.path(&format!("run{run}.receipt.json"));
            unwrap_message(encode_command(&[
                "--arm",
                "m1-m2",
                "--item-index",
                "0",
                "--input",
                &scratch.path("item.ndjson"),
                "--tape-out",
                &scratch.path(&format!("run{run}.tape")),
                "--receipt-out",
                &receipt_path,
            ]));
            receipts.push(fs::read(&receipt_path).unwrap());
        }
        assert_eq!(receipts[0], receipts[1]);
    }

    #[test]
    fn decode_rejects_a_tampered_expected_ledger() {
        let scratch = Scratch::new();
        fs::write(scratch.path("item.ndjson"), corpus()).unwrap();
        let receipt_path = scratch.path("receipt.json");
        unwrap_message(encode_command(&[
            "--arm",
            "m1-chassis",
            "--item-index",
            "0",
            "--input",
            &scratch.path("item.ndjson"),
            "--tape-out",
            &scratch.path("item.tape"),
            "--receipt-out",
            &receipt_path,
        ]));
        let receipt = fs::read_to_string(&receipt_path).unwrap();
        let events: u64 = receipt_field(&receipt, "modeled_binary_events")
            .parse()
            .unwrap();
        let result = decode_command(&[
            "--arm",
            "m1-chassis",
            "--item-index",
            "0",
            "--tape",
            &scratch.path("item.tape"),
            "--records",
            receipt_field(&receipt, "records"),
            "--modeled-binary-events",
            &(events + 1).to_string(),
            "--modeled-loss-q24",
            receipt_field(&receipt, "modeled_loss_q24"),
            "--raw-literal-bytes",
            receipt_field(&receipt, "raw_literal_bytes"),
            "--output",
            &scratch.path("out"),
            "--receipt-out",
            &scratch.path("out.receipt.json"),
        ]);
        assert!(matches!(result, Err(CommandError::Failure(_))));
        assert!(!Path::new(&scratch.path("out")).exists());
    }

    #[test]
    fn decode_rejects_the_wrong_arm_or_item_identity() {
        let scratch = Scratch::new();
        fs::write(scratch.path("item.ndjson"), corpus()).unwrap();
        let receipt_path = scratch.path("receipt.json");
        unwrap_message(encode_command(&[
            "--arm",
            "full",
            "--item-index",
            "2",
            "--input",
            &scratch.path("item.ndjson"),
            "--tape-out",
            &scratch.path("item.tape"),
            "--receipt-out",
            &receipt_path,
        ]));
        let receipt = fs::read_to_string(&receipt_path).unwrap();
        for (arm, item) in [("full-minus-m3", "2"), ("full", "1")] {
            let result = decode_command(&[
                "--arm",
                arm,
                "--item-index",
                item,
                "--tape",
                &scratch.path("item.tape"),
                "--records",
                receipt_field(&receipt, "records"),
                "--modeled-binary-events",
                receipt_field(&receipt, "modeled_binary_events"),
                "--modeled-loss-q24",
                receipt_field(&receipt, "modeled_loss_q24"),
                "--raw-literal-bytes",
                receipt_field(&receipt, "raw_literal_bytes"),
                "--output",
                &scratch.path("out"),
                "--receipt-out",
                &scratch.path("out.receipt.json"),
            ]);
            assert!(matches!(result, Err(CommandError::Failure(_))));
        }
    }

    #[test]
    fn outputs_are_never_clobbered_without_force() {
        let scratch = Scratch::new();
        fs::write(scratch.path("item.ndjson"), corpus()).unwrap();
        fs::write(scratch.path("item.tape"), b"existing").unwrap();
        let result = encode_command(&[
            "--arm",
            "m1-chassis",
            "--item-index",
            "0",
            "--input",
            &scratch.path("item.ndjson"),
            "--tape-out",
            &scratch.path("item.tape"),
            "--receipt-out",
            &scratch.path("receipt.json"),
        ]);
        assert!(matches!(result, Err(CommandError::Failure(_))));
        assert_eq!(fs::read(scratch.path("item.tape")).unwrap(), b"existing");

        unwrap_message(encode_command(&[
            "--arm",
            "m1-chassis",
            "--item-index",
            "0",
            "--input",
            &scratch.path("item.ndjson"),
            "--tape-out",
            &scratch.path("item.tape"),
            "--receipt-out",
            &scratch.path("receipt.json"),
            "--force",
        ]));
        assert_ne!(fs::read(scratch.path("item.tape")).unwrap(), b"existing");
    }

    #[test]
    fn a_failed_run_never_leaves_a_tape_without_its_receipt() {
        let scratch = Scratch::new();
        fs::write(scratch.path("item.ndjson"), corpus()).unwrap();
        // The receipt destination already exists and --force is absent, so the
        // command fails after the tape was written; the tape must be removed.
        fs::write(scratch.path("receipt.json"), b"occupied").unwrap();
        let result = encode_command(&[
            "--arm",
            "m1-chassis",
            "--item-index",
            "0",
            "--input",
            &scratch.path("item.ndjson"),
            "--tape-out",
            &scratch.path("item.tape"),
            "--receipt-out",
            &scratch.path("receipt.json"),
        ]);
        assert!(matches!(result, Err(CommandError::Failure(_))));
        assert!(!Path::new(&scratch.path("item.tape")).exists());
        assert_eq!(fs::read(scratch.path("receipt.json")).unwrap(), b"occupied");
    }

    #[test]
    fn a_zero_segment_interval_is_rejected_by_the_library_too() {
        let table = LossTable::generate();
        for arm in [s0::Arm::RawO3, s0::Arm::M1Chassis, s0::Arm::Full] {
            assert_eq!(
                s0::encode_arm_item(arm, b"{\"a\":1}\n", &table, 0, Some(0)),
                Err(s0::ChassisError::InvalidSegmentInterval),
                "{}",
                arm.name()
            );
        }
    }

    // A corpus large enough to force an SSE 17-bit bucket collision that the
    // 18th bit resolves, so the refined profile actually moves the mixer loss.
    fn diverging_corpus() -> Vec<u8> {
        let mut source = Vec::new();
        for index in 0..1_500_u32 {
            let mix = index.wrapping_mul(2_654_435_761);
            source.extend_from_slice(
                format!(
                    "{{\"id\":{},\"ts\":\"2026-07-22T{:02}:{:02}:{:02}Z\",\"session\":\"s{}\",\"path\":\"/api/v/{}/resource/{}\",\"tag\":\"{:08x}\",\"status\":{}}}\n",
                    100_000 + index,
                    index % 24,
                    index % 60,
                    (index * 7) % 60,
                    index % 997,
                    index % 733,
                    index % 521,
                    mix,
                    200 + (index % 5)
                )
                .as_bytes(),
            );
        }
        source.extend_from_slice(b"{ bad }\n");
        source
    }

    fn encode_with_bits(scratch: &Scratch, arm: &str, bits: Option<&str>) -> String {
        let label = bits.unwrap_or("default");
        let tape = scratch.path(&format!("{arm}-{label}.tape"));
        let receipt_path = scratch.path(&format!("{arm}-{label}.receipt.json"));
        let mut command = vec![
            "--arm",
            arm,
            "--item-index",
            "0",
            "--input",
            "PLACEHOLDER",
            "--tape-out",
            "PLACEHOLDER",
            "--receipt-out",
            "PLACEHOLDER",
            "--segment-bytes",
            "256",
        ];
        let input = scratch.path("item.ndjson");
        command[5] = &input;
        command[7] = &tape;
        command[9] = &receipt_path;
        let bits_owned;
        if let Some(value) = bits {
            bits_owned = value.to_owned();
            command.push("--sse-bucket-bits");
            command.push(&bits_owned);
        }
        unwrap_message(encode_command(&command));
        fs::read_to_string(&receipt_path).unwrap()
    }

    #[test]
    fn default_sse_bucket_bits_are_seventeen_and_recorded() {
        let scratch = Scratch::new();
        fs::write(scratch.path("item.ndjson"), corpus()).unwrap();
        let receipt = encode_with_bits(&scratch, "full", None);
        assert_eq!(receipt_field(&receipt, "sse_bucket_bits"), "17");
        // The default omits the flag; an explicit 17 must be byte-identical.
        let explicit = encode_with_bits(&scratch, "full", Some("17"));
        assert_eq!(receipt, explicit);
    }

    #[test]
    fn refined_bits_hold_the_tape_and_move_only_mixer_loss() {
        let scratch = Scratch::new();
        fs::write(scratch.path("item.ndjson"), diverging_corpus()).unwrap();
        // A mixer arm: refined bits keep the tape SHA but change the loss.
        let base = encode_with_bits(&scratch, "full", Some("17"));
        let refined = encode_with_bits(&scratch, "full", Some("18"));
        assert_eq!(receipt_field(&refined, "sse_bucket_bits"), "18");
        assert_eq!(
            receipt_field(&base, "tape_sha256"),
            receipt_field(&refined, "tape_sha256")
        );
        assert_ne!(
            receipt_field(&base, "modeled_loss_q24"),
            receipt_field(&refined, "modeled_loss_q24")
        );
        // A non-mixer arm ignores the flag entirely: identical receipt except
        // the recorded sse_bucket_bits field.
        let raw_base = encode_with_bits(&scratch, "m1-m2", Some("17"));
        let raw_refined = encode_with_bits(&scratch, "m1-m2", Some("18"));
        assert_eq!(
            receipt_field(&raw_base, "modeled_loss_q24"),
            receipt_field(&raw_refined, "modeled_loss_q24")
        );
        assert_eq!(
            raw_base.replace("\"sse_bucket_bits\": 17", "\"sse_bucket_bits\": 18"),
            raw_refined
        );
    }

    #[test]
    fn decode_under_the_wrong_bits_fails_the_ledger_on_a_mixer_arm() {
        let scratch = Scratch::new();
        fs::write(scratch.path("item.ndjson"), diverging_corpus()).unwrap();
        unwrap_message(encode_command(&[
            "--arm",
            "full",
            "--item-index",
            "0",
            "--input",
            &scratch.path("item.ndjson"),
            "--tape-out",
            &scratch.path("item.tape"),
            "--receipt-out",
            &scratch.path("receipt.json"),
            "--sse-bucket-bits",
            "18",
        ]));
        let receipt = fs::read_to_string(scratch.path("receipt.json")).unwrap();
        let decode_args = |bits: &str, out: &str, rcpt: &str| {
            decode_command(&[
                "--arm",
                "full",
                "--item-index",
                "0",
                "--tape",
                &scratch.path("item.tape"),
                "--records",
                receipt_field(&receipt, "records"),
                "--modeled-binary-events",
                receipt_field(&receipt, "modeled_binary_events"),
                "--modeled-loss-q24",
                receipt_field(&receipt, "modeled_loss_q24"),
                "--raw-literal-bytes",
                receipt_field(&receipt, "raw_literal_bytes"),
                "--output",
                &scratch.path(out),
                "--receipt-out",
                &scratch.path(rcpt),
                "--sse-bucket-bits",
                bits,
            ])
        };
        // Matching bits reproduce the source; the base bits reproduce a
        // different loss and fail the ledger equality.
        unwrap_message(decode_args("18", "ok.out", "ok.receipt.json"));
        assert!(matches!(
            decode_args("17", "bad.out", "bad.receipt.json"),
            Err(CommandError::Failure(_))
        ));
        assert!(!Path::new(&scratch.path("bad.out")).exists());
    }

    #[test]
    fn an_out_of_range_bucket_bit_count_is_a_usage_error() {
        let scratch = Scratch::new();
        let bad = |bits: &str| {
            encode_command(&[
                "--arm",
                "full",
                "--item-index",
                "0",
                "--input",
                &scratch.path("item.ndjson"),
                "--tape-out",
                &scratch.path("item.tape"),
                "--receipt-out",
                &scratch.path("receipt.json"),
                "--sse-bucket-bits",
                bits,
            ])
        };
        // Rejected before the input is ever read.
        assert!(matches!(bad("16"), Err(CommandError::Usage(_))));
        assert!(matches!(bad("19"), Err(CommandError::Usage(_))));
        assert!(!Path::new(&scratch.path("item.tape")).exists());
    }

    #[test]
    fn usage_errors_are_reported_as_usage() {
        assert!(matches!(
            encode_command(&["--arm", "nope"]),
            Err(CommandError::Usage(_))
        ));
        assert!(matches!(
            encode_command(&["--arm", "full", "--segment-bytes", "0"]),
            Err(CommandError::Usage(_))
        ));
        assert!(matches!(
            encode_command(&["--arm", "full", "--segment-bytes", "8", "--no-segments"]),
            Err(CommandError::Usage(_))
        ));
        assert!(matches!(
            decode_command(&["--no-segments"]),
            Err(CommandError::Usage(_))
        ));
    }
}
