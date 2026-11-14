//! PresentMon's CSV, filtered to the one program being tested.
//!
//! PresentMon records every program that draws to the screen. The privacy rule
//! (docs/privacy.md) is that only the tested program's rows leave the PC, with
//! a *count* of the others. So rows are filtered as they arrive and written
//! straight to `presentmon.csv`; other programs' rows are counted and dropped.
//! Their names are not even kept in memory: to count how many *different*
//! programs were removed, only a 64-bit hash of each name is remembered.
//!
//! Column names differ between PresentMon versions (docs/verified-facts.md):
//!
//! | Style            | Frame time          | Timestamp       |
//! |------------------|---------------------|-----------------|
//! | 1.x / `--v1_metrics` | `msBetweenPresents` | `TimeInSeconds` |
//! | 2.x default      | `MsBetweenPresents` | `TimeInSeconds` |
//! | 2.x `--v2_metrics` | `FrameTime`       | `CPUStartTime`  |
//!
//! All of them name the program `Application`, which is the only column the
//! filter needs. The rows are copied unchanged, so the analyzer (which accepts
//! every style) reads them as PresentMon wrote them.

use std::collections::HashSet;
use std::hash::{DefaultHasher, Hash, Hasher};
use std::io::{self, Write};
use std::path::Path;
use std::sync::LazyLock;

use regex::Regex;

/// Which PresentMon column layout the header looked like. Recorded in the
/// manifest (`capture.presentmon.columns`) to help read odd captures later.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HeaderStyle {
    /// PresentMon 1.x, or 2.x with `--v1_metrics`: `msBetweenPresents`.
    V1,
    /// PresentMon 2.x default output: `MsBetweenPresents`.
    V2,
    /// PresentMon 2.x with `--v2_metrics`: `FrameTime`.
    V2Metrics,
    /// No frame-time column we know. The rows are still filtered and kept.
    Unknown,
}

impl HeaderStyle {
    /// Decide from the header's column names. Case matters here only to tell
    /// 1.x (`msBetweenPresents`) from 2.x (`MsBetweenPresents`); the analyzer
    /// itself matches case-insensitively.
    pub fn detect(columns: &[&str]) -> Self {
        if columns.contains(&"MsBetweenPresents") {
            HeaderStyle::V2
        } else if columns.contains(&"msBetweenPresents") {
            HeaderStyle::V1
        } else if columns.iter().any(|c| c.eq_ignore_ascii_case("FrameTime")) {
            HeaderStyle::V2Metrics
        } else if columns
            .iter()
            .any(|c| c.eq_ignore_ascii_case("MsBetweenPresents"))
        {
            // Some other capitalisation: still a frame-time column.
            HeaderStyle::V2
        } else {
            HeaderStyle::Unknown
        }
    }

    /// The name written to the manifest.
    pub fn as_str(self) -> &'static str {
        match self {
            HeaderStyle::V1 => "v1",
            HeaderStyle::V2 => "v2",
            HeaderStyle::V2Metrics => "v2_metrics",
            HeaderStyle::Unknown => "unknown",
        }
    }
}

/// What the filter saw, for the manifest and the console.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct FilterSummary {
    /// The program's name exactly as PresentMon wrote it (e.g. `Game.exe`),
    /// once at least one of its rows was seen.
    pub application: Option<String>,
    /// Rows kept (frames of the tested program).
    pub frames: u64,
    /// How many different other programs were removed.
    pub other_processes_removed: u64,
    /// How many rows of other programs were removed.
    pub other_frames_removed: u64,
    /// Rows too short to have an `Application` cell.
    pub malformed_rows: u64,
    /// The header layout, once the header was seen.
    pub style: Option<HeaderStyle>,
    /// False when the file had no `Application` column, so nothing could be
    /// filtered and every row was kept (such a file names no program at all).
    pub filtered: bool,
}

/// Filters PresentMon CSV lines to one program and writes them to `out`.
pub struct FrameFilter<W: Write> {
    target: String,
    out: W,
    /// Index of the `Application` column; `None` until the header is read,
    /// or if the header has no such column.
    app_index: Option<usize>,
    header_seen: bool,
    other_names: HashSet<u64>,
    summary: FilterSummary,
}

impl<W: Write> FrameFilter<W> {
    /// `target` is the program to keep: `Game.exe` or just `Game`, any case
    /// (the same matching as the PowerShell collector).
    pub fn new(target: &str, out: W) -> Self {
        Self {
            target: target.trim().to_string(),
            out,
            app_index: None,
            header_seen: false,
            other_names: HashSet::new(),
            summary: FilterSummary {
                filtered: true,
                ..FilterSummary::default()
            },
        }
    }

    /// Feed one line (without its newline). The first non-empty line is the
    /// header and is always written.
    pub fn push_line(&mut self, line: &str) -> io::Result<()> {
        if line.trim().is_empty() {
            return Ok(());
        }
        if !self.header_seen {
            return self.read_header(line);
        }
        let Some(app_index) = self.app_index else {
            // No Application column: nothing to filter on, and no program
            // names to leak. Keep the row rather than lose the data.
            self.summary.frames += 1;
            return writeln!(self.out, "{line}");
        };
        // PresentMon does not quote its fields, so a plain split is exact.
        // (The PowerShell collector splits the same way.)
        let Some(app) = line.split(',').nth(app_index).map(str::trim) else {
            self.summary.malformed_rows += 1;
            return Ok(());
        };
        if matches_target(app, &self.target) {
            if self.summary.application.is_none() {
                self.summary.application = Some(app.to_string());
            }
            self.summary.frames += 1;
            writeln!(self.out, "{line}")
        } else {
            self.summary.other_frames_removed += 1;
            self.other_names.insert(name_hash(app));
            self.summary.other_processes_removed = self.other_names.len() as u64;
            Ok(())
        }
    }

    fn read_header(&mut self, line: &str) -> io::Result<()> {
        // A UTF-8 byte-order mark would stick to the first column name.
        let line = line.trim_start_matches('\u{feff}');
        let columns: Vec<&str> = line.split(',').map(str::trim).collect();
        self.app_index = columns
            .iter()
            .position(|c| c.eq_ignore_ascii_case("Application"));
        self.summary.filtered = self.app_index.is_some();
        self.summary.style = Some(HeaderStyle::detect(&columns));
        self.header_seen = true;
        writeln!(self.out, "{line}")
    }

    /// What has been seen so far.
    pub fn summary(&self) -> &FilterSummary {
        &self.summary
    }

    /// True once the header has been read.
    pub fn header_seen(&self) -> bool {
        self.header_seen
    }

    /// Flush and hand back the writer and the final summary.
    pub fn finish(mut self) -> io::Result<(W, FilterSummary)> {
        self.out.flush()?;
        Ok((self.out, self.summary))
    }
}

/// `Game.exe` matches `game.exe`, `GAME.EXE` and `game`.
pub fn matches_target(app: &str, target: &str) -> bool {
    if target.is_empty() {
        return false;
    }
    if app.eq_ignore_ascii_case(target) {
        return true;
    }
    // "Game" given, "Game.exe" in the file. get() instead of slicing: a
    // program name can contain non-ASCII letters, and slicing in the middle
    // of one would panic.
    match (app.get(..target.len()), app.get(target.len()..)) {
        (Some(stem), Some(extension)) => {
            stem.eq_ignore_ascii_case(target) && extension.eq_ignore_ascii_case(".exe")
        }
        _ => false,
    }
}

/// A program name reduced to a number, so names of other programs are never
/// stored - only how many different ones there were.
fn name_hash(app: &str) -> u64 {
    let mut hasher = DefaultHasher::new();
    app.to_ascii_lowercase().hash(&mut hasher);
    hasher.finish()
}

/// The flags the PowerShell collector passes (verified against PresentMon
/// 2.6.0, docs/verified-facts.md). `std::process::Command` quotes each
/// argument itself, so paths with spaces need no extra quotes here.
pub fn presentmon_arguments(output_file: &Path, seconds: u64, process: &str) -> Vec<String> {
    let mut args = vec![
        "--output_file".to_string(),
        output_file.display().to_string(),
        "--timed".to_string(),
        seconds.to_string(),
        "--terminate_after_timed".to_string(),
        "--no_console_stats".to_string(),
        "--stop_existing_session".to_string(),
        "--session_name".to_string(),
        "PCDoctor".to_string(),
    ];
    if !process.trim().is_empty() {
        args.push("--process_name".to_string());
        args.push(process.trim().to_string());
    }
    args
}

/// The standalone PresentMon build has no version resource, but its file
/// name does: `PresentMon-2.6.0-x64.exe` -> `2.6.0`.
pub fn version_from_file_name(path: &Path) -> Option<String> {
    static VERSION: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(r"(\d+\.\d+\.\d+)").expect("valid regex"));
    let name = path.file_name()?.to_string_lossy();
    VERSION.captures(&name).map(|c| c[1].to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    const FIXTURES: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/fixtures");

    fn filter_text(text: &str, target: &str) -> (String, FilterSummary) {
        let mut filter = FrameFilter::new(target, Vec::new());
        for line in text.lines() {
            filter.push_line(line).unwrap();
        }
        let (out, summary) = filter.finish().unwrap();
        (String::from_utf8(out).unwrap(), summary)
    }

    fn fixture(name: &str) -> String {
        std::fs::read_to_string(format!("{FIXTURES}/{name}")).unwrap()
    }

    #[test]
    fn keeps_only_the_target_and_counts_the_others() {
        let text = "Application,ProcessID,SwapChainAddress,TimeInSeconds,MsBetweenPresents\n\
                    dwm.exe,10,0xA,0.1,16.6\n\
                    Game.exe,20,0xB,0.1,7.1\n\
                    chrome.exe,30,0xC,0.1,16.6\n\
                    Game.exe,20,0xB,0.2,7.2\n\
                    dwm.exe,10,0xA,0.2,16.6\n";
        let (out, summary) = filter_text(text, "game.exe");
        assert_eq!(
            out,
            "Application,ProcessID,SwapChainAddress,TimeInSeconds,MsBetweenPresents\n\
             Game.exe,20,0xB,0.1,7.1\n\
             Game.exe,20,0xB,0.2,7.2\n"
        );
        assert!(!out.contains("dwm") && !out.contains("chrome"));
        assert_eq!(summary.application.as_deref(), Some("Game.exe"));
        assert_eq!(summary.frames, 2);
        assert_eq!(summary.other_processes_removed, 2);
        assert_eq!(summary.other_frames_removed, 3);
        assert_eq!(summary.style, Some(HeaderStyle::V2));
        assert!(summary.filtered);
    }

    #[test]
    fn matches_with_or_without_exe_in_any_case() {
        assert!(matches_target("Game.exe", "Game.exe"));
        assert!(matches_target("Game.exe", "game"));
        assert!(matches_target("GAME.EXE", "game.exe"));
        assert!(!matches_target("Game.exe", "Gam"));
        assert!(!matches_target("MyGame.exe", "Game"));
        assert!(!matches_target("Game.exe", ""));
        // Multi-byte names must not panic on slicing.
        assert!(!matches_target("ab\u{e9}xyz", "abc"));
    }

    #[test]
    fn reads_presentmon_1x_columns() {
        let (out, summary) = filter_text(&fixture("presentmon_v1.csv"), "Game.exe");
        assert_eq!(summary.style, Some(HeaderStyle::V1));
        assert_eq!(summary.frames, 3);
        assert_eq!(summary.other_processes_removed, 1);
        assert!(out.starts_with("Application,ProcessID,SwapChainAddress,Runtime,"));
    }

    #[test]
    fn reads_presentmon_2x_default_columns() {
        let (_, summary) = filter_text(&fixture("presentmon_v2.csv"), "Game.exe");
        assert_eq!(summary.style, Some(HeaderStyle::V2));
        assert_eq!(summary.frames, 3);
        assert_eq!(summary.other_processes_removed, 2);
    }

    #[test]
    fn reads_presentmon_2x_v2_metrics_columns() {
        let (_, summary) = filter_text(&fixture("presentmon_v2_metrics.csv"), "Game");
        assert_eq!(summary.style, Some(HeaderStyle::V2Metrics));
        assert_eq!(summary.frames, 3);
        assert_eq!(summary.application.as_deref(), Some("Game.exe"));
    }

    #[test]
    fn strips_a_byte_order_mark_from_the_header() {
        let (out, summary) = filter_text(
            "\u{feff}Application,MsBetweenPresents\r\nGame.exe,7.1\r\n",
            "Game.exe",
        );
        assert_eq!(out, "Application,MsBetweenPresents\nGame.exe,7.1\n");
        assert_eq!(summary.frames, 1);
    }

    #[test]
    fn keeps_everything_when_there_is_no_application_column() {
        let (out, summary) = filter_text("TimeInSeconds,MsBetweenPresents\n0.1,7.1\n", "x");
        assert!(!summary.filtered);
        assert_eq!(summary.frames, 1);
        assert_eq!(out.lines().count(), 2);
    }

    #[test]
    fn counts_short_rows_as_malformed() {
        let (_, summary) = filter_text("ProcessID,Application\n20\n20,Game.exe\n", "Game.exe");
        assert_eq!(summary.malformed_rows, 1);
        assert_eq!(summary.frames, 1);
    }

    #[test]
    fn header_only_file_keeps_no_frames() {
        let (out, summary) = filter_text("Application,MsBetweenPresents\n", "Game.exe");
        assert_eq!(summary.frames, 0);
        assert_eq!(summary.application, None);
        assert_eq!(out, "Application,MsBetweenPresents\n");
    }

    #[test]
    fn same_flags_as_the_powershell_collector() {
        let args = presentmon_arguments(Path::new("C:/runs/my run/pm.csv"), 300, "game.exe");
        assert_eq!(
            args.join(" "),
            "--output_file C:/runs/my run/pm.csv --timed 300 --terminate_after_timed \
             --no_console_stats --stop_existing_session --session_name PCDoctor \
             --process_name game.exe"
        );
        let args = presentmon_arguments(Path::new("x.csv"), 5, " ");
        assert!(!args.contains(&"--process_name".to_string()));
    }

    #[test]
    fn version_comes_from_the_file_name() {
        assert_eq!(
            version_from_file_name(Path::new("tools/PresentMon-2.6.0-x64.exe")).as_deref(),
            Some("2.6.0")
        );
        assert_eq!(version_from_file_name(Path::new("PresentMon.exe")), None);
    }
}
