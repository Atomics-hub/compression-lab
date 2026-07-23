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

use moon::c3::{
    c3_declared_state_bytes, decode_c3_item_with_bits, encode_c3_item_with_bits_and_quarters,
    C3QuarterSnapshot, C3_ARM_ID,
};
use moon::c8::{
    c8_declared_state_bytes, decode_c8_item_with_bits, encode_c8_item_with_bits, C8_ARM_ID,
};
use moon::diagnose::{decompose_h1, DEFAULT_TOP_REGIONS};
use moon::h1::{
    decode_h1_item_with_bits, encode_h1_item_with_bits, h1_declared_state_bytes, H1_ARM_ID,
};
use moon::h6::{
    decode_h6_item_with_bits, encode_h6_item_with_bits, h6_declared_state_bytes, H6_ARM_ID,
};
use moon::h8::{
    decode_h8_item_with_bits, encode_h8_item_with_bits, h8_declared_state_bytes, H8_ARM_ID,
};
use moon::h9::{
    decode_h9_item_with_bits, encode_h9_item_with_bits, h9_declared_state_bytes, H9_ARM_ID,
};
use s0::{Ledger, LossTable, Tape, SSE_BASE_BUCKET_BITS, SSE_REFINED_BUCKET_BITS};
use sha2::{Digest, Sha256};
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::ExitCode;

const VERSION: &str = env!("CARGO_PKG_VERSION");
const EVIDENCE_STAGE: &str = "development_only_prescreen";

// Preregistered per-arm kill lines (draft cycle-1 §2), echoed verbatim into
// every receipt so the eventual kill/nominate report is mechanical. Data
// strings, not claims: no candidate, SOTA, exact-codec, or ratio assertion.
const H1_KILL_CRITERION: &str = "Kill if projected complete bytes exceed 1.10x local zpaq -m5 -B16 on at least two public snapshots at <=256 MiB declared state, OR peak decode RSS exceeds 512 MiB.";
// The draft wrote this baseline as "max(H1-alone, H5/M3-alone)"; helm deferred
// H5, so M3 is the cycle-1 reuse baseline and the line names M3 alone. This is
// the intentional recorded simplification, not a drift.
const H6_KILL_CRITERION: &str =
    "Kill if the hybrid does not beat max(H1-alone, M3-alone) by >= 3% on the public set.";
// Draft cycle-1 §2-H8 ("Kill if the frozen mixer loses to the adaptive mixer
// by > 2% on the unseen month"), phrased mechanically like the other arms:
// frozen-mixer bytes above 1.02x adaptive-H1 bytes on month B. Byte-identical
// to the runner's KILL_LINES entry.
const H8_KILL_CRITERION: &str = "Kill if frozen-mixer complete bytes exceed 1.02x adaptive H1 complete bytes on the unseen month.";
// H9 kill line, verbatim from draft cycle-1 §2-H9.
const H9_KILL_CRITERION: &str =
    "Kill if bounded-grammar size > 1.3x local ZPAQ-16MiB on the public set.";
const C3_KILL_CRITERION: &str = "Kill if C3 complete bytes are at least 0.97x H1 complete bytes on both public snapshots, OR any exactness, identity, ledger, unaccounted-state, 600-second wall, or 512 MiB decode-RSS gate fails.";
const C8_KILL_CRITERION: &str = "Kill if C8 complete bytes are at least 0.93x H1 complete bytes on both public snapshots, OR any exactness, identity, ledger, unaccounted-state, 600-second wall, or 512 MiB decode-RSS gate fails.";

/// The moon prescreen arms. Each wraps a moon arm's encode/decode, declared
/// state, and preregistered kill line so the kernel dispatches uniformly.
#[derive(Clone, Copy)]
enum MoonArm {
    C3LiveAdaptation,
    C8ExpertMixture,
    H1Floor,
    H6Hybrid,
    H8StaticMixer,
    H9Grammar,
}

const ARMS: [MoonArm; 6] = [
    MoonArm::C3LiveAdaptation,
    MoonArm::C8ExpertMixture,
    MoonArm::H1Floor,
    MoonArm::H6Hybrid,
    MoonArm::H8StaticMixer,
    MoonArm::H9Grammar,
];

impl MoonArm {
    fn from_name(name: &str) -> Option<Self> {
        match name {
            "c3-live-adaptation" => Some(Self::C3LiveAdaptation),
            "c8-expert-mixture" => Some(Self::C8ExpertMixture),
            "h1-floor" => Some(Self::H1Floor),
            "h6-hybrid" => Some(Self::H6Hybrid),
            "h8-static-mixer" => Some(Self::H8StaticMixer),
            "h9-grammar" => Some(Self::H9Grammar),
            _ => None,
        }
    }

    fn name(self) -> &'static str {
        match self {
            Self::C3LiveAdaptation => "c3-live-adaptation",
            Self::C8ExpertMixture => "c8-expert-mixture",
            Self::H1Floor => "h1-floor",
            Self::H6Hybrid => "h6-hybrid",
            Self::H8StaticMixer => "h8-static-mixer",
            Self::H9Grammar => "h9-grammar",
        }
    }

    fn id(self) -> u8 {
        match self {
            Self::C3LiveAdaptation => C3_ARM_ID,
            Self::C8ExpertMixture => C8_ARM_ID,
            Self::H1Floor => H1_ARM_ID,
            Self::H6Hybrid => H6_ARM_ID,
            Self::H8StaticMixer => H8_ARM_ID,
            Self::H9Grammar => H9_ARM_ID,
        }
    }

    fn kill_criterion(self) -> &'static str {
        match self {
            Self::C3LiveAdaptation => C3_KILL_CRITERION,
            Self::C8ExpertMixture => C8_KILL_CRITERION,
            Self::H1Floor => H1_KILL_CRITERION,
            Self::H6Hybrid => H6_KILL_CRITERION,
            Self::H8StaticMixer => H8_KILL_CRITERION,
            Self::H9Grammar => H9_KILL_CRITERION,
        }
    }

    fn declared_state_bytes(self, table: &LossTable, sse_bucket_bits: u32) -> usize {
        match self {
            Self::C3LiveAdaptation => c3_declared_state_bytes(table, sse_bucket_bits),
            Self::C8ExpertMixture => c8_declared_state_bytes(table, sse_bucket_bits),
            Self::H1Floor => h1_declared_state_bytes(table, sse_bucket_bits),
            Self::H6Hybrid => h6_declared_state_bytes(table, sse_bucket_bits),
            Self::H8StaticMixer => h8_declared_state_bytes(table, sse_bucket_bits),
            Self::H9Grammar => h9_declared_state_bytes(table, sse_bucket_bits),
        }
    }

    fn encode(
        self,
        source: &[u8],
        table: &LossTable,
        item_index: u8,
        sse_bucket_bits: u32,
    ) -> Result<(Tape, Ledger, Option<[C3QuarterSnapshot; 4]>), String> {
        match self {
            Self::C3LiveAdaptation => {
                encode_c3_item_with_bits_and_quarters(source, table, item_index, sse_bucket_bits)
                    .map(|(tape, ledger, quarters)| (tape, ledger, Some(quarters)))
                    .map_err(|error| error.to_string())
            }
            Self::C8ExpertMixture => {
                encode_c8_item_with_bits(source, table, item_index, sse_bucket_bits)
                    .map(|(tape, ledger)| (tape, ledger, None))
                    .map_err(|error| error.to_string())
            }
            Self::H1Floor => encode_h1_item_with_bits(source, table, item_index, sse_bucket_bits)
                .map(|(tape, ledger)| (tape, ledger, None))
                .map_err(|error| error.to_string()),
            Self::H6Hybrid => encode_h6_item_with_bits(source, table, item_index, sse_bucket_bits)
                .map(|(tape, ledger)| (tape, ledger, None))
                .map_err(|error| error.to_string()),
            Self::H8StaticMixer => {
                encode_h8_item_with_bits(source, table, item_index, sse_bucket_bits)
                    .map(|(tape, ledger)| (tape, ledger, None))
                    .map_err(|error| error.to_string())
            }
            Self::H9Grammar => encode_h9_item_with_bits(source, table, item_index, sse_bucket_bits)
                .map(|(tape, ledger)| (tape, ledger, None))
                .map_err(|error| error.to_string()),
        }
    }

    fn decode(
        self,
        tape: &Tape,
        expected_ledger: Ledger,
        table: &LossTable,
        item_index: u8,
        sse_bucket_bits: u32,
    ) -> Result<Vec<u8>, String> {
        match self {
            Self::C3LiveAdaptation => {
                decode_c3_item_with_bits(tape, expected_ledger, table, item_index, sse_bucket_bits)
                    .map_err(|error| error.to_string())
            }
            Self::C8ExpertMixture => {
                decode_c8_item_with_bits(tape, expected_ledger, table, item_index, sse_bucket_bits)
                    .map_err(|error| error.to_string())
            }
            Self::H1Floor => {
                decode_h1_item_with_bits(tape, expected_ledger, table, item_index, sse_bucket_bits)
                    .map_err(|error| error.to_string())
            }
            Self::H6Hybrid => {
                decode_h6_item_with_bits(tape, expected_ledger, table, item_index, sse_bucket_bits)
                    .map_err(|error| error.to_string())
            }
            Self::H8StaticMixer => {
                decode_h8_item_with_bits(tape, expected_ledger, table, item_index, sse_bucket_bits)
                    .map_err(|error| error.to_string())
            }
            Self::H9Grammar => {
                decode_h9_item_with_bits(tape, expected_ledger, table, item_index, sse_bucket_bits)
                    .map_err(|error| error.to_string())
            }
        }
    }
}

const HELP: &str = "clab-moon-kernel — moonshot cycle-1 prescreen accounting kernel

Usage:
  clab-moon-kernel arms
  clab-moon-kernel encode --arm c3-live-adaptation|c8-expert-mixture|h1-floor|h6-hybrid|h8-static-mixer|h9-grammar --item-index N --input PATH
                          --tape-out PATH --receipt-out PATH
                          [--sse-bucket-bits 17|18] [--force]
  clab-moon-kernel decode --arm c3-live-adaptation|c8-expert-mixture|h1-floor|h6-hybrid|h8-static-mixer|h9-grammar --item-index N --tape PATH
                          --records N --modeled-binary-events N
                          --modeled-loss-q24 N --raw-literal-bytes N
                          --output PATH --receipt-out PATH
                          [--sse-bucket-bits 17|18] [--force]
  clab-moon-kernel diagnose-h1 --item-index N --input PATH --report-out PATH
                          [--sse-bucket-bits 17|18] [--top-regions N] [--force]
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
            for arm in ARMS {
                println!("{} {}", arm.id(), arm.name());
            }
            ExitCode::SUCCESS
        }
        Some((&"encode", rest)) => run(encode_command(rest)),
        Some((&"decode", rest)) => run(decode_command(rest)),
        Some((&"diagnose-h1", rest)) => run(diagnose_h1_command(rest)),
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

fn parse_arm(name: &str) -> Result<MoonArm, CommandError> {
    MoonArm::from_name(name).ok_or_else(|| {
        usage(format!(
            "unknown arm: {name} (expected one of {})",
            ARMS.map(MoonArm::name).join(", ")
        ))
    })
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

fn quarter_json(quarters: Option<[C3QuarterSnapshot; 4]>) -> String {
    let Some(quarters) = quarters else {
        return "null".to_owned();
    };
    let mut previous_bytes = 0_u64;
    let mut previous_events = 0_u64;
    let mut previous_loss = 0_u64;
    let rows = quarters.map(|quarter| {
        let row = format!(
            "{{\"cumulative_source_bytes\": {}, \"delta_source_bytes\": {}, \"delta_modeled_binary_events\": {}, \"delta_modeled_loss_q24\": {}}}",
            quarter.source_bytes,
            quarter.source_bytes - previous_bytes,
            quarter.modeled_binary_events - previous_events,
            quarter.modeled_loss_q24 - previous_loss,
        );
        previous_bytes = quarter.source_bytes;
        previous_events = quarter.modeled_binary_events;
        previous_loss = quarter.modeled_loss_q24;
        row
    });
    format!("[{}]", rows.join(", "))
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
    let arm = parse_arm(options.take("arm")?)?;
    let item_index: u8 = parse_number("item-index", options.take("item-index")?)?;
    let input = options.take("input")?;
    let tape_out = options.take("tape-out")?;
    let receipt_out = options.take("receipt-out")?;
    let sse_bucket_bits = parse_sse_bucket_bits(&options)?;

    let source = read_bytes(input)?;
    let table = LossTable::generate();
    let (tape, ledger, quarters) = arm
        .encode(&source, &table, item_index, sse_bucket_bits)
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
    let decoded = arm
        .decode(&reread, ledger, &table, item_index, sse_bucket_bits)
        .map_err(|error| failure(format!("confirmation decode failed: {error}")))?;
    if decoded != source {
        return Err(failure("confirmation decode did not reproduce the source"));
    }

    let source_bytes = source.len() as u64;
    let declared_state_bytes = arm.declared_state_bytes(&table, sse_bucket_bits);
    let receipt = format!(
        "{{\n  \"schema\": \"clab-moon-kernel-encode-receipt-v1\",\n  \"kernel_version\": \"{VERSION}\",\n  \"evidence_stage\": \"{EVIDENCE_STAGE}\",\n  \"arm\": \"{}\",\n  \"arm_id\": {},\n  \"item_index\": {item_index},\n  \"source_bytes\": {source_bytes},\n  \"source_sha256\": \"{}\",\n  \"tape_bytes\": {},\n  \"tape_sha256\": \"{}\",\n  \"sse_bucket_bits\": {sse_bucket_bits},\n  \"declared_model_state_bytes\": {declared_state_bytes},\n  \"ledger\": {},\n  \"item_projection\": {},\n  \"quarter_diagnostics_q24_scale\": 16777216,\n  \"quarter_diagnostics\": {},\n  \"predicted_kill_criterion\": \"{}\",\n  \"decoded_sha256\": \"{}\",\n  \"decode_matches_source\": true\n}}\n",
        arm.name(),
        arm.id(),
        sha256_hex(&source),
        tape_bytes.len(),
        sha256_hex(&tape_bytes),
        ledger_json(ledger),
        projection_json(ledger, source_bytes)?,
        quarter_json(quarters),
        arm.kill_criterion(),
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
    let decoded = arm
        .decode(&tape, expected_ledger, &table, item_index, sse_bucket_bits)
        .map_err(|error| failure(format!("decode failed: {error}")))?;
    write_output(output, &decoded, options.force)?;
    let mut written_output = WrittenOutput::pending(output);

    let receipt = format!(
        "{{\n  \"schema\": \"clab-moon-kernel-decode-receipt-v1\",\n  \"kernel_version\": \"{VERSION}\",\n  \"evidence_stage\": \"{EVIDENCE_STAGE}\",\n  \"arm\": \"{}\",\n  \"arm_id\": {},\n  \"item_index\": {item_index},\n  \"tape_bytes\": {},\n  \"tape_sha256\": \"{}\",\n  \"sse_bucket_bits\": {sse_bucket_bits},\n  \"ledger\": {},\n  \"decoded_bytes\": {},\n  \"decoded_sha256\": \"{}\"\n}}\n",
        arm.name(),
        arm.id(),
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

/// Read-only H1 loss-decomposition diagnostic. It never writes a tape and never
/// touches the encode/decode receipt paths; it emits a single deterministic
/// decomposition report for one item. The `decompose_h1` observer re-runs the
/// canonical H1 arm and fails closed if its tape or ledger diverges by a byte,
/// so this command can never report a decomposition of a tape the arm would not
/// have produced.
fn diagnose_h1_command(arguments: &[&str]) -> Result<(), CommandError> {
    let options = parse_options(
        arguments,
        &[
            "item-index",
            "input",
            "report-out",
            "sse-bucket-bits",
            "top-regions",
        ],
    )?;
    let item_index: u8 = parse_number("item-index", options.take("item-index")?)?;
    let input = options.take("input")?;
    let report_out = options.take("report-out")?;
    let sse_bucket_bits = parse_sse_bucket_bits(&options)?;
    let top_regions: usize = match options.take_optional("top-regions") {
        None => DEFAULT_TOP_REGIONS,
        Some(value) => parse_number("top-regions", value)?,
    };

    let source = read_bytes(input)?;
    let table = LossTable::generate();
    let decomposition = decompose_h1(&source, &table, item_index, sse_bucket_bits, top_regions)
        .map_err(|error| failure(format!("loss decomposition failed: {error}")))?;

    // Re-encode once to recover the exact tape SHA for provenance; the observer
    // already proved this tape is byte-identical to the one it decomposed.
    let (tape, _) =
        moon::h1::encode_h1_item_with_bits(&source, &table, item_index, sse_bucket_bits)
            .map_err(|error| failure(format!("tape hash re-encode failed: {error}")))?;
    let report =
        decomposition.to_json(VERSION, &sha256_hex(&source), &sha256_hex(&tape.to_bytes()));
    write_output(report_out, report.as_bytes(), options.force)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicU64, Ordering};

    const ARM_NAME: &str = "h1-floor";

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
            "119947264"
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
    fn the_h6_arm_encodes_decodes_and_reports_its_own_state_and_kill_line() {
        let scratch = Scratch::new();
        // Heavy exact-duplicate lines so the reuse layer fires.
        let mut source = Vec::new();
        for _ in 0..30 {
            source.extend_from_slice(b"{\"level\":\"info\",\"msg\":\"ready\"}\n");
        }
        fs::write(scratch.path("item.ndjson"), &source).unwrap();
        let receipt_path = scratch.path("h6.receipt.json");
        unwrap_message(encode_command(&[
            "--arm",
            "h6-hybrid",
            "--item-index",
            "2",
            "--input",
            &scratch.path("item.ndjson"),
            "--tape-out",
            &scratch.path("h6.tape"),
            "--receipt-out",
            &receipt_path,
        ]));
        let receipt = fs::read_to_string(&receipt_path).unwrap();
        assert_eq!(receipt_field(&receipt, "arm"), "h6-hybrid");
        assert_eq!(receipt_field(&receipt, "arm_id"), "101");
        assert_eq!(receipt_field(&receipt, "decode_matches_source"), "true");
        assert_eq!(
            receipt_field(&receipt, "declared_model_state_bytes"),
            "148654078"
        );
        assert!(receipt.contains("beat max(H1-alone, M3-alone) by >= 3%"));

        let output = scratch.path("h6.decoded");
        unwrap_message(decode_command(&[
            "--arm",
            "h6-hybrid",
            "--item-index",
            "2",
            "--tape",
            &scratch.path("h6.tape"),
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
            &scratch.path("h6.decode-receipt.json"),
        ]));
        assert_eq!(fs::read(&output).unwrap(), source);
    }

    #[test]
    fn the_h8_arm_encodes_decodes_and_reports_its_own_state_and_kill_line() {
        let scratch = Scratch::new();
        let source = corpus();
        fs::write(scratch.path("item.ndjson"), &source).unwrap();
        let receipt_path = scratch.path("h8.receipt.json");
        unwrap_message(encode_command(&[
            "--arm",
            "h8-static-mixer",
            "--item-index",
            "5",
            "--input",
            &scratch.path("item.ndjson"),
            "--tape-out",
            &scratch.path("h8.tape"),
            "--receipt-out",
            &receipt_path,
        ]));
        let receipt = fs::read_to_string(&receipt_path).unwrap();
        assert_eq!(receipt_field(&receipt, "arm"), "h8-static-mixer");
        assert_eq!(receipt_field(&receipt, "arm_id"), "103");
        assert_eq!(receipt_field(&receipt, "decode_matches_source"), "true");
        assert_eq!(
            receipt_field(&receipt, "declared_model_state_bytes"),
            "109314564"
        );
        assert!(receipt.contains("exceed 1.02x adaptive H1 complete bytes on the unseen month"));

        let output = scratch.path("h8.decoded");
        unwrap_message(decode_command(&[
            "--arm",
            "h8-static-mixer",
            "--item-index",
            "5",
            "--tape",
            &scratch.path("h8.tape"),
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
            &scratch.path("h8.decode-receipt.json"),
        ]));
        assert_eq!(fs::read(&output).unwrap(), source);
    }

    #[test]
    fn the_h9_arm_encodes_decodes_and_reports_its_own_state_and_kill_line() {
        let scratch = Scratch::new();
        let mut source = Vec::new();
        for _ in 0..40 {
            source.extend_from_slice(b"{\"event\":\"heartbeat\",\"ok\":true}\n");
        }
        fs::write(scratch.path("item.ndjson"), &source).unwrap();
        let receipt_path = scratch.path("h9.receipt.json");
        unwrap_message(encode_command(&[
            "--arm",
            "h9-grammar",
            "--item-index",
            "1",
            "--input",
            &scratch.path("item.ndjson"),
            "--tape-out",
            &scratch.path("h9.tape"),
            "--receipt-out",
            &receipt_path,
        ]));
        let receipt = fs::read_to_string(&receipt_path).unwrap();
        assert_eq!(receipt_field(&receipt, "arm"), "h9-grammar");
        assert_eq!(receipt_field(&receipt, "arm_id"), "102");
        assert_eq!(receipt_field(&receipt, "decode_matches_source"), "true");
        assert_eq!(
            receipt_field(&receipt, "declared_model_state_bytes"),
            "25297254"
        );
        assert!(receipt.contains("bounded-grammar size > 1.3x local ZPAQ-16MiB"));

        let output = scratch.path("h9.decoded");
        unwrap_message(decode_command(&[
            "--arm",
            "h9-grammar",
            "--item-index",
            "1",
            "--tape",
            &scratch.path("h9.tape"),
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
            &scratch.path("h9.decode-receipt.json"),
        ]));
        assert_eq!(fs::read(&output).unwrap(), source);
    }

    #[test]
    fn c3_encodes_decodes_and_binds_state_and_kill_line() {
        let scratch = Scratch::new();
        let source = corpus();
        fs::write(scratch.path("item.ndjson"), &source).unwrap();
        let receipt_path = scratch.path("c3.receipt.json");
        unwrap_message(encode_command(&[
            "--arm",
            "c3-live-adaptation",
            "--item-index",
            "7",
            "--input",
            &scratch.path("item.ndjson"),
            "--tape-out",
            &scratch.path("c3.tape"),
            "--receipt-out",
            &receipt_path,
        ]));
        let receipt = fs::read_to_string(&receipt_path).unwrap();
        assert_eq!(receipt_field(&receipt, "arm"), "c3-live-adaptation");
        assert_eq!(receipt_field(&receipt, "arm_id"), "104");
        assert_eq!(receipt_field(&receipt, "decode_matches_source"), "true");
        assert_eq!(
            receipt_field(&receipt, "declared_model_state_bytes"),
            "126238720"
        );
        assert!(receipt.contains(C3_KILL_CRITERION));

        let output = scratch.path("c3.decoded");
        unwrap_message(decode_command(&[
            "--arm",
            "c3-live-adaptation",
            "--item-index",
            "7",
            "--tape",
            &scratch.path("c3.tape"),
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
            &scratch.path("c3.decode-receipt.json"),
        ]));
        assert_eq!(fs::read(&output).unwrap(), source);
    }

    #[test]
    fn arms_lists_every_moon_arm() {
        assert_eq!(
            MoonArm::from_name("c3-live-adaptation").map(MoonArm::id),
            Some(104)
        );
        assert_eq!(MoonArm::from_name("h1-floor").map(MoonArm::id), Some(100));
        assert_eq!(MoonArm::from_name("h6-hybrid").map(MoonArm::id), Some(101));
        assert_eq!(
            MoonArm::from_name("h8-static-mixer").map(MoonArm::id),
            Some(103)
        );
        assert_eq!(MoonArm::from_name("h9-grammar").map(MoonArm::id), Some(102));
        assert_eq!(
            MoonArm::from_name("c8-expert-mixture").map(MoonArm::id),
            Some(107)
        );
        assert!(MoonArm::from_name("nope").is_none());
        assert_eq!(ARMS.len(), 6);
    }

    #[test]
    fn c8_encodes_decodes_and_binds_state_and_kill_line() {
        let scratch = Scratch::new();
        let source = corpus();
        fs::write(scratch.path("item.ndjson"), &source).unwrap();
        let receipt_path = scratch.path("c8.receipt.json");
        unwrap_message(encode_command(&[
            "--arm",
            "c8-expert-mixture",
            "--item-index",
            "6",
            "--input",
            &scratch.path("item.ndjson"),
            "--tape-out",
            &scratch.path("c8.tape"),
            "--receipt-out",
            &receipt_path,
        ]));
        let receipt = fs::read_to_string(&receipt_path).unwrap();
        assert_eq!(receipt_field(&receipt, "arm"), "c8-expert-mixture");
        assert_eq!(receipt_field(&receipt, "arm_id"), "107");
        assert_eq!(receipt_field(&receipt, "decode_matches_source"), "true");
        assert_eq!(
            receipt_field(&receipt, "declared_model_state_bytes"),
            "119963648"
        );
        assert!(receipt.contains(C8_KILL_CRITERION));
        assert!(receipt.contains("at least 0.93x H1 complete bytes"));

        let output = scratch.path("c8.decoded");
        unwrap_message(decode_command(&[
            "--arm",
            "c8-expert-mixture",
            "--item-index",
            "6",
            "--tape",
            &scratch.path("c8.tape"),
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
            &scratch.path("c8.decode-receipt.json"),
        ]));
        assert_eq!(fs::read(&output).unwrap(), source);
    }

    #[test]
    fn diagnose_h1_emits_a_deterministic_decomposition_report() {
        let scratch = Scratch::new();
        let source = corpus();
        fs::write(scratch.path("item.ndjson"), &source).unwrap();

        let run = |name: &str| {
            let report_path = scratch.path(name);
            unwrap_message(diagnose_h1_command(&[
                "--item-index",
                "4",
                "--input",
                &scratch.path("item.ndjson"),
                "--report-out",
                &report_path,
                "--top-regions",
                "8",
            ]));
            fs::read_to_string(&report_path).unwrap()
        };
        let first = run("a.report.json");
        let second = run("b.report.json");
        assert_eq!(first, second, "report must be deterministic");
        assert_eq!(
            receipt_field(&first, "schema"),
            "clab-moon-h1-loss-decomposition-v1"
        );
        assert_eq!(receipt_field(&first, "arm"), "h1-floor");
        assert_eq!(receipt_field(&first, "evidence_stage"), EVIDENCE_STAGE);
        assert_eq!(receipt_field(&first, "item_index"), "4");
        // The report's tape SHA matches an independent H1 encode of the source.
        let table = LossTable::generate();
        let (tape, _) =
            moon::h1::encode_h1_item_with_bits(&source, &table, 4, SSE_BASE_BUCKET_BITS).unwrap();
        assert_eq!(
            receipt_field(&first, "tape_sha256"),
            sha256_hex(&tape.to_bytes())
        );
        assert!(first.contains("\"primary_partition\""));
        assert!(first.contains("\"top_regions\""));
        assert!(first.contains("\"repeat_candidate\""));
    }

    #[test]
    fn diagnose_h1_never_clobbers_without_force() {
        let scratch = Scratch::new();
        fs::write(scratch.path("item.ndjson"), corpus()).unwrap();
        fs::write(scratch.path("report.json"), b"existing").unwrap();
        let result = diagnose_h1_command(&[
            "--item-index",
            "0",
            "--input",
            &scratch.path("item.ndjson"),
            "--report-out",
            &scratch.path("report.json"),
        ]);
        assert!(matches!(result, Err(CommandError::Failure(_))));
        assert_eq!(fs::read(scratch.path("report.json")).unwrap(), b"existing");
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
