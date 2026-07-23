//! Deterministic accounting CLI for the moonshot cycle-1 prescreen harness.
//!
//! Development-only prescreen infrastructure (Lane 2, the Pareto moonshot), not
//! a product codec. `encode` charges the H1 floor arm on one item, writes the
//! exact modeled-bit tape, immediately re-decodes the written tape bytes
//! through the independent decoder ledger, and emits a deterministic JSON
//! receipt with the per-item projection and the declared model-state figure.
//! `decode` reproduces the exact source from a tape plus its expected ledger.
//! Every receipt is content-derived (no paths, timestamps, or host identity)
//! and carries a `development_only_prescreen` evidence ceiling: no candidate,
//! SOTA, exact-codec, or ratio claims. Corpora are synthetic or public only;
//! this kernel never reads licensed development items.

#[path = "../s0/mod.rs"]
pub mod s0;

#[path = "../moon/mod.rs"]
pub mod moon;

use moon::h1::{
    decode_h1_item_with_bits, encode_h1_item_with_bits, h1_declared_state_bytes, H1_ARM_ID,
};
use s0::{Ledger, LossTable, Tape, SSE_BASE_BUCKET_BITS, SSE_REFINED_BUCKET_BITS};
use sha2::{Digest, Sha256};
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::ExitCode;

const VERSION: &str = env!("CARGO_PKG_VERSION");
const EVIDENCE_STAGE: &str = "development_only_prescreen";
const ARM_NAME: &str = "h1-floor";
// The preregistered H1 kill line (draft cycle-1 §2), echoed verbatim into every
// receipt so the eventual kill/nominate report is mechanical. It is a data
// string, not a claim: no candidate, SOTA, exact-codec, or ratio assertion.
const H1_KILL_CRITERION: &str = "Kill if projected complete bytes exceed 1.10x local zpaq -m5 -B16 on at least two public snapshots at <=256 MiB declared state, OR peak decode RSS exceeds 512 MiB.";

const HELP: &str = "clab-moon-kernel — moonshot cycle-1 prescreen accounting kernel

Usage:
  clab-moon-kernel arms
  clab-moon-kernel encode --arm h1-floor --item-index N --input PATH
                          --tape-out PATH --receipt-out PATH
                          [--sse-bucket-bits 17|18] [--force]
  clab-moon-kernel decode --arm h1-floor --item-index N --tape PATH
                          --records N --modeled-binary-events N
                          --modeled-loss-q24 N --raw-literal-bytes N
                          --output PATH --receipt-out PATH
                          [--sse-bucket-bits 17|18] [--force]
  clab-moon-kernel --help
  clab-moon-kernel --version
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
            println!("clab-moon-kernel {VERSION}");
            ExitCode::SUCCESS
        }
        Some((&"arms", [])) => {
            println!("{H1_ARM_ID} {ARM_NAME}");
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
            eprintln!("clab-moon-kernel: {message}");
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

fn parse_arm(name: &str) -> Result<(), CommandError> {
    if name == ARM_NAME {
        Ok(())
    } else {
        Err(usage(format!("unknown arm: {name} (expected {ARM_NAME})")))
    }
}

fn parse_number<T: std::str::FromStr>(name: &str, value: &str) -> Result<T, CommandError> {
    value
        .parse()
        .map_err(|_| usage(format!("invalid --{name}: {value}")))
}

/// Selects the SSE capacity profile. Only the base (17) and the single
/// predeclared refined (18) counts are accepted; an omitted flag reproduces
/// the base profile.
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

fn encode_command(arguments: &[&str]) -> Result<(), CommandError> {
    let options = parse_options(
        arguments,
        &[
            "arm",
            "item-index",
            "input",
            "tape-out",
            "receipt-out",
            "sse-bucket-bits",
        ],
    )?;
    parse_arm(options.take("arm")?)?;
    let item_index: u8 = parse_number("item-index", options.take("item-index")?)?;
    let input = options.take("input")?;
    let tape_out = options.take("tape-out")?;
    let receipt_out = options.take("receipt-out")?;
    let sse_bucket_bits = parse_sse_bucket_bits(&options)?;

    let source = read_bytes(input)?;
    let table = LossTable::generate();
    let (tape, ledger) = encode_h1_item_with_bits(&source, &table, item_index, sse_bucket_bits)
        .map_err(|error| failure(format!("encode failed: {error}")))?;
    let tape_bytes = tape.to_bytes();
    write_output(tape_out, &tape_bytes, options.force)?;
    let mut written_tape = WrittenOutput::pending(tape_out);

    // Confirmation decode from the exact written bytes through the independent
    // decoder ledger; the receipt only reports a decode that reproduced the
    // source byte-for-byte.
    let written = read_bytes(tape_out)?;
    let reread = Tape::from_bytes(&written)
        .map_err(|error| failure(format!("written tape failed to parse: {error}")))?;
    let decoded = decode_h1_item_with_bits(&reread, ledger, &table, item_index, sse_bucket_bits)
        .map_err(|error| failure(format!("confirmation decode failed: {error}")))?;
    if decoded != source {
        return Err(failure("confirmation decode did not reproduce the source"));
    }

    let source_bytes = source.len() as u64;
    let declared_state_bytes = h1_declared_state_bytes(&table, sse_bucket_bits);
    let receipt = format!(
        "{{\n  \"schema\": \"clab-moon-kernel-encode-receipt-v1\",\n  \"kernel_version\": \"{VERSION}\",\n  \"evidence_stage\": \"{EVIDENCE_STAGE}\",\n  \"arm\": \"{ARM_NAME}\",\n  \"arm_id\": {H1_ARM_ID},\n  \"item_index\": {item_index},\n  \"source_bytes\": {source_bytes},\n  \"source_sha256\": \"{}\",\n  \"tape_bytes\": {},\n  \"tape_sha256\": \"{}\",\n  \"sse_bucket_bits\": {sse_bucket_bits},\n  \"declared_model_state_bytes\": {declared_state_bytes},\n  \"ledger\": {},\n  \"item_projection\": {},\n  \"predicted_kill_criterion\": \"{H1_KILL_CRITERION}\",\n  \"decoded_sha256\": \"{}\",\n  \"decode_matches_source\": true\n}}\n",
        sha256_hex(&source),
        tape_bytes.len(),
        sha256_hex(&tape_bytes),
        ledger_json(ledger),
        projection_json(ledger, source_bytes)?,
        sha256_hex(&decoded),
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
    parse_arm(options.take("arm")?)?;
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
    let decoded =
        decode_h1_item_with_bits(&tape, expected_ledger, &table, item_index, sse_bucket_bits)
            .map_err(|error| failure(format!("decode failed: {error}")))?;
    write_output(output, &decoded, options.force)?;
    let mut written_output = WrittenOutput::pending(output);

    let receipt = format!(
        "{{\n  \"schema\": \"clab-moon-kernel-decode-receipt-v1\",\n  \"kernel_version\": \"{VERSION}\",\n  \"evidence_stage\": \"{EVIDENCE_STAGE}\",\n  \"arm\": \"{ARM_NAME}\",\n  \"arm_id\": {H1_ARM_ID},\n  \"item_index\": {item_index},\n  \"tape_bytes\": {},\n  \"tape_sha256\": \"{}\",\n  \"sse_bucket_bits\": {sse_bucket_bits},\n  \"ledger\": {},\n  \"decoded_bytes\": {},\n  \"decoded_sha256\": \"{}\"\n}}\n",
        tape_bytes.len(),
        sha256_hex(&tape_bytes),
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
                "clab-moon-kernel-test-{}-{serial}",
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

        let tape = scratch.path("h1.tape");
        let receipt_path = scratch.path("h1.receipt.json");
        unwrap_message(encode_command(&[
            "--arm",
            ARM_NAME,
            "--item-index",
            "1",
            "--input",
            &scratch.path("item.ndjson"),
            "--tape-out",
            &tape,
            "--receipt-out",
            &receipt_path,
        ]));

        let receipt = fs::read_to_string(&receipt_path).unwrap();
        assert_eq!(receipt_field(&receipt, "arm"), ARM_NAME);
        assert_eq!(receipt_field(&receipt, "evidence_stage"), EVIDENCE_STAGE);
        assert_eq!(receipt_field(&receipt, "decode_matches_source"), "true");
        assert_eq!(
            receipt_field(&receipt, "source_sha256"),
            sha256_hex(&source)
        );
        assert_eq!(
            receipt_field(&receipt, "declared_model_state_bytes"),
            "119799808"
        );

        let output = scratch.path("h1.decoded");
        let decode_receipt_path = scratch.path("h1.decode-receipt.json");
        unwrap_message(decode_command(&[
            "--arm",
            ARM_NAME,
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

    #[test]
    fn receipts_are_deterministic_across_repeat_runs() {
        let scratch = Scratch::new();
        fs::write(scratch.path("item.ndjson"), corpus()).unwrap();
        let mut receipts = Vec::new();
        for run in 0..2 {
            let receipt_path = scratch.path(&format!("run{run}.receipt.json"));
            unwrap_message(encode_command(&[
                "--arm",
                ARM_NAME,
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
            ARM_NAME,
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
            ARM_NAME,
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
    fn refined_bits_hold_the_tape_and_grow_declared_state() {
        let scratch = Scratch::new();
        fs::write(scratch.path("item.ndjson"), corpus()).unwrap();
        let encode = |bits: &str| {
            let receipt = scratch.path(&format!("r{bits}.receipt.json"));
            unwrap_message(encode_command(&[
                "--arm",
                ARM_NAME,
                "--item-index",
                "0",
                "--input",
                &scratch.path("item.ndjson"),
                "--tape-out",
                &scratch.path(&format!("t{bits}.tape")),
                "--receipt-out",
                &receipt,
                "--sse-bucket-bits",
                bits,
            ]));
            fs::read_to_string(&receipt).unwrap()
        };
        let base = encode("17");
        let refined = encode("18");
        // The SSE capacity holds the tape identical; only the declared model
        // state grows with the larger SSE table.
        assert_eq!(
            receipt_field(&base, "tape_sha256"),
            receipt_field(&refined, "tape_sha256")
        );
        assert_eq!(receipt_field(&refined, "sse_bucket_bits"), "18");
        let base_state: u64 = receipt_field(&base, "declared_model_state_bytes")
            .parse()
            .unwrap();
        let refined_state: u64 = receipt_field(&refined, "declared_model_state_bytes")
            .parse()
            .unwrap();
        assert!(refined_state > base_state);
    }

    #[test]
    fn outputs_are_never_clobbered_without_force() {
        let scratch = Scratch::new();
        fs::write(scratch.path("item.ndjson"), corpus()).unwrap();
        fs::write(scratch.path("item.tape"), b"existing").unwrap();
        let result = encode_command(&[
            "--arm",
            ARM_NAME,
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
    }

    #[test]
    fn a_failed_run_never_leaves_a_tape_without_its_receipt() {
        let scratch = Scratch::new();
        fs::write(scratch.path("item.ndjson"), corpus()).unwrap();
        fs::write(scratch.path("receipt.json"), b"occupied").unwrap();
        let result = encode_command(&[
            "--arm",
            ARM_NAME,
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
    fn usage_errors_are_reported_as_usage() {
        assert!(matches!(
            encode_command(&["--arm", "nope"]),
            Err(CommandError::Usage(_))
        ));
        assert!(matches!(
            encode_command(&[
                "--arm",
                ARM_NAME,
                "--item-index",
                "0",
                "--sse-bucket-bits",
                "16"
            ]),
            Err(CommandError::Usage(_))
        ));
        assert!(matches!(
            decode_command(&["--arm", "h1-floor", "--unknown", "1"]),
            Err(CommandError::Usage(_))
        ));
    }
}
