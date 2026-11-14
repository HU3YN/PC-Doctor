//! LibreHardwareMonitor sensors -> one row of `sensors.csv`.
//!
//! The columns and the mapping rules are the PowerShell collector's
//! (`ConvertTo-PCDoctorSample` in collector/PCDoctorCollector.psm1), so a run
//! from either collector reads the same. Sensor names were read from
//! LibreHardwareMonitor's source: IntelCpu.cs, Amd17Cpu.cs, GenericCpu.cs,
//! NvidiaGpu.cs, AmdGpu.cs, TotalMemory.cs.
//!
//! Like PowerShell's `-eq`, name comparisons ignore case.

use std::collections::BTreeSet;
use std::sync::LazyLock;

use regex::Regex;

use crate::lhm::Sensor;

/// The fixed columns of sensors.csv, in file order (docs/run-format.md).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Column {
    CpuTemp,
    CpuLoad,
    CpuCoreMaxLoad,
    CpuClock,
    CpuPerf,
    CpuPower,
    GpuTemp,
    GpuHotspot,
    GpuLoad,
    GpuClock,
    GpuPower,
    GpuFan,
    GpuVramUsed,
    RamUsed,
}

impl Column {
    /// Every column, in the order they appear in the file.
    pub const ALL: [Column; 14] = [
        Column::CpuTemp,
        Column::CpuLoad,
        Column::CpuCoreMaxLoad,
        Column::CpuClock,
        Column::CpuPerf,
        Column::CpuPower,
        Column::GpuTemp,
        Column::GpuHotspot,
        Column::GpuLoad,
        Column::GpuClock,
        Column::GpuPower,
        Column::GpuFan,
        Column::GpuVramUsed,
        Column::RamUsed,
    ];

    /// The column's name in the CSV header. The analyzer reads by name.
    pub fn name(self) -> &'static str {
        match self {
            Column::CpuTemp => "cpu_temp_c",
            Column::CpuLoad => "cpu_load_pct",
            Column::CpuCoreMaxLoad => "cpu_core_max_load_pct",
            Column::CpuClock => "cpu_clock_mhz",
            // Only Windows' own counters give this; LibreHardwareMonitor has
            // no such sensor, so this collector always leaves it empty.
            Column::CpuPerf => "cpu_perf_pct",
            Column::CpuPower => "cpu_power_w",
            Column::GpuTemp => "gpu_temp_c",
            Column::GpuHotspot => "gpu_hotspot_c",
            Column::GpuLoad => "gpu_load_pct",
            Column::GpuClock => "gpu_clock_mhz",
            Column::GpuPower => "gpu_power_w",
            Column::GpuFan => "gpu_fan_rpm",
            Column::GpuVramUsed => "gpu_vram_used_pct",
            Column::RamUsed => "ram_used_pct",
        }
    }

    fn index(self) -> usize {
        // The enum's declaration order is the file order.
        self as usize
    }
}

/// One sample: a value (or "no reading") for every column.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct Sample {
    values: [Option<f64>; 14],
}

impl Sample {
    pub fn get(&self, column: Column) -> Option<f64> {
        self.values[column.index()]
    }

    pub fn set(&mut self, column: Column, value: Option<f64>) {
        // NaN or infinity is not a reading.
        self.values[column.index()] = value.filter(|v| v.is_finite());
    }

    /// True when not a single column has a reading.
    pub fn is_empty(&self) -> bool {
        self.values.iter().all(Option::is_none)
    }
}

/// `elapsed_s,cpu_temp_c,...` - the first line of sensors.csv.
pub fn header() -> String {
    let mut line = String::from("elapsed_s");
    for column in Column::ALL {
        line.push(',');
        line.push_str(column.name());
    }
    line
}

/// One CSV line: elapsed seconds with two decimals, then each column with up
/// to two decimals and an empty cell for "no reading". Always a dot for
/// decimals (Rust's formatting ignores the Windows region settings).
pub fn format_row(elapsed_seconds: f64, sample: &Sample) -> String {
    let mut line = format!("{elapsed_seconds:.2}");
    for column in Column::ALL {
        line.push(',');
        if let Some(value) = sample.get(column) {
            line.push_str(&format_number(value));
        }
    }
    line
}

/// 71.456 -> "71.46", 55.0 -> "55", 0.5 -> "0.5" (PowerShell's '0.##').
pub fn format_number(value: f64) -> String {
    let text = format!("{value:.2}");
    let text = text.trim_end_matches('0').trim_end_matches('.');
    if text == "-0" {
        "0".to_string()
    } else {
        text.to_string()
    }
}

/// Which graphics adapter to follow: a graphics card (NVIDIA, then AMD)
/// before Intel graphics. Decided once, on the first sample, so the GPU
/// columns never switch adapters halfway through a run.
pub fn select_gpu_prefix(sensors: &[Sensor]) -> Option<String> {
    static GPU: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(r"(?i)^(/gpu-[a-z-]+/\d+)/").expect("valid regex"));
    // Sorted and without duplicates, like PowerShell's Sort-Object -Unique.
    let prefixes: BTreeSet<String> = sensors
        .iter()
        .filter_map(|s| GPU.captures(&s.id).map(|c| c[1].to_string()))
        .collect();
    for kind in ["/gpu-nvidia/", "/gpu-amd/", "/gpu-intel/"] {
        if let Some(found) = prefixes.iter().find(|p| p.starts_with(kind)) {
            return Some(found.clone());
        }
    }
    prefixes.into_iter().next()
}

/// The first reading of a sensor of `kind` whose name is one of `names`,
/// trying the names in order.
fn value_by_name(sensors: &[&Sensor], kind: &str, names: &[&str]) -> Option<f64> {
    names.iter().find_map(|name| {
        sensors.iter().find_map(|s| {
            let matches = s.kind.eq_ignore_ascii_case(kind) && s.text.eq_ignore_ascii_case(name);
            if matches {
                s.value
            } else {
                None
            }
        })
    })
}

/// Readings of every sensor of `kind` whose name matches `pattern`.
fn values_matching<'a>(
    sensors: &'a [&Sensor],
    kind: &'a str,
    pattern: &'a Regex,
) -> impl Iterator<Item = f64> + 'a {
    sensors
        .iter()
        .filter(move |s| s.kind.eq_ignore_ascii_case(kind) && pattern.is_match(&s.text))
        .filter_map(|s| s.value)
}

fn max(values: impl Iterator<Item = f64>) -> Option<f64> {
    values.fold(None, |best, v| Some(best.map_or(v, |b: f64| b.max(v))))
}

fn average(values: impl Iterator<Item = f64>) -> Option<f64> {
    let (sum, count) = values.fold((0.0, 0u32), |(sum, n), v| (sum + v, n + 1));
    (count > 0).then(|| sum / f64::from(count))
}

/// Map one snapshot of sensors to a sample. `gpu_prefix` is the adapter chosen
/// on the first sample; `None` chooses again from this snapshot.
pub fn map_sample(sensors: &[Sensor], gpu_prefix: Option<&str>) -> Sample {
    static CORE_N: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(r"(?i)Core #\d+").expect("valid regex"));
    static CORE_N_END: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(r"(?i)Core #\d+$").expect("valid regex"));
    static DISTANCE: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(r"(?i)Distance").expect("valid regex"));

    let mut sample = Sample::default();
    let starts_with = |s: &Sensor, prefix: &str| {
        s.id.get(..prefix.len())
            .is_some_and(|start| start.eq_ignore_ascii_case(prefix))
    };

    // ---- processor: the first CPU package only.
    let cpu: Vec<&Sensor> = sensors
        .iter()
        .filter(|s| starts_with(s, "/intelcpu/0/") || starts_with(s, "/amdcpu/0/"))
        .collect();
    if !cpu.is_empty() {
        let temperature = value_by_name(
            &cpu,
            "Temperature",
            &[
                "CPU Package",
                "Core (Tctl/Tdie)",
                "Core (Tdie)",
                "Core (Tctl)",
                "Core Max",
                "CCDs Max (Tdie)",
                "Core Average",
            ],
        )
        .or_else(|| {
            // No known name: the hottest temperature, skipping "Distance to
            // TjMax" sensors, which count *down* as the chip heats up.
            max(cpu
                .iter()
                .filter(|s| s.kind.eq_ignore_ascii_case("Temperature"))
                .filter(|s| !DISTANCE.is_match(&s.text))
                .filter_map(|s| s.value))
        });
        sample.set(Column::CpuTemp, temperature);
        sample.set(Column::CpuLoad, value_by_name(&cpu, "Load", &["CPU Total"]));
        let core_max = value_by_name(&cpu, "Load", &["CPU Core Max"])
            .or_else(|| max(values_matching(&cpu, "Load", &CORE_N)));
        sample.set(Column::CpuCoreMaxLoad, core_max);
        // The average core clock, never the bus speed.
        let clock = value_by_name(&cpu, "Clock", &["Cores (Average)"])
            .or_else(|| average(values_matching(&cpu, "Clock", &CORE_N_END)));
        sample.set(Column::CpuClock, clock);
        sample.set(
            Column::CpuPower,
            value_by_name(&cpu, "Power", &["CPU Package", "Package"]),
        );
    }

    // ---- graphics: the one adapter chosen for the run.
    let chosen = match gpu_prefix {
        Some(prefix) => Some(prefix.to_string()),
        None => select_gpu_prefix(sensors),
    };
    if let Some(prefix) = chosen {
        let prefix = format!("{prefix}/");
        let gpu: Vec<&Sensor> = sensors.iter().filter(|s| starts_with(s, &prefix)).collect();
        sample.set(
            Column::GpuTemp,
            value_by_name(&gpu, "Temperature", &["GPU Core"]),
        );
        sample.set(
            Column::GpuHotspot,
            value_by_name(&gpu, "Temperature", &["GPU Hot Spot"]),
        );
        sample.set(
            Column::GpuLoad,
            value_by_name(&gpu, "Load", &["GPU Core", "D3D 3D"]),
        );
        sample.set(
            Column::GpuClock,
            value_by_name(&gpu, "Clock", &["GPU Core"]),
        );
        sample.set(
            Column::GpuPower,
            value_by_name(&gpu, "Power", &["GPU Package", "GPU Power", "GPU Core"]),
        );
        let fan = gpu
            .iter()
            .filter(|s| s.kind.eq_ignore_ascii_case("Fan"))
            .find_map(|s| s.value);
        sample.set(Column::GpuFan, fan);
        // Used / total is a ratio, so it does not matter which unit this
        // LibreHardwareMonitor version reports data sizes in.
        let used = value_by_name(&gpu, "SmallData", &["GPU Memory Used"])
            .or_else(|| value_by_name(&gpu, "Data", &["GPU Memory Used"]));
        let total = value_by_name(&gpu, "SmallData", &["GPU Memory Total"])
            .or_else(|| value_by_name(&gpu, "Data", &["GPU Memory Total"]));
        let vram = match (used, total) {
            (Some(used), Some(total)) if total > 0.0 => Some((100.0 * used / total).min(100.0)),
            _ => value_by_name(&gpu, "Load", &["GPU Memory"]),
        };
        sample.set(Column::GpuVramUsed, vram);
    }

    // ---- memory: physical RAM (/ram/), not virtual memory (/vram/).
    let ram: Vec<&Sensor> = sensors.iter().filter(|s| starts_with(s, "/ram/")).collect();
    sample.set(Column::RamUsed, value_by_name(&ram, "Load", &["Memory"]));
    sample
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::lhm::{flatten, LhmSource};

    fn sensor(id: &str, kind: &str, text: &str, value: f64) -> Sensor {
        Sensor {
            id: id.into(),
            kind: kind.into(),
            text: text.into(),
            value: Some(value),
        }
    }

    /// The same sensors as the PowerShell collector's Pester test.
    fn intel_nvidia() -> Vec<Sensor> {
        vec![
            sensor(
                "/intelcpu/0/temperature/8",
                "Temperature",
                "CPU Package",
                71.0,
            ),
            sensor(
                "/intelcpu/0/temperature/0",
                "Temperature",
                "P-Core #1",
                69.0,
            ),
            sensor(
                "/intelcpu/0/temperature/9",
                "Temperature",
                "P-Core #1 Distance to TjMax",
                31.0,
            ),
            sensor("/intelcpu/0/load/0", "Load", "CPU Total", 42.0),
            sensor("/intelcpu/0/load/1", "Load", "CPU Core Max", 97.0),
            sensor("/intelcpu/0/clock/0", "Clock", "Bus Speed", 100.0),
            sensor("/intelcpu/0/clock/1", "Clock", "P-Core #1", 5000.0),
            sensor("/intelcpu/0/clock/2", "Clock", "E-Core #1", 4000.0),
            sensor("/intelcpu/0/power/0", "Power", "CPU Package", 120.5),
            sensor("/gpu-intel-integrated/0/load/0", "Load", "GPU Core", 3.0),
            sensor(
                "/gpu-nvidia/0/temperature/0",
                "Temperature",
                "GPU Core",
                66.0,
            ),
            sensor(
                "/gpu-nvidia/0/temperature/2",
                "Temperature",
                "GPU Hot Spot",
                78.0,
            ),
            sensor("/gpu-nvidia/0/load/0", "Load", "GPU Core", 98.0),
            sensor("/gpu-nvidia/0/clock/0", "Clock", "GPU Core", 1905.0),
            sensor("/gpu-nvidia/0/power/0", "Power", "GPU Package", 210.0),
            sensor("/gpu-nvidia/0/fan/1", "Fan", "GPU Fan", 1500.0),
            sensor(
                "/gpu-nvidia/0/smalldata/1",
                "SmallData",
                "GPU Memory Used",
                6144.0,
            ),
            sensor(
                "/gpu-nvidia/0/smalldata/2",
                "SmallData",
                "GPU Memory Total",
                8192.0,
            ),
            sensor("/ram/load/0", "Load", "Memory", 55.0),
            sensor("/vram/load/1", "Load", "Memory", 12.0),
        ]
    }

    #[test]
    fn maps_an_intel_cpu_and_an_nvidia_card() {
        let sample = map_sample(&intel_nvidia(), None);
        assert_eq!(sample.get(Column::CpuTemp), Some(71.0));
        assert_eq!(sample.get(Column::CpuLoad), Some(42.0));
        assert_eq!(sample.get(Column::CpuCoreMaxLoad), Some(97.0));
        assert_eq!(sample.get(Column::CpuClock), Some(4500.0)); // cores, not the bus
        assert_eq!(sample.get(Column::CpuPower), Some(120.5));
        assert_eq!(sample.get(Column::CpuPerf), None);
        assert_eq!(sample.get(Column::GpuTemp), Some(66.0));
        assert_eq!(sample.get(Column::GpuHotspot), Some(78.0));
        assert_eq!(sample.get(Column::GpuLoad), Some(98.0)); // the card, not the iGPU
        assert_eq!(sample.get(Column::GpuClock), Some(1905.0));
        assert_eq!(sample.get(Column::GpuPower), Some(210.0));
        assert_eq!(sample.get(Column::GpuFan), Some(1500.0));
        assert_eq!(sample.get(Column::GpuVramUsed), Some(75.0));
        assert_eq!(sample.get(Column::RamUsed), Some(55.0)); // physical, not virtual
    }

    #[test]
    fn maps_an_amd_cpu_and_falls_back_when_a_named_sensor_is_missing() {
        let amd = vec![
            sensor(
                "/amdcpu/0/temperature/2",
                "Temperature",
                "Core (Tctl/Tdie)",
                88.5,
            ),
            sensor("/amdcpu/0/clock/1", "Clock", "Cores (Average)", 4650.0),
            sensor("/amdcpu/0/clock/3", "Clock", "Core #1", 4700.0),
            sensor("/amdcpu/0/power/0", "Power", "Package", 95.0),
            sensor("/amdcpu/0/load/2", "Load", "CPU Core #1", 60.0),
            sensor("/amdcpu/0/load/3", "Load", "CPU Core #2", 91.0),
            sensor("/gpu-amd/0/load/0", "Load", "GPU Core", 77.0),
            sensor("/gpu-amd/0/load/1", "Load", "GPU Memory", 64.0),
        ];
        let sample = map_sample(&amd, None);
        assert_eq!(sample.get(Column::CpuTemp), Some(88.5));
        assert_eq!(sample.get(Column::CpuClock), Some(4650.0));
        assert_eq!(sample.get(Column::CpuPower), Some(95.0));
        assert_eq!(sample.get(Column::CpuCoreMaxLoad), Some(91.0)); // the busiest core
        assert_eq!(sample.get(Column::CpuLoad), None);
        assert_eq!(sample.get(Column::GpuLoad), Some(77.0));
        assert_eq!(sample.get(Column::GpuVramUsed), Some(64.0)); // no used/total
    }

    #[test]
    fn unknown_cpu_temperature_names_use_the_hottest_but_not_distance() {
        let sensors = vec![
            sensor("/intelcpu/0/temperature/0", "Temperature", "Core #1", 60.0),
            sensor("/intelcpu/0/temperature/1", "Temperature", "Core #2", 64.0),
            sensor(
                "/intelcpu/0/temperature/2",
                "Temperature",
                "Core #1 Distance to TjMax",
                90.0,
            ),
            sensor("/intelcpu/0/clock/1", "Clock", "Core #1", 4000.0),
            sensor("/intelcpu/0/clock/2", "Clock", "Core #2", 3000.0),
        ];
        let sample = map_sample(&sensors, None);
        assert_eq!(sample.get(Column::CpuTemp), Some(64.0));
        assert_eq!(sample.get(Column::CpuClock), Some(3500.0));
    }

    #[test]
    fn prefers_a_graphics_card_and_keeps_to_the_chosen_one() {
        let sensors = intel_nvidia();
        assert_eq!(
            select_gpu_prefix(&sensors).as_deref(),
            Some("/gpu-nvidia/0")
        );
        let sample = map_sample(&sensors, Some("/gpu-intel-integrated/0"));
        assert_eq!(sample.get(Column::GpuLoad), Some(3.0));
        assert_eq!(
            select_gpu_prefix(&[sensor("/ram/load/0", "Load", "Memory", 1.0)]),
            None
        );
    }

    #[test]
    fn no_sensors_gives_an_empty_sample() {
        assert!(map_sample(&[], None).is_empty());
    }

    #[test]
    fn maps_the_fixture_data_json_files() {
        let dir = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/fixtures");
        let intel = LhmSource::File(format!("{dir}/lhm_intel_nvidia.json").into())
            .read()
            .unwrap();
        let sample = map_sample(&intel, None);
        assert_eq!(sample.get(Column::CpuTemp), Some(72.5));
        assert_eq!(sample.get(Column::GpuLoad), Some(97.0));
        assert_eq!(sample.get(Column::GpuVramUsed), Some(62.5));
        assert_eq!(sample.get(Column::RamUsed), Some(48.25));

        let amd = std::fs::read_to_string(format!("{dir}/lhm_amd.json")).unwrap();
        let sample = map_sample(&flatten(&serde_json::from_str(&amd).unwrap()), None);
        assert_eq!(sample.get(Column::CpuTemp), Some(81.0));
        assert_eq!(sample.get(Column::CpuCoreMaxLoad), Some(93.0));
        assert_eq!(sample.get(Column::GpuHotspot), Some(88.0));
    }

    #[test]
    fn rows_use_the_fixed_column_order_and_a_dot() {
        let mut sample = Sample::default();
        sample.set(Column::CpuTemp, Some(71.456));
        sample.set(Column::RamUsed, Some(55.0));
        // The PowerShell collector's Pester test expects exactly this line.
        assert_eq!(format_row(2.5, &sample), "2.50,71.46,,,,,,,,,,,,,55");
        assert_eq!(header().split(',').count(), 15);
        assert!(header().starts_with("elapsed_s,cpu_temp_c,cpu_load_pct,"));
        assert!(header().ends_with(",gpu_vram_used_pct,ram_used_pct"));
    }

    #[test]
    fn formats_numbers_like_powershell() {
        assert_eq!(format_number(55.0), "55");
        assert_eq!(format_number(0.5), "0.5");
        assert_eq!(format_number(4500.004), "4500");
        assert_eq!(format_number(-0.001), "0");
        assert_eq!(format_number(1905.25), "1905.25");
    }

    #[test]
    fn nan_is_no_reading() {
        let mut sample = Sample::default();
        sample.set(Column::GpuFan, Some(f64::NAN));
        assert!(sample.is_empty());
    }
}
