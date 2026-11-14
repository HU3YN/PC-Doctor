//! The run folder, its files and the zip.
//!
//! Same conventions as the PowerShell collector: a folder named
//! `PCDoctor-run-yyyyMMdd-HHmmss` (local time) with the files at its top
//! level, and a zip of the same name next to it with the files at the zip's
//! top level. Text is UTF-8 without a byte-order mark.

use std::fs::{self, File};
use std::io::{self, BufWriter, Write};
use std::path::Path;

use chrono::{DateTime, Local, Utc};
use serde::Serialize;
use zip::write::SimpleFileOptions;
use zip::{CompressionMethod, ZipWriter};

/// Every file a run may contain (docs/run-format.md). The zip holds only
/// these, so a stray file in the folder (PresentMon's unfiltered CSV, say)
/// can never be uploaded by mistake.
pub const RUN_FILES: [&str; 8] = [
    "manifest.json",
    "specs.json",
    "events.json",
    "disks.json",
    "presentmon.csv",
    "sensors.csv",
    "sensors_raw.json",
    "collector.log",
];

/// `PCDoctor-run-20261114-180000` for a run started at 18:00:00 local time.
pub fn run_name(started: &DateTime<Local>) -> String {
    format!("PCDoctor-run-{}", started.format("%Y%m%d-%H%M%S"))
}

/// `2026-11-14T17:00:00Z`: UTC, ISO 8601, to the second.
pub fn iso_utc(time: &DateTime<Utc>) -> String {
    time.format("%Y-%m-%dT%H:%M:%SZ").to_string()
}

/// Pretty JSON, UTF-8 without a byte-order mark.
pub fn write_json<T: Serialize>(path: &Path, value: &T) -> io::Result<()> {
    let mut writer = BufWriter::new(File::create(path)?);
    serde_json::to_writer_pretty(&mut writer, value)?;
    writer.write_all(b"\n")?;
    writer.flush()
}

/// Lines, each ended with a newline.
pub fn write_lines(path: &Path, lines: &[String]) -> io::Result<()> {
    let mut writer = BufWriter::new(File::create(path)?);
    for line in lines {
        writeln!(writer, "{line}")?;
    }
    writer.flush()
}

/// Zip the known run files found in `run_dir` into `zip_path`. Returns the
/// names that went in, in [`RUN_FILES`] order.
pub fn zip_run(run_dir: &Path, zip_path: &Path) -> io::Result<Vec<String>> {
    let mut zip = ZipWriter::new(File::create(zip_path)?);
    let options = SimpleFileOptions::default().compression_method(CompressionMethod::Deflated);
    let mut added = Vec::new();
    for name in RUN_FILES {
        let path = run_dir.join(name);
        if !path.is_file() {
            continue;
        }
        // Only the bare file name goes into the zip, never a folder path.
        zip.start_file(name, options).map_err(io::Error::other)?;
        io::copy(&mut File::open(&path)?, &mut zip)?;
        added.push(name.to_string());
    }
    zip.finish().map_err(io::Error::other)?;
    Ok(added)
}

/// Remove a file if it exists; a missing file is not an error.
pub fn remove_if_exists(path: &Path) -> io::Result<()> {
    match fs::remove_file(path) {
        Err(error) if error.kind() != io::ErrorKind::NotFound => Err(error),
        _ => Ok(()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;
    use std::io::Read;

    #[test]
    fn names_and_times_follow_the_powershell_collector() {
        let local = Local.with_ymd_and_hms(2026, 11, 14, 18, 5, 9).unwrap();
        assert_eq!(run_name(&local), "PCDoctor-run-20261114-180509");
        let utc = Utc.with_ymd_and_hms(2026, 11, 14, 17, 5, 9).unwrap();
        assert_eq!(iso_utc(&utc), "2026-11-14T17:05:09Z");
    }

    #[test]
    fn zips_only_known_files_at_the_top_level() {
        let dir = tempfile::tempdir().unwrap();
        let run = dir.path().join("PCDoctor-run-20261114-180509");
        fs::create_dir(&run).unwrap();
        write_json(
            &run.join("manifest.json"),
            &serde_json::json!({"schema_version": 1}),
        )
        .unwrap();
        write_lines(&run.join("sensors.csv"), &["elapsed_s".to_string()]).unwrap();
        fs::write(run.join("presentmon_raw.csv"), "Application\nchrome.exe\n").unwrap();

        let zip_path = dir.path().join("PCDoctor-run-20261114-180509.zip");
        let added = zip_run(&run, &zip_path).unwrap();
        assert_eq!(added, vec!["manifest.json", "sensors.csv"]);

        let mut archive = zip::ZipArchive::new(File::open(&zip_path).unwrap()).unwrap();
        let names: Vec<String> = archive.file_names().map(String::from).collect();
        assert_eq!(names.len(), 2);
        assert!(!names.iter().any(|n| n.contains('/') || n.contains("raw")));
        let mut text = String::new();
        archive
            .by_name("manifest.json")
            .unwrap()
            .read_to_string(&mut text)
            .unwrap();
        assert!(!text.starts_with('\u{feff}'));
        assert!(text.contains("\"schema_version\": 1"));
    }

    #[test]
    fn removing_a_missing_file_is_fine() {
        let dir = tempfile::tempdir().unwrap();
        remove_if_exists(&dir.path().join("nothing")).unwrap();
    }
}
