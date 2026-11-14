//! `manifest.json`: what was collected, when and how (docs/run-format.md).
//!
//! Field names and nesting are the PowerShell collector's, so the analyzer and
//! the API read this file the same way. Fields this collector adds
//! (`collector_resources`, `capture.presentmon.other_frames_removed`,
//! `capture.presentmon.columns`) are new keys, which every reader ignores
//! ("Add fields freely" in run-format.md).

use serde::Serialize;

use crate::resources::ResourceUsage;

#[derive(Debug, Clone, Serialize)]
pub struct Manifest {
    pub schema_version: u32,
    pub run_id: String,
    pub collector: CollectorInfo,
    /// UTC, ISO 8601, to the second: `2026-11-14T18:00:00Z`.
    pub started_at: String,
    pub finished_at: String,
    /// Always `capture`: this collector only does the capture part.
    pub mode: String,
    pub label: String,
    pub capture: Capture,
    /// `null`: this collector does not read the event log.
    pub event_window_days: Option<u32>,
    /// `null`: not checked by this collector.
    pub is_admin: Option<bool>,
    pub warnings: Vec<String>,
    /// This collector's own cost, measured just before the manifest is
    /// written (so it covers the whole capture but not the zipping).
    pub collector_resources: Option<ResourceUsage>,
}

#[derive(Debug, Clone, Serialize)]
pub struct CollectorInfo {
    pub name: String,
    pub version: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct Capture {
    pub requested_seconds: u64,
    pub actual_seconds: f64,
    /// The program's name as PresentMon wrote it, or as given on the command
    /// line when no frame of it was seen. The analyzer uses it to pick rows.
    pub target_process: Option<String>,
    pub presentmon: PresentMonInfo,
    pub sensors: SensorsInfo,
}

#[derive(Debug, Clone, Serialize, Default)]
pub struct PresentMonInfo {
    pub used: bool,
    pub version: Option<String>,
    /// `presentmon.csv` when frames were kept, otherwise `null`.
    pub file: Option<String>,
    pub exit_code: Option<i32>,
    pub frames: u64,
    pub other_processes_removed: u64,
    pub other_frames_removed: u64,
    /// `v1`, `v2`, `v2_metrics` or `unknown` (see presentmon::HeaderStyle).
    pub columns: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct SensorsInfo {
    /// `librehardwaremonitor`, or `null` when no sensors were read.
    pub source: Option<String>,
    pub interval_seconds: f64,
    pub file: Option<String>,
    pub samples: u64,
}

/// Round to one decimal, as the PowerShell collector does for actual_seconds.
pub fn round1(value: f64) -> f64 {
    (value * 10.0).round() / 10.0
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::Value;

    fn example() -> Manifest {
        Manifest {
            schema_version: crate::SCHEMA_VERSION,
            run_id: "00000000-0000-4000-8000-000000000000".into(),
            collector: CollectorInfo {
                name: crate::COLLECTOR_NAME.into(),
                version: crate::COLLECTOR_VERSION.into(),
            },
            started_at: "2026-11-14T18:00:00Z".into(),
            finished_at: "2026-11-14T18:05:00Z".into(),
            mode: "capture".into(),
            label: "bench 3".into(),
            capture: Capture {
                requested_seconds: 300,
                actual_seconds: round1(300.04),
                target_process: Some("Game.exe".into()),
                presentmon: PresentMonInfo {
                    used: true,
                    frames: 42,
                    file: Some("presentmon.csv".into()),
                    ..PresentMonInfo::default()
                },
                sensors: SensorsInfo {
                    source: Some("librehardwaremonitor".into()),
                    interval_seconds: 1.0,
                    file: Some("sensors.csv".into()),
                    samples: 300,
                },
            },
            event_window_days: None,
            is_admin: None,
            warnings: vec![],
            collector_resources: Some(ResourceUsage {
                cpu_user_seconds: 1.0,
                cpu_kernel_seconds: 0.5,
                cpu_seconds: 1.5,
                peak_memory_bytes: Some(4_000_000),
                peak_memory_kind: "test".into(),
            }),
        }
    }

    #[test]
    fn has_the_run_format_field_names() {
        let value: Value = serde_json::to_value(example()).unwrap();
        for key in [
            "schema_version",
            "run_id",
            "collector",
            "started_at",
            "finished_at",
            "mode",
            "label",
            "capture",
            "event_window_days",
            "is_admin",
            "warnings",
        ] {
            assert!(value.get(key).is_some(), "manifest lacks {key}");
        }
        assert_eq!(value["schema_version"], 1);
        assert_eq!(value["collector"]["name"], "pcdoctor-capture-rs");
        let capture = &value["capture"];
        for key in [
            "requested_seconds",
            "actual_seconds",
            "target_process",
            "presentmon",
            "sensors",
        ] {
            assert!(capture.get(key).is_some(), "capture lacks {key}");
        }
        for key in [
            "used",
            "version",
            "exit_code",
            "frames",
            "other_processes_removed",
        ] {
            assert!(
                capture["presentmon"].get(key).is_some(),
                "presentmon lacks {key}"
            );
        }
        for key in ["source", "interval_seconds", "samples"] {
            assert!(capture["sensors"].get(key).is_some(), "sensors lacks {key}");
        }
        assert_eq!(capture["actual_seconds"], 300.0);
        assert_eq!(value["collector_resources"]["cpu_seconds"], 1.5);
    }
}
