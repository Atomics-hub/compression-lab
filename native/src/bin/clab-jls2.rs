#[path = "../jls2.rs"]
mod jls2;

use std::env;
use std::fs::{self, File, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::process;
use std::sync::atomic::{AtomicU64, Ordering};

const VERSION: &str = env!("CARGO_PKG_VERSION");
static TEMPORARY_COUNTER: AtomicU64 = AtomicU64::new(0);

const HELP: &str = "clab-jls2 — standalone verified JLS2 decoder

Usage:
  clab-jls2 decompress INPUT -o OUTPUT [--force] [--max-output-size BYTES]
  clab-jls2 --help
  clab-jls2 --version
";

struct DecompressArgs {
    input: PathBuf,
    output: PathBuf,
    force: bool,
    max_output_size: Option<u64>,
}

struct TemporaryOutput {
    path: PathBuf,
    published: bool,
}

impl TemporaryOutput {
    fn create(destination: &Path) -> Result<(Self, File), String> {
        let parent = destination.parent().unwrap_or_else(|| Path::new("."));
        fs::create_dir_all(parent)
            .map_err(|error| format!("cannot create output directory: {error}"))?;
        let name = destination
            .file_name()
            .and_then(|value| value.to_str())
            .unwrap_or("output");
        for _ in 0..1024 {
            let serial = TEMPORARY_COUNTER.fetch_add(1, Ordering::Relaxed);
            let path = parent.join(format!(".{name}.{}.{}.partial", process::id(), serial));
            match OpenOptions::new().write(true).create_new(true).open(&path) {
                Ok(file) => {
                    return Ok((
                        Self {
                            path,
                            published: false,
                        },
                        file,
                    ));
                }
                Err(error) if error.kind() == io::ErrorKind::AlreadyExists => continue,
                Err(error) => return Err(format!("cannot create temporary output: {error}")),
            }
        }
        Err("cannot allocate a unique temporary output".to_owned())
    }

    fn publish(mut self, destination: &Path, force: bool) -> Result<(), String> {
        if force {
            replace_file(&self.path, destination)
                .map_err(|error| format!("cannot replace destination: {error}"))?;
        } else {
            fs::hard_link(&self.path, destination).map_err(|error| {
                if error.kind() == io::ErrorKind::AlreadyExists {
                    format!("destination already exists: {}", destination.display())
                } else {
                    format!("cannot publish destination: {error}")
                }
            })?;
            fs::remove_file(&self.path)
                .map_err(|error| format!("cannot remove temporary link: {error}"))?;
        }
        self.published = true;
        Ok(())
    }
}

impl Drop for TemporaryOutput {
    fn drop(&mut self) {
        if !self.published {
            let _ = fs::remove_file(&self.path);
        }
    }
}

#[cfg(unix)]
fn replace_file(source: &Path, destination: &Path) -> io::Result<()> {
    fs::rename(source, destination)
}

#[cfg(windows)]
fn replace_file(source: &Path, destination: &Path) -> io::Result<()> {
    use std::os::windows::ffi::OsStrExt;

    const MOVEFILE_REPLACE_EXISTING: u32 = 0x1;
    const MOVEFILE_WRITE_THROUGH: u32 = 0x8;
    #[link(name = "kernel32")]
    extern "system" {
        fn MoveFileExW(existing: *const u16, replacement: *const u16, flags: u32) -> i32;
    }
    let existing: Vec<u16> = source.as_os_str().encode_wide().chain(Some(0)).collect();
    let replacement: Vec<u16> = destination
        .as_os_str()
        .encode_wide()
        .chain(Some(0))
        .collect();
    let status = unsafe {
        MoveFileExW(
            existing.as_ptr(),
            replacement.as_ptr(),
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
        )
    };
    if status == 0 {
        Err(io::Error::last_os_error())
    } else {
        Ok(())
    }
}

fn parse_size(value: &str) -> Result<u64, String> {
    value
        .parse::<u64>()
        .map_err(|_| format!("invalid byte count: {value}"))
}

fn parse_decompress(arguments: &[String]) -> Result<DecompressArgs, String> {
    let mut input = None;
    let mut output = None;
    let mut force = false;
    let mut max_output_size = None;
    let mut offset = 0;
    while offset < arguments.len() {
        match arguments[offset].as_str() {
            "-o" | "--output" => {
                offset += 1;
                let value = arguments
                    .get(offset)
                    .ok_or_else(|| "missing value after --output".to_owned())?;
                if output.replace(PathBuf::from(value)).is_some() {
                    return Err("output was specified more than once".to_owned());
                }
            }
            "--force" => force = true,
            "--max-output-size" => {
                offset += 1;
                let value = arguments
                    .get(offset)
                    .ok_or_else(|| "missing value after --max-output-size".to_owned())?;
                if max_output_size.replace(parse_size(value)?).is_some() {
                    return Err("maximum output size was specified more than once".to_owned());
                }
            }
            "-h" | "--help" => return Err(HELP.to_owned()),
            value if value.starts_with('-') => return Err(format!("unknown option: {value}")),
            value => {
                if input.replace(PathBuf::from(value)).is_some() {
                    return Err("more than one input was provided".to_owned());
                }
            }
        }
        offset += 1;
    }
    Ok(DecompressArgs {
        input: input.ok_or_else(|| "missing input path".to_owned())?,
        output: output.ok_or_else(|| "missing --output path".to_owned())?,
        force,
        max_output_size,
    })
}

fn same_existing_file(left: &Path, right: &Path) -> bool {
    match (fs::canonicalize(left), fs::canonicalize(right)) {
        (Ok(left), Ok(right)) => left == right,
        _ => false,
    }
}

fn decompress(arguments: DecompressArgs) -> Result<(), String> {
    if same_existing_file(&arguments.input, &arguments.output) {
        return Err("input and output paths refer to the same file".to_owned());
    }
    if !arguments.force && arguments.output.exists() {
        return Err(format!(
            "destination already exists: {}",
            arguments.output.display()
        ));
    }
    let encoded = fs::read(&arguments.input)
        .map_err(|error| format!("cannot read {}: {error}", arguments.input.display()))?;
    let (temporary, mut output) = TemporaryOutput::create(&arguments.output)?;
    let stats = jls2::decode_to_writer(&encoded, &mut output, arguments.max_output_size)?;
    output
        .flush()
        .map_err(|error| format!("cannot flush output: {error}"))?;
    drop(output);
    temporary.publish(&arguments.output, arguments.force)?;
    println!(
        "decoded {} bytes to {} bytes across {} segment(s)",
        stats.encoded_bytes, stats.restored_bytes, stats.segment_count
    );
    Ok(())
}

fn run() -> Result<(), (i32, String)> {
    let arguments: Vec<String> = env::args().skip(1).collect();
    match arguments.first().map(String::as_str) {
        Some("-h" | "--help") => {
            print!("{HELP}");
            Ok(())
        }
        Some("-V" | "--version") => {
            println!("clab-jls2 {VERSION}");
            Ok(())
        }
        Some("decompress")
            if arguments[1..]
                .iter()
                .any(|argument| matches!(argument.as_str(), "-h" | "--help")) =>
        {
            print!("{HELP}");
            Ok(())
        }
        Some("decompress") => parse_decompress(&arguments[1..])
            .map_err(|error| (2, error))
            .and_then(|parsed| decompress(parsed).map_err(|error| (1, error))),
        Some(command) => Err((2, format!("unknown command: {command}\n\n{HELP}"))),
        None => Err((2, HELP.to_owned())),
    }
}

fn main() {
    if let Err((status, message)) = run() {
        eprintln!("{message}");
        process::exit(status);
    }
}
