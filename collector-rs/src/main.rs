//! `pcdoctor-capture`: record frame times and sensors into a PC Doctor run.
//!
//! READ-ONLY: this changes no settings and installs nothing. It reads
//! PresentMon's CSV and LibreHardwareMonitor's sensor readings, writes a run
//! folder and zips it. All the logic is in the library (src/lib.rs); this file
//! only parses flags and runs the capture loop.

use std::fs::{self, File};
use std::io::BufWriter;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, ExitCode, Stdio};
use std::time::{Duration, Instant};

use chrono::{Local, Utc};
use clap::{ArgGroup, Parser};

use pcdoctor_capture::lhm::LhmSource;
use pcdoctor_capture::live;
use pcdoctor_capture::manifest::{
    round1, Capture, CollectorInfo, Manifest, PresentMonInfo, SensorsInfo,
};
use pcdoctor_capture::presentmon::{presentmon_arguments, version_from_file_name, FrameFilter};
use pcdoctor_capture::resources::{self, ResourceUsage};
use pcdoctor_capture::run::{self, remove_if_exists};
use pcdoctor_capture::sensors::{self, Sample};
use pcdoctor_capture::tail::FileTail;
use pcdoctor_capture::winsensors::WindowsSensors;
use pcdoctor_capture::{privacy, COLLECTOR_NAME, COLLECTOR_VERSION, SCHEMA_VERSION};

/// How often the PresentMon file is checked for new rows.
const POLL_INTERVAL: Duration = Duration::from_millis(250);
/// How long PresentMon may take to stop by itself after the capture time.
const PRESENTMON_GRACE: Duration = Duration::from_secs(30);
/// How long one LibreHardwareMonitor request may take.
const LHM_TIMEOUT: Duration = Duration::from_secs(2);

/// Record frame times (PresentMon) and sensors (LibreHardwareMonitor) into a
/// PC Doctor run folder and zip. Read-only: changes no settings, installs
/// nothing.
#[derive(Parser, Debug)]
#[command(name = "pcdoctor-capture", version)]
#[command(group(ArgGroup::new("frames").args(["presentmon_csv", "start_presentmon"])))]
#[command(group(ArgGroup::new("sensor_source").args(["lhm_url", "lhm_file", "no_sensors"])))]
struct Args {
    /// The program being tested, e.g. Game.exe (".exe" optional, any case).
    /// Only its frames are kept; other programs are only counted.
    #[arg(long)]
    process: String,

    /// Capture length in seconds.
    #[arg(long, default_value_t = 300, value_parser = clap::value_parser!(u64).range(1..=3600))]
    seconds: u64,

    /// Follow a PresentMon CSV that something else is writing (or has written).
    #[arg(long, value_name = "PATH")]
    presentmon_csv: Option<PathBuf>,

    /// Start this PresentMon executable for the capture and follow its CSV
    /// (Windows; needs administrator rights to record frames).
    #[arg(long, value_name = "EXE")]
    start_presentmon: Option<PathBuf>,

    /// LibreHardwareMonitor's web server (Options > Remote Web Server > Run).
    #[arg(
        long,
        value_name = "URL",
        default_value = "http://localhost:8085/data.json"
    )]
    lhm_url: String,

    /// Read sensors from a saved data.json instead of the web server (tests).
    #[arg(long, value_name = "PATH")]
    lhm_file: Option<PathBuf>,

    /// Record no sensors.
    #[arg(long)]
    no_sensors: bool,

    /// Seconds between sensor samples.
    #[arg(long, default_value_t = 1.0)]
    interval: f64,

    /// A note to recognise the run by, e.g. "bench 3, after repaste". Never a
    /// customer's name.
    #[arg(long, default_value = "")]
    label: String,

    /// Where run folders go. Default: a "runs" folder next to this program.
    #[arg(long, value_name = "DIR")]
    output_dir: Option<PathBuf>,

    /// Seconds to wait before the capture starts, to switch to the game.
    #[arg(long, default_value_t = 0)]
    start_delay: u64,

    /// Write the folder only, no zip.
    #[arg(long)]
    no_zip: bool,

    /// Also stream frame times and sensor readings to a PC Doctor live
    /// session while capturing (the address the Live page shows). https://,
    /// or http:// to this PC or a private network only.
    #[arg(long, value_name = "URL")]
    live_url: Option<String>,
}

/// Streaming to a live session, when --live-url is given.
struct Live {
    sender: live::LiveSender,
    times: Option<live::FrameTimes>,
}

/// What the run did, in plain words, for collector.log and the console.
/// Never holds a file path, a computer name or a user name.
struct Log {
    lines: Vec<String>,
    warnings: Vec<String>,
}

impl Log {
    fn step(&mut self, text: &str) {
        println!("  {text}");
        self.lines
            .push(format!("{}  {text}", Local::now().format("%H:%M:%S")));
    }

    fn warn(&mut self, text: &str) {
        println!("  ! {text}");
        self.lines.push(format!(
            "{}  WARNING: {text}",
            Local::now().format("%H:%M:%S")
        ));
        self.warnings.push(text.to_string());
    }
}

/// Where frames come from during the capture.
struct FrameSource {
    tail: FileTail,
    filter: FrameFilter<BufWriter<File>>,
    /// The PresentMon we started, if any.
    child: Option<Child>,
    /// Our own copy of PresentMon's unfiltered CSV, deleted at the end.
    raw_csv: Option<PathBuf>,
    version: Option<String>,
}

fn main() -> ExitCode {
    let args = Args::parse();
    match capture(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(message) => {
            eprintln!("pcdoctor-capture: {message}");
            ExitCode::FAILURE
        }
    }
}

fn capture(args: &Args) -> Result<(), String> {
    if !(args.interval >= 0.1 && args.interval <= 60.0) {
        return Err("--interval must be between 0.1 and 60 seconds".into());
    }
    println!();
    println!("PC Doctor capture {COLLECTOR_VERSION} (Rust)");
    println!("Read-only: this changes nothing on this PC. It reads frame times and sensors only.");
    println!();

    let mut log = Log {
        lines: Vec::new(),
        warnings: Vec::new(),
    };
    let label = privacy::scrub(&args.label, 200);

    // ---- where it goes
    let output_dir = match &args.output_dir {
        Some(dir) => dir.clone(),
        None => default_output_dir()?,
    };
    let started_local = Local::now();
    let started_utc = Utc::now();
    let name = run::run_name(&started_local);
    let run_dir = output_dir.join(&name);
    fs::create_dir_all(&run_dir)
        .map_err(|e| format!("cannot create the run folder {}: {e}", run_dir.display()))?;

    // ---- sensors: check once that they answer, and fix the GPU to follow
    let sensor_source = if args.no_sensors {
        None
    } else if let Some(path) = &args.lhm_file {
        Some(LhmSource::File(path.clone()))
    } else {
        Some(LhmSource::http(&args.lhm_url, LHM_TIMEOUT))
    };
    let mut gpu_prefix = None;
    // Without LibreHardwareMonitor, Windows' own counters still give loads,
    // speeds and RAM use (no temperatures), as in the PowerShell collector.
    let mut windows_sensors: Option<WindowsSensors> = None;
    let mut sensor_source = sensor_source;
    if let Some(source) = &sensor_source {
        match source.read() {
            Ok(first) => {
                gpu_prefix = sensors::select_gpu_prefix(&first);
                // One snapshot of sensor names, so a wrong mapping on unusual
                // hardware can be diagnosed later. Sensor nodes only: no
                // hardware model names.
                let raw = serde_json::json!({ "sensors": first });
                run::write_json(&run_dir.join("sensors_raw.json"), &raw)
                    .map_err(|e| format!("cannot write sensors_raw.json: {e}"))?;
                log.step("Sensors: LibreHardwareMonitor");
            }
            Err(reason) => match WindowsSensors::open() {
                // A saved data.json (--lhm-file) is a test: no fallback then.
                Ok(fallback) if args.lhm_file.is_none() => {
                    windows_sensors = Some(fallback);
                    sensor_source = None;
                    log.warn(&format!(
                        "{reason}, so this run has Windows' own readings (load, speed, RAM) \
                         and no temperatures. Start LibreHardwareMonitor and switch on \
                         Options > Remote Web Server > Run, then capture again."
                    ));
                }
                _ => log.warn(&format!(
                    "{reason}. There will be no temperatures in this run unless it starts \
                     answering. Start LibreHardwareMonitor and switch on Options > Remote Web \
                     Server > Run."
                )),
            },
        }
    }
    let sensor_source = sensor_source;

    if args.start_delay > 0 {
        println!(
            "  Switch to your game now. Capturing {} seconds, starting in {} ...",
            args.seconds, args.start_delay
        );
        std::thread::sleep(Duration::from_secs(args.start_delay));
    }

    // ---- live view (optional, best effort: the run on disk is the record)
    let mut live = match &args.live_url {
        Some(url) => {
            let sender = live::LiveSender::new(url)?;
            log.step("Live view: streaming frame times and sensors about once a second");
            Some(Live {
                sender,
                times: None,
            })
        }
        None => None,
    };

    // ---- frames
    let mut frames = open_frame_source(args, &run_dir, &mut log)?;

    // ---- the capture loop: sample sensors on a fixed schedule, read new
    // PresentMon rows in between. One thread: nothing here is busy enough to
    // need more, and fewer threads means less overhead on the game's PC.
    log.step(&format!("Capturing for {} seconds ...", args.seconds));
    let mut rows = vec![sensors::header()];
    let mut samples_with_data = 0u64;
    let clock = Instant::now();
    let duration = Duration::from_secs(args.seconds);
    let interval = Duration::from_secs_f64(args.interval);
    let mut next_sample = Duration::ZERO;
    let mut sample_errors = 0u64;
    while clock.elapsed() < duration {
        let sampling = sensor_source.is_some() || windows_sensors.is_some();
        if sampling && clock.elapsed() >= next_sample {
            let elapsed = clock.elapsed().as_secs_f64();
            let sample = match (&sensor_source, &windows_sensors) {
                (Some(source), _) => match source.read() {
                    Ok(list) => {
                        if gpu_prefix.is_none() {
                            gpu_prefix = sensors::select_gpu_prefix(&list);
                        }
                        sensors::map_sample(&list, gpu_prefix.as_deref())
                    }
                    Err(_) => {
                        // A missed sample is an empty row, as in the
                        // PowerShell collector; the analyzer skips gaps.
                        sample_errors += 1;
                        Sample::default()
                    }
                },
                (None, Some(windows)) => windows.read(),
                (None, None) => Sample::default(),
            };
            if !sample.is_empty() {
                samples_with_data += 1;
                if let Some(live) = live.as_mut() {
                    live.sender.sensors(elapsed, &sample);
                }
            }
            rows.push(sensors::format_row(elapsed, &sample));
            // Fixed schedule (not "interval after the last one"), so slow
            // reads do not make the samples drift.
            while next_sample <= clock.elapsed() {
                next_sample += interval;
            }
        }
        if let Some(source) = frames.as_mut() {
            feed(source, false, live.as_mut())?;
        }
        if let Some(live) = live.as_mut() {
            send_live(live, &mut log);
        }
        let until_end = duration.saturating_sub(clock.elapsed());
        let until_sample = next_sample.saturating_sub(clock.elapsed());
        let mut wait = POLL_INTERVAL.min(until_end);
        if sampling {
            wait = wait.min(until_sample);
        }
        std::thread::sleep(wait);
    }
    let actual_seconds = round1(clock.elapsed().as_secs_f64());
    // Frames PresentMon wrote just before it stopped still go to the live
    // view; finish_frames reads the very last ones for the file.
    if let Some(source) = frames.as_mut() {
        feed(source, false, live.as_mut())?;
    }
    if let Some(live) = live.as_mut() {
        if let live::Sent::Stopped(reason) | live::Sent::Later(reason) = live.sender.finish() {
            log.warn(&format!("Live view: {reason}"));
        }
        log.step(&format!(
            "Live view: {} lines sent, {} not delivered",
            live.sender.lines_sent, live.sender.lines_dropped
        ));
    }
    if sample_errors > 0 {
        log.warn(&format!(
            "{sample_errors} sensor samples could not be read and were left empty."
        ));
    }

    // ---- sensors.csv
    let sample_count = (rows.len() - 1) as u64;
    let any_source = sensor_source.is_some() || windows_sensors.is_some();
    let sensors_info = if any_source && samples_with_data > 0 {
        run::write_lines(&run_dir.join("sensors.csv"), &rows)
            .map_err(|e| format!("cannot write sensors.csv: {e}"))?;
        SensorsInfo {
            // The same names as the PowerShell collector's manifest.
            source: Some(
                if windows_sensors.is_some() {
                    "windows"
                } else {
                    "librehardwaremonitor"
                }
                .into(),
            ),
            interval_seconds: args.interval,
            file: Some("sensors.csv".into()),
            samples: sample_count,
        }
    } else {
        if any_source {
            log.warn("No sensor reading was recorded, so sensors.csv was not written.");
        }
        SensorsInfo {
            source: None,
            interval_seconds: args.interval,
            file: None,
            samples: 0,
        }
    };

    // ---- presentmon.csv
    let mut target_process = Some(args.process.trim().to_string());
    let presentmon_info = match frames {
        Some(source) => finish_frames(source, &run_dir, &mut log, &mut target_process)?,
        None => PresentMonInfo::default(),
    };

    // ---- manifest, log, zip
    let usage = resources::current();
    let manifest = Manifest {
        schema_version: SCHEMA_VERSION,
        run_id: uuid::Uuid::new_v4().to_string(),
        collector: CollectorInfo {
            name: COLLECTOR_NAME.into(),
            version: COLLECTOR_VERSION.into(),
        },
        started_at: run::iso_utc(&started_utc),
        finished_at: run::iso_utc(&Utc::now()),
        mode: "capture".into(),
        label,
        capture: Capture {
            requested_seconds: args.seconds,
            actual_seconds,
            target_process,
            presentmon: presentmon_info,
            sensors: sensors_info,
        },
        event_window_days: None,
        is_admin: None,
        warnings: log.warnings.clone(),
        collector_resources: usage.clone(),
    };
    if let Some(usage) = &usage {
        log.step(&format!("This collector used {}", describe(usage)));
    }
    run::write_json(&run_dir.join("manifest.json"), &manifest)
        .map_err(|e| format!("cannot write manifest.json: {e}"))?;
    run::write_lines(&run_dir.join("collector.log"), &log.lines)
        .map_err(|e| format!("cannot write collector.log: {e}"))?;

    println!();
    println!("  Run folder: {}", run_dir.display());
    if !args.no_zip {
        let zip_path = output_dir.join(format!("{name}.zip"));
        match run::zip_run(&run_dir, &zip_path) {
            Ok(_) => println!("  Zip file:   {}", zip_path.display()),
            Err(e) => println!("  ! Could not create the zip: {e}"),
        }
    }
    // Measured again after zipping: the total for the whole program.
    if let Some(usage) = resources::current() {
        println!(
            "  Collector overhead (whole run, incl. zip): {}",
            describe(&usage)
        );
    }
    println!();
    Ok(())
}

/// "0.42 s CPU (user 0.30 s, kernel 0.12 s), peak memory 5.1 MB"
fn describe(usage: &ResourceUsage) -> String {
    let memory = usage
        .peak_memory_bytes
        .map(|b| format!("{:.1} MB", b as f64 / 1_000_000.0))
        .unwrap_or_else(|| "unknown".into());
    format!(
        "{:.2} s CPU (user {:.2} s, kernel {:.2} s), peak memory {memory} ({})",
        usage.cpu_seconds, usage.cpu_user_seconds, usage.cpu_kernel_seconds, usage.peak_memory_kind
    )
}

/// A "runs" folder next to the executable, as the PowerShell collector puts
/// its runs next to its script (handy on a USB stick).
fn default_output_dir() -> Result<PathBuf, String> {
    let exe =
        std::env::current_exe().map_err(|e| format!("cannot find this program's folder: {e}"))?;
    let dir = exe.parent().unwrap_or(Path::new("."));
    Ok(dir.join("runs"))
}

/// Start PresentMon or open the CSV to follow, and the filtered output file.
fn open_frame_source(
    args: &Args,
    run_dir: &Path,
    log: &mut Log,
) -> Result<Option<FrameSource>, String> {
    let (csv_path, child, raw_csv, version) = if let Some(exe) = &args.start_presentmon {
        let raw = run_dir.join("presentmon_raw.csv");
        remove_if_exists(&raw).map_err(|e| format!("cannot clear an old PresentMon file: {e}"))?;
        let version = version_from_file_name(exe);
        // PresentMon prints its banner on stderr; neither stream is needed.
        let child = Command::new(exe)
            .args(presentmon_arguments(&raw, args.seconds, &args.process))
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn();
        match child {
            Ok(child) => {
                log.step(&format!(
                    "Frame times: PresentMon {}",
                    version.as_deref().unwrap_or("(version unknown)")
                ));
                (raw.clone(), Some(child), Some(raw), version)
            }
            Err(e) => {
                log.warn(&format!(
                    "PresentMon could not be started ({}), so frame times are skipped.",
                    e.kind()
                ));
                return Ok(None);
            }
        }
    } else if let Some(path) = &args.presentmon_csv {
        log.step("Frame times: following an existing PresentMon file");
        (path.clone(), None, None, None)
    } else {
        log.warn("No PresentMon source was given (--start-presentmon or --presentmon-csv), so frame times are skipped.");
        return Ok(None);
    };

    let out = File::create(run_dir.join("presentmon.csv"))
        .map_err(|e| format!("cannot write presentmon.csv: {e}"))?;
    Ok(Some(FrameSource {
        tail: FileTail::new(csv_path),
        filter: FrameFilter::new(&args.process, BufWriter::new(out)),
        child,
        raw_csv,
        version,
    }))
}

/// Read new PresentMon lines into the filter. With `last`, this is the final
/// read: an unterminated last row is kept only if we started PresentMon (it
/// has exited, so the row is complete).
/// Send what is due to the live session, and say once if it has stopped.
fn send_live(live: &mut Live, log: &mut Log) {
    let was_stopped = live.sender.is_stopped();
    match live.sender.tick(Instant::now()) {
        live::Sent::Stopped(reason) if !was_stopped => {
            log.warn(&format!("Live view stopped: {reason}. The capture carries on."))
        }
        live::Sent::Later(reason) if live.sender.failures == 1 => log.warn(&format!(
            "Live view: PC Doctor did not take the samples ({reason}); retrying. The capture carries on."
        )),
        _ => {}
    }
}

fn feed(source: &mut FrameSource, last: bool, mut live: Option<&mut Live>) -> Result<(), String> {
    let lines = if last {
        let writer_finished = source.child.is_some();
        source.tail.finish(writer_finished)
    } else {
        source.tail.poll()
    };
    let lines = lines.map_err(|e| format!("cannot read the PresentMon file ({})", e.kind()))?;
    for line in lines {
        let header_before = source.filter.header_seen();
        let frames_before = source.filter.summary().frames;
        source
            .filter
            .push_line(&line)
            .map_err(|e| format!("cannot write presentmon.csv: {e}"))?;
        if let Some(live) = live.as_deref_mut() {
            if !header_before && source.filter.header_seen() {
                live.times = Some(live::FrameTimes::from_header(&line));
            } else if source.filter.summary().frames > frames_before {
                // A row of the target program: only its frame time is sent.
                if let Some((seconds, ms)) = live.times.as_mut().and_then(|t| t.read(&line)) {
                    live.sender.frame(seconds, ms);
                }
            }
        }
    }
    Ok(())
}

/// Wait for PresentMon, read the last rows, and describe what was kept.
fn finish_frames(
    mut source: FrameSource,
    run_dir: &Path,
    log: &mut Log,
    target_process: &mut Option<String>,
) -> Result<PresentMonInfo, String> {
    let mut info = PresentMonInfo {
        version: source.version.clone(),
        ..PresentMonInfo::default()
    };
    if let Some(child) = source.child.as_mut() {
        log.step("Waiting for PresentMon to finish ...");
        info.exit_code = wait_or_kill(child, log);
    }
    let last_read = if source.tail.is_open() || source.child.is_some() {
        feed(&mut source, true, None)
    } else {
        Err("the PresentMon file was never found".to_string())
    };
    if let Some(raw) = &source.raw_csv {
        // The unfiltered file names every program on screen: never keep it.
        remove_if_exists(raw)
            .map_err(|e| format!("cannot delete PresentMon's unfiltered file: {e}"))?;
    }
    let (_, summary) = source
        .filter
        .finish()
        .map_err(|e| format!("cannot write presentmon.csv: {e}"))?;
    if let Err(reason) = last_read {
        log.warn(&format!(
            "PresentMon wrote no frame-time file ({reason}). Nothing was drawing to the screen, \
             or it lacked administrator rights."
        ));
    }
    info.columns = summary.style.map(|s| s.as_str().to_string());
    info.other_processes_removed = summary.other_processes_removed;
    info.other_frames_removed = summary.other_frames_removed;
    if !summary.filtered && summary.frames > 0 {
        log.warn(
            "The PresentMon file has no Application column, so its rows were kept unfiltered.",
        );
    }
    if summary.malformed_rows > 0 {
        log.warn(&format!(
            "{} short PresentMon rows were skipped.",
            summary.malformed_rows
        ));
    }
    if summary.frames > 0 {
        info.used = true;
        info.file = Some("presentmon.csv".into());
        info.frames = summary.frames;
        if let Some(app) = summary.application {
            *target_process = Some(app);
        }
        log.step(&format!(
            "Frame times: {} frames kept; {} other programs ({} rows) removed",
            summary.frames, summary.other_processes_removed, summary.other_frames_removed
        ));
    } else {
        remove_if_exists(&run_dir.join("presentmon.csv"))
            .map_err(|e| format!("cannot remove an empty presentmon.csv: {e}"))?;
        if summary.other_frames_removed > 0 {
            log.warn("PresentMon recorded other programs but no frames of the tested program. Was the name right, and was it on screen?");
        } else {
            log.warn("PresentMon recorded no frames. Was the game running and on screen during the capture?");
        }
    }
    Ok(info)
}

/// PresentMon stops by itself after `--timed`; give it a grace period, then
/// close it.
fn wait_or_kill(child: &mut Child, log: &mut Log) -> Option<i32> {
    let deadline = Instant::now() + PRESENTMON_GRACE;
    loop {
        match child.try_wait() {
            Ok(Some(status)) => return status.code(),
            Ok(None) if Instant::now() < deadline => std::thread::sleep(POLL_INTERVAL),
            Ok(None) => {
                log.warn("PresentMon did not stop by itself and was closed.");
                let _ = child.kill();
                return child.wait().ok().and_then(|s| s.code());
            }
            Err(_) => return None,
        }
    }
}
