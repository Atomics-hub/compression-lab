#[path = "../jls2.rs"]
mod jls2;
#[path = "../jls2_a3_audit.rs"]
mod jls2_a3_audit;

use std::env;
use std::path::PathBuf;
use std::process;

struct Arguments {
    input: PathBuf,
    fixture_id: String,
    expected_output_sha256: String,
    output: PathBuf,
}

fn parse() -> Result<Arguments, String> {
    let values: Vec<String> = env::args().skip(1).collect();
    let mut input = None;
    let mut fixture_id = None;
    let mut expected_output_sha256 = None;
    let mut output = None;
    let mut offset = 0;
    while offset < values.len() {
        let key = &values[offset];
        offset += 1;
        let value = values
            .get(offset)
            .ok_or_else(|| format!("missing value after {key}"))?;
        match key.as_str() {
            "--input" => input = Some(PathBuf::from(value)),
            "--fixture-id" => fixture_id = Some(value.clone()),
            "--expected-output-sha256" => expected_output_sha256 = Some(value.clone()),
            "--output" => output = Some(PathBuf::from(value)),
            _ => return Err(format!("unknown option: {key}")),
        }
        offset += 1;
    }
    Ok(Arguments {
        input: input.ok_or_else(|| "missing --input".to_owned())?,
        fixture_id: fixture_id.ok_or_else(|| "missing --fixture-id".to_owned())?,
        expected_output_sha256: expected_output_sha256
            .ok_or_else(|| "missing --expected-output-sha256".to_owned())?,
        output: output.ok_or_else(|| "missing --output".to_owned())?,
    })
}

fn run() -> Result<(), String> {
    let arguments = parse()?;
    jls2_a3_audit::run(
        &arguments.input,
        &arguments.fixture_id,
        &arguments.expected_output_sha256,
        &arguments.output,
    )
}

fn main() {
    if let Err(error) = run() {
        eprintln!("{error}");
        process::exit(1);
    }
}
