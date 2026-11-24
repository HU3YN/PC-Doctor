//! PC Doctor capture collector, as a library.
//!
//! Everything the `pcdoctor-capture` binary does lives here, split by job, so
//! each part can be tested on any OS with fixture files:
//!
//! - [`tail`]: read a file that another program is still writing, line by line
//! - [`presentmon`]: keep only the tested program's rows of PresentMon's CSV
//! - [`lhm`]: read LibreHardwareMonitor's `data.json` into a flat sensor list
//! - [`sensors`]: map those sensors to the fixed `sensors.csv` columns
//! - [`manifest`]: the `manifest.json` structure
//! - [`run`]: run folder name, file writing and the zip
//! - [`resources`]: this process's own CPU time and peak memory
//! - [`privacy`]: scrubbing the one piece of free text (the label)
//!
//! READ-ONLY BY DESIGN: nothing here changes a setting or installs anything.
//! The output format is the one in `docs/run-format.md`, the same the
//! PowerShell collector writes, so the analyzer reads both.

pub mod lhm;
pub mod live;
pub mod manifest;
pub mod nvidia;
pub mod presentmon;
pub mod privacy;
pub mod resources;
pub mod run;
pub mod sensors;
pub mod signature;
pub mod tail;
pub mod winsensors;

/// `schema_version` in manifest.json. Must match the PowerShell collector's
/// `$script:SchemaVersion`; the analyzer warns about versions it does not know.
pub const SCHEMA_VERSION: u32 = 1;

/// Written to `collector.name` so a run says which collector made it.
pub const COLLECTOR_NAME: &str = "pcdoctor-capture-rs";

/// This crate's version, from Cargo.toml.
pub const COLLECTOR_VERSION: &str = env!("CARGO_PKG_VERSION");
