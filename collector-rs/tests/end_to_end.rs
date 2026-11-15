//! Runs the real `pcdoctor-capture` binary on fixture files and checks the
//! run folder and zip it writes. No PresentMon, no LibreHardwareMonitor and no
//! Windows needed: `--presentmon-csv` follows a fixture CSV and `--lhm-file`
//! reads a saved data.json.
//!
//! scripts/check-with-analyzer.sh goes one step further and feeds the zip to
//! the Python analyzer.

use std::collections::BTreeSet;
use std::fs::{self, File};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::Duration;

use serde_json::Value;

const BIN: &str = env!("CARGO_BIN_EXE_pcdoctor-capture");

fn fixture(name: &str) -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures")
        .join(name)
}

/// Run the binary; return (run folder, zip, stdout).
fn capture(output: &Path, extra: &[&str]) -> (PathBuf, PathBuf, String) {
    let result = Command::new(BIN)
        .args(["--output-dir", output.to_str().unwrap()])
        .args(extra)
        .output()
        .expect("the binary runs");
    let stdout = String::from_utf8_lossy(&result.stdout).into_owned();
    assert!(
        result.status.success(),
        "exit {:?}\nstdout:\n{stdout}\nstderr:\n{}",
        result.status,
        String::from_utf8_lossy(&result.stderr)
    );
    let mut dirs = Vec::new();
    let mut zips = Vec::new();
    for entry in fs::read_dir(output).unwrap() {
        let path = entry.unwrap().path();
        let name = path.file_name().unwrap().to_string_lossy().into_owned();
        assert!(
            name.starts_with("PCDoctor-run-"),
            "unexpected output {name}"
        );
        if path.is_dir() {
            dirs.push(path);
        } else if name.ends_with(".zip") {
            zips.push(path);
        }
    }
    assert_eq!(
        (dirs.len(), zips.len()),
        (1, 1),
        "one run folder and one zip"
    );
    let stem = zips[0].file_stem().unwrap().to_string_lossy().into_owned();
    assert_eq!(dirs[0].file_name().unwrap().to_string_lossy(), stem);
    // PCDoctor-run-yyyyMMdd-HHmmss
    let stamp = stem.trim_start_matches("PCDoctor-run-");
    assert!(
        stamp.len() == 15 && stamp.as_bytes()[8] == b'-',
        "bad run name {stem}"
    );
    (dirs.remove(0), zips.remove(0), stdout)
}

fn zip_entries(path: &Path) -> Vec<(String, String)> {
    let mut archive = zip::ZipArchive::new(File::open(path).unwrap()).unwrap();
    let mut out = Vec::new();
    for i in 0..archive.len() {
        let mut file = archive.by_index(i).unwrap();
        let mut text = String::new();
        file.read_to_string(&mut text).unwrap();
        out.push((file.name().to_string(), text));
    }
    out
}

#[test]
fn produces_a_run_zip_from_fixtures() {
    let output = tempfile::tempdir().unwrap();
    let csv = fixture("presentmon_game.csv");
    let lhm = fixture("lhm_intel_nvidia.json");
    let (run_dir, zip, stdout) = capture(
        output.path(),
        &[
            "--process",
            "game", // no ".exe", lower case: still matches Game.exe
            "--seconds",
            "2",
            "--interval",
            "0.5",
            "--presentmon-csv",
            csv.to_str().unwrap(),
            "--lhm-file",
            lhm.to_str().unwrap(),
            "--label",
            "integration test",
        ],
    );
    assert!(stdout.contains("Read-only"));
    assert!(stdout.contains("Collector overhead"));

    let entries = zip_entries(&zip);
    let names: BTreeSet<&str> = entries.iter().map(|(n, _)| n.as_str()).collect();
    assert_eq!(
        names,
        BTreeSet::from([
            "collector.log",
            "manifest.json",
            "presentmon.csv",
            "sensors.csv",
            "sensors_raw.json"
        ])
    );
    let file = |name: &str| {
        entries
            .iter()
            .find(|(n, _)| n == name)
            .map(|(_, text)| text.clone())
            .unwrap()
    };
    // The zip holds exactly what is in the folder.
    for (name, text) in &entries {
        assert_eq!(&fs::read_to_string(run_dir.join(name)).unwrap(), text);
    }

    // presentmon.csv: the header and the 900 Game.exe rows, nothing else.
    let frames = file("presentmon.csv");
    let lines: Vec<&str> = frames.lines().collect();
    assert_eq!(lines.len(), 901);
    assert!(lines[0].starts_with("Application,ProcessID,"));
    assert!(lines[1..].iter().all(|l| l.starts_with("Game.exe,")));
    assert!(!frames.contains("dwm") && !frames.contains("chrome"));

    // sensors.csv: header, then a row per 0.5 s with every column.
    let sensors = file("sensors.csv");
    let rows: Vec<Vec<&str>> = sensors.lines().map(|l| l.split(',').collect()).collect();
    assert!(rows[0].join(",").starts_with("elapsed_s,cpu_temp_c,"));
    assert!(rows.len() >= 4, "{} samples", rows.len() - 1);
    assert!(rows.iter().all(|r| r.len() == 15));
    assert_eq!(rows[1][1], "72.5"); // cpu_temp_c
    assert_eq!(rows[1][9], "97"); // gpu_load_pct
    assert_eq!(rows[1][5], ""); // cpu_perf_pct: LibreHardwareMonitor has none

    let manifest: Value = serde_json::from_str(&file("manifest.json")).unwrap();
    assert_eq!(manifest["schema_version"], 1);
    assert_eq!(manifest["mode"], "capture");
    assert_eq!(manifest["label"], "integration test");
    assert_eq!(manifest["collector"]["name"], "pcdoctor-capture-rs");
    let started = manifest["started_at"].as_str().unwrap();
    assert!(started.len() == 20 && started.ends_with('Z'), "{started}");
    let capture = &manifest["capture"];
    assert_eq!(capture["requested_seconds"], 2);
    assert!(capture["actual_seconds"].as_f64().unwrap() >= 2.0);
    assert_eq!(capture["target_process"], "Game.exe");
    let pm = &capture["presentmon"];
    assert_eq!(pm["used"], true);
    assert_eq!(pm["file"], "presentmon.csv");
    assert_eq!(pm["frames"], 900);
    assert_eq!(pm["other_processes_removed"], 2);
    assert_eq!(pm["other_frames_removed"], 112 + 22);
    assert_eq!(pm["columns"], "v2");
    assert_eq!(capture["sensors"]["source"], "librehardwaremonitor");
    assert_eq!(
        capture["sensors"]["samples"].as_u64().unwrap(),
        (rows.len() - 1) as u64
    );
    assert!(manifest["warnings"].as_array().unwrap().is_empty());
    let resources = &manifest["collector_resources"];
    assert!(resources["cpu_seconds"].as_f64().unwrap() >= 0.0);
    assert!(resources["peak_memory_bytes"].as_u64().unwrap() > 0);

    // Privacy: no hardware or computer names from data.json, no file paths.
    let everything: String = entries.iter().map(|(_, t)| t.as_str()).collect();
    for secret in [
        "BENCH-PC",
        "RTX 3070",
        "i7-12700K",
        "chrome",
        "dwm.exe",
        env!("CARGO_MANIFEST_DIR"),
        output.path().to_str().unwrap(),
    ] {
        assert!(!everything.contains(secret), "{secret} leaked into the run");
    }
    for var in ["USER", "USERNAME", "HOSTNAME", "COMPUTERNAME"] {
        if let Ok(name) = std::env::var(var) {
            // Very short names ("ci", "root") also occur in ordinary words.
            if name.len() >= 5 {
                assert!(!everything.contains(&name), "${var} leaked into the run");
            }
        }
    }
}

#[test]
fn follows_a_csv_while_it_is_being_written() {
    let output = tempfile::tempdir().unwrap();
    let source = tempfile::tempdir().unwrap();
    let csv = source.path().join("presentmon_live.csv");
    let full = fs::read(fixture("presentmon_game.csv")).unwrap();

    // Write the fixture in small chunks that cut lines in half, while the
    // capture is already running.
    let writer_path = csv.clone();
    let writer = std::thread::spawn(move || {
        std::thread::sleep(Duration::from_millis(300)); // the file appears late
        let mut file = File::create(&writer_path).unwrap();
        for chunk in full.chunks(997) {
            file.write_all(chunk).unwrap();
            file.flush().unwrap();
            std::thread::sleep(Duration::from_millis(5));
        }
    });
    let (run_dir, _zip, _) = capture(
        output.path(),
        &[
            "--process",
            "Game.exe",
            "--seconds",
            "3",
            "--presentmon-csv",
            csv.to_str().unwrap(),
            "--no-sensors",
        ],
    );
    writer.join().unwrap();

    let frames = fs::read_to_string(run_dir.join("presentmon.csv")).unwrap();
    // Every row arrived whole: same rows as filtering the finished file.
    let original = fs::read_to_string(fixture("presentmon_game.csv")).unwrap();
    let expected: Vec<&str> = original
        .lines() // lines() also drops the "\r" of "\r\n"
        .filter(|l| l.starts_with("Application") || l.starts_with("Game.exe,"))
        .collect();
    assert_eq!(frames.lines().collect::<Vec<_>>(), expected);
    assert!(!run_dir.join("sensors.csv").exists());
    let manifest: Value =
        serde_json::from_str(&fs::read_to_string(run_dir.join("manifest.json")).unwrap()).unwrap();
    assert_eq!(manifest["capture"]["presentmon"]["frames"], 900);
    assert_eq!(manifest["capture"]["sensors"]["source"], Value::Null);
}

#[test]
fn a_target_that_never_presents_leaves_no_frame_file() {
    let output = tempfile::tempdir().unwrap();
    let csv = fixture("presentmon_v2.csv");
    let (run_dir, zip, _) = capture(
        output.path(),
        &[
            "--process",
            "NotRunning.exe",
            "--seconds",
            "1",
            "--presentmon-csv",
            csv.to_str().unwrap(),
            "--no-sensors",
        ],
    );
    assert!(!run_dir.join("presentmon.csv").exists());
    let names: Vec<String> = zip_entries(&zip).into_iter().map(|(n, _)| n).collect();
    assert_eq!(names, vec!["manifest.json", "collector.log"]);
    let manifest: Value =
        serde_json::from_str(&fs::read_to_string(run_dir.join("manifest.json")).unwrap()).unwrap();
    assert_eq!(manifest["capture"]["presentmon"]["used"], false);
    assert_eq!(
        manifest["capture"]["presentmon"]["other_processes_removed"],
        3
    );
    assert_eq!(manifest["capture"]["target_process"], "NotRunning.exe");
    let warnings = manifest["warnings"].as_array().unwrap();
    assert!(warnings.iter().any(|w| w
        .as_str()
        .unwrap()
        .contains("no frames of the tested program")));
}

#[test]
fn a_silent_sensor_source_is_a_warning_not_a_failure() {
    let output = tempfile::tempdir().unwrap();
    // A port nothing listens on.
    let port = std::net::TcpListener::bind("127.0.0.1:0")
        .unwrap()
        .local_addr()
        .unwrap()
        .port();
    let url = format!("http://127.0.0.1:{port}");
    let (run_dir, _, _) = capture(
        output.path(),
        &["--process", "Game.exe", "--seconds", "1", "--lhm-url", &url],
    );
    let manifest: Value =
        serde_json::from_str(&fs::read_to_string(run_dir.join("manifest.json")).unwrap()).unwrap();
    if cfg!(windows) {
        // Windows' own counters stand in: loads and RAM, no temperatures.
        // "windows+nvidia-smi" only on a PC with a signed NVIDIA driver.
        let source = manifest["capture"]["sensors"]["source"].as_str().unwrap();
        assert!(
            source == "windows" || source == "windows+nvidia-smi",
            "{source}"
        );
        let csv = fs::read_to_string(run_dir.join("sensors.csv")).unwrap();
        let header: Vec<&str> = csv.lines().next().unwrap().split(',').collect();
        let first: Vec<&str> = csv.lines().nth(1).unwrap().split(',').collect();
        let cell = |name: &str| first[header.iter().position(|h| *h == name).unwrap()];
        assert!(!cell("ram_used_pct").is_empty(), "{csv}");
        assert!(cell("cpu_temp_c").is_empty(), "{csv}");
    } else {
        assert_eq!(manifest["capture"]["sensors"]["source"], Value::Null);
        assert!(!run_dir.join("sensors.csv").exists());
    }
    let warnings: Vec<&str> = manifest["warnings"]
        .as_array()
        .unwrap()
        .iter()
        .map(|w| w.as_str().unwrap())
        .collect();
    assert!(warnings
        .iter()
        .any(|w| w.contains("LibreHardwareMonitor did not answer")));
    assert!(warnings.iter().any(|w| w.contains("No PresentMon source")));
}
