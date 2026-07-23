//! Offline trainer for the H8 static-mixer weight vector.
//!
//! Development-only prescreen infrastructure (Lane 2, the Pareto moonshot). It
//! reads exactly one input file — the pinned public month-A slice — runs the
//! deterministic single-pass logistic learner in `moon::h8`, and emits the
//! frozen weight vector as the committed weight file plus a content-derived
//! receipt. It reads nothing else: no month-B slice, no `corpora/`, no licensed
//! development item, and it makes no network access. Same input bytes always
//! produce a byte-identical weight file (the receipt records both SHA-256s so
//! the determinism is checkable by re-running).

#[path = "../s0/mod.rs"]
pub mod s0;

#[path = "../moon/mod.rs"]
pub mod moon;

use moon::h8::{
    serialize_weight_file, train_static_weights, H8_PROCEDURE_VERSION, H8_STATIC_WEIGHT_COUNT,
    H8_WEIGHT_FILE_BYTES,
};
use s0::LossTable;
use sha2::{Digest, Sha256};
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::ExitCode;

const VERSION: &str = env!("CARGO_PKG_VERSION");
const EVIDENCE_STAGE: &str = "development_only_prescreen";

const HELP: &str = "clab-moon-h8-train — offline trainer for the H8 static mixer

Reads ONLY the pinned public month-A slice, learns the frozen static mixer
weight vector by one deterministic logistic pass, and writes the committed
weight file plus a content-derived receipt.

Usage:
  clab-moon-h8-train --input MONTH_A_SLICE --weights-out PATH
                     [--receipt-out PATH] [--force]
  clab-moon-h8-train --help
  clab-moon-h8-train --version
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
            println!("clab-moon-h8-train {VERSION}");
            ExitCode::SUCCESS
        }
        _ => match run(&arguments) {
            Ok(()) => ExitCode::SUCCESS,
            Err(message) => {
                eprintln!("clab-moon-h8-train: {message}\n{HELP}");
                ExitCode::FAILURE
            }
        },
    }
}

fn run(arguments: &[&str]) -> Result<(), String> {
    let mut input: Option<&str> = None;
    let mut weights_out: Option<&str> = None;
    let mut receipt_out: Option<&str> = None;
    let mut force = false;

    let mut index = 0;
    while index < arguments.len() {
        match arguments[index] {
            "--force" => {
                force = true;
                index += 1;
            }
            "--input" => {
                input = Some(next_value(arguments, index)?);
                index += 2;
            }
            "--weights-out" => {
                weights_out = Some(next_value(arguments, index)?);
                index += 2;
            }
            "--receipt-out" => {
                receipt_out = Some(next_value(arguments, index)?);
                index += 2;
            }
            other => return Err(format!("unknown or malformed argument: {other}")),
        }
    }

    let input = input.ok_or("missing required --input")?;
    let weights_out = weights_out.ok_or("missing required --weights-out")?;

    let month_a =
        fs::read(input).map_err(|error| format!("cannot read month-A slice {input}: {error}"))?;
    let source_sha = sha256_hex(&month_a);

    let table = LossTable::generate();
    let weights = train_static_weights(&month_a, &table);
    if weights.len() != H8_STATIC_WEIGHT_COUNT {
        return Err("trainer produced the wrong weight count".to_owned());
    }
    let file = serialize_weight_file(&weights);
    if file.len() != H8_WEIGHT_FILE_BYTES {
        return Err("serialized weight file has the wrong length".to_owned());
    }
    let weight_sha = sha256_hex(&file);

    write_output(weights_out, &file, force)?;

    if let Some(receipt_out) = receipt_out {
        let receipt = format!(
            "{{\n  \"schema\": \"clab-moon-h8-train-receipt-v1\",\n  \"trainer_version\": \"{VERSION}\",\n  \"evidence_stage\": \"{EVIDENCE_STAGE}\",\n  \"procedure_version\": {H8_PROCEDURE_VERSION},\n  \"train_month\": \"A\",\n  \"source_bytes\": {},\n  \"source_sha256\": \"{source_sha}\",\n  \"weight_count\": {H8_STATIC_WEIGHT_COUNT},\n  \"weight_file_bytes\": {},\n  \"weight_file_sha256\": \"{weight_sha}\",\n  \"determinism\": \"single deterministic integer pass; identical source bytes yield a byte-identical weight file\",\n  \"reads\": \"month-A slice only; no month-B, no corpora, no network\"\n}}\n",
            month_a.len(),
            file.len(),
        );
        write_output(receipt_out, receipt.as_bytes(), force)?;
    }

    Ok(())
}

fn next_value<'a>(arguments: &[&'a str], index: usize) -> Result<&'a str, String> {
    arguments
        .get(index + 1)
        .copied()
        .ok_or_else(|| format!("missing value for {}", arguments[index]))
}

fn write_output(path: &str, bytes: &[u8], force: bool) -> Result<(), String> {
    let destination = PathBuf::from(path);
    if let Some(parent) = destination
        .parent()
        .filter(|parent| *parent != Path::new(""))
    {
        fs::create_dir_all(parent)
            .map_err(|error| format!("cannot create directory for {path}: {error}"))?;
    }
    if !force && destination.exists() {
        return Err(format!("refusing to overwrite {path} without --force"));
    }
    fs::write(&destination, bytes).map_err(|error| format!("cannot write {path}: {error}"))
}

fn sha256_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    let mut hex = String::with_capacity(64);
    for byte in digest {
        hex.push_str(&format!("{byte:02x}"));
    }
    hex
}
