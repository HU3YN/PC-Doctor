//! Sensor readings Windows gives without LibreHardwareMonitor: CPU load,
//! busiest core, CPU speed, RAM use and GPU load. No temperatures - Windows
//! has no reliable source for them, which is why LibreHardwareMonitor is
//! recommended. This is the fallback the PowerShell collector has too
//! (`Get-PCDoctorWindowsSample`), with the same columns.
//!
//! The counters are read with PDH (the Performance Data Helper API) under
//! their English names (`PdhAddEnglishCounterW`), so they work on a Windows
//! in any language. The PowerShell collector reaches the same numbers
//! through CIM classes for the same reason.
//!
//! The arithmetic is in plain functions that are tested on any OS; only
//! `WindowsSensors` itself is Windows-only.
//!
//! With an NVIDIA card, `nvidia-smi` adds its temperature, load, power and
//! video memory, as in the PowerShell collector - only System32's copy, and
//! only when it carries NVIDIA's signature (see nvidia.rs).

use std::collections::BTreeMap;

use crate::sensors::{Column, Sample};

/// The PDH counters read, by their English names.
pub const CPU_UTILITY_ALL: &str = r"\Processor Information(*)\% Processor Utility";
pub const CPU_PERFORMANCE: &str = r"\Processor Information(_Total)\% Processor Performance";
pub const CPU_FREQUENCY: &str = r"\Processor Information(_Total)\Processor Frequency";
pub const GPU_3D_ENGINES: &str = r"\GPU Engine(*engtype_3D)\Utilization Percentage";

/// From `\Processor Information(*)\% Processor Utility`: the total load and
/// the busiest single core. Instance names are `_Total`, `0,_Total` (one per
/// processor group) and `0,3` (group 0, core 3). Utility can pass 100 when a
/// core runs above its base speed, so it is capped as Task Manager does.
pub fn cpu_loads(items: &[(String, f64)]) -> (Option<f64>, Option<f64>) {
    let mut total = None;
    let mut busiest: Option<f64> = None;
    for (name, value) in items {
        if !value.is_finite() {
            continue;
        }
        let load = value.clamp(0.0, 100.0);
        if name == "_Total" {
            total = Some(load);
        } else if !name.ends_with("_Total") {
            busiest = Some(busiest.map_or(load, |b| b.max(load)));
        }
    }
    (total, busiest)
}

/// The CPU's actual speed: its rated frequency times its performance share.
pub fn cpu_clock_mhz(frequency_mhz: Option<f64>, performance_pct: Option<f64>) -> Option<f64> {
    match (frequency_mhz, performance_pct) {
        (Some(f), Some(p)) if f > 0.0 && p > 0.0 && f.is_finite() && p.is_finite() => {
            Some(f * p / 100.0)
        }
        _ => None,
    }
}

/// Task Manager's GPU figure: per adapter, the 3D engines' utilisation summed
/// over every process; then the busiest adapter. Instance names look like
/// `pid_1234_luid_0x00000000_0x0000C2E1_phys_0_eng_0_engtype_3D`.
pub fn busiest_gpu(items: &[(String, f64)]) -> Option<f64> {
    let mut by_adapter: BTreeMap<String, f64> = BTreeMap::new();
    for (name, value) in items {
        if !value.is_finite() || *value < 0.0 {
            continue;
        }
        let adapter = adapter_of(name).unwrap_or("gpu").to_string();
        *by_adapter.entry(adapter).or_insert(0.0) += value;
    }
    by_adapter
        .values()
        .copied()
        .reduce(f64::max)
        .map(|load| load.min(100.0))
}

fn adapter_of(name: &str) -> Option<&str> {
    let start = name.find("luid_")? + "luid_".len();
    let rest = &name[start..];
    // "0x00000000_0x0000C2E1": two hex numbers joined by "_".
    let end = rest
        .match_indices('_')
        .nth(1)
        .map_or(rest.len(), |(index, _)| index);
    Some(&rest[..end])
}

/// RAM in use, from total and available bytes.
pub fn ram_used_pct(total: u64, available: u64) -> Option<f64> {
    (total > 0 && available <= total).then(|| 100.0 * (1.0 - available as f64 / total as f64))
}

/// One sample from the parts above.
pub fn sample_from(
    cpu_utility: &[(String, f64)],
    performance_pct: Option<f64>,
    frequency_mhz: Option<f64>,
    gpu_engines: &[(String, f64)],
    memory: Option<(u64, u64)>,
) -> Sample {
    let mut sample = Sample::default();
    let (total, busiest) = cpu_loads(cpu_utility);
    sample.set(Column::CpuLoad, total);
    sample.set(Column::CpuCoreMaxLoad, busiest);
    sample.set(Column::CpuPerf, performance_pct.filter(|p| *p > 0.0));
    sample.set(
        Column::CpuClock,
        cpu_clock_mhz(frequency_mhz, performance_pct),
    );
    sample.set(Column::GpuLoad, busiest_gpu(gpu_engines));
    sample.set(
        Column::RamUsed,
        memory.and_then(|(total, available)| ram_used_pct(total, available)),
    );
    sample
}

#[cfg(windows)]
pub use windows_impl::WindowsSensors;

/// On other systems there are no Windows counters: `open` says so, and the
/// capture carries on without them. (It keeps the capture loop free of
/// per-OS branches.)
#[cfg(not(windows))]
pub struct WindowsSensors;

#[cfg(not(windows))]
impl WindowsSensors {
    pub fn open() -> Result<Self, String> {
        Err("Windows' counters exist only on Windows".into())
    }

    pub fn read(&self) -> Sample {
        Sample::default()
    }

    pub fn has_nvidia_smi(&self) -> bool {
        false
    }
}

#[cfg(windows)]
mod windows_impl {
    use super::*;
    use windows_sys::Win32::System::Performance::{
        PdhAddEnglishCounterW, PdhCloseQuery, PdhCollectQueryData, PdhGetFormattedCounterArrayW,
        PdhGetFormattedCounterValue, PdhOpenQueryW, PDH_FMT_COUNTERVALUE,
        PDH_FMT_COUNTERVALUE_ITEM_W, PDH_FMT_DOUBLE, PDH_MORE_DATA,
    };
    use windows_sys::Win32::System::SystemInformation::{GlobalMemoryStatusEx, MEMORYSTATUSEX};

    // PDH handles are plain integers in windows-sys.
    type QueryHandle = isize;
    type CounterHandle = isize;
    /// Do not cap at 100 (pdh.h: PDH_FMT_NOCAP100). "% Processor Utility"
    /// passes 100 above base speed; cpu_loads caps it itself.
    const PDH_FMT_NOCAP100: u32 = 0x0000_8000;
    const FORMAT: u32 = PDH_FMT_DOUBLE | PDH_FMT_NOCAP100;

    fn wide(text: &str) -> Vec<u16> {
        text.encode_utf16().chain(std::iter::once(0)).collect()
    }

    /// An open PDH query. Rate counters ("% Utility") need two collections
    /// to give a value, so the first is made when it opens.
    pub struct WindowsSensors {
        query: QueryHandle,
        nvidia_smi: Option<std::path::PathBuf>,
        cpu_utility: Option<CounterHandle>,
        cpu_performance: Option<CounterHandle>,
        cpu_frequency: Option<CounterHandle>,
        gpu_engines: Option<CounterHandle>,
    }

    impl WindowsSensors {
        pub fn open() -> Result<Self, String> {
            // SAFETY: plain Win32 calls; every handle is checked and closed in Drop.
            unsafe {
                let mut query: QueryHandle = std::mem::zeroed();
                let status = PdhOpenQueryW(std::ptr::null(), 0, &mut query);
                if status != 0 {
                    return Err(format!("PDH could not open a query (0x{status:08X})"));
                }
                let add = |path: &str| -> Option<CounterHandle> {
                    let mut counter: CounterHandle = std::mem::zeroed();
                    let path = wide(path);
                    (PdhAddEnglishCounterW(query, path.as_ptr(), 0, &mut counter) == 0)
                        .then_some(counter)
                };
                let sensors = Self {
                    query,
                    nvidia_smi: crate::nvidia::find(),
                    cpu_utility: add(CPU_UTILITY_ALL),
                    cpu_performance: add(CPU_PERFORMANCE),
                    cpu_frequency: add(CPU_FREQUENCY),
                    // Missing on some PCs (no WDDM 2 driver): then no GPU load.
                    gpu_engines: add(GPU_3D_ENGINES),
                };
                PdhCollectQueryData(query);
                Ok(sensors)
            }
        }

        /// One sample. Missing counters give empty columns, not an error.
        pub fn read(&self) -> Sample {
            // SAFETY: the handles are valid until Drop.
            unsafe {
                PdhCollectQueryData(self.query);
            }
            let mut sample = sample_from(
                &self.cpu_utility.map(array).unwrap_or_default(),
                self.cpu_performance.and_then(single),
                self.cpu_frequency.and_then(single),
                &self.gpu_engines.map(array).unwrap_or_default(),
                memory(),
            );
            if let Some(nvidia_smi) = &self.nvidia_smi {
                let card = crate::nvidia::read(nvidia_smi);
                for column in [Column::GpuTemp, Column::GpuPower, Column::GpuVramUsed] {
                    sample.set(column, card.get(column));
                }
                // nvidia-smi's own load figure, when it gives one.
                if card.get(Column::GpuLoad).is_some() {
                    sample.set(Column::GpuLoad, card.get(Column::GpuLoad));
                }
            }
            sample
        }

        /// True when nvidia-smi was found and passed the signature check.
        pub fn has_nvidia_smi(&self) -> bool {
            self.nvidia_smi.is_some()
        }
    }

    impl Drop for WindowsSensors {
        fn drop(&mut self) {
            // SAFETY: the query was opened in `open` and is closed once.
            unsafe {
                PdhCloseQuery(self.query);
            }
        }
    }

    fn single(counter: CounterHandle) -> Option<f64> {
        // SAFETY: `value` is a plain struct PDH fills in; `doubleValue` is the
        // member PDH_FMT_DOUBLE asks for.
        unsafe {
            let mut value: PDH_FMT_COUNTERVALUE = std::mem::zeroed();
            let status =
                PdhGetFormattedCounterValue(counter, FORMAT, std::ptr::null_mut(), &mut value);
            (status == 0 && value.CStatus == 0).then_some(value.Anonymous.doubleValue)
        }
    }

    fn array(counter: CounterHandle) -> Vec<(String, f64)> {
        // SAFETY: the first call asks for the buffer size; the buffer is u64
        // words (aligned for the items) of at least that many bytes, and the
        // names it holds are read before it is dropped.
        unsafe {
            let mut bytes = 0u32;
            let mut count = 0u32;
            let status = PdhGetFormattedCounterArrayW(
                counter,
                FORMAT,
                &mut bytes,
                &mut count,
                std::ptr::null_mut(),
            );
            if status != PDH_MORE_DATA || bytes == 0 {
                return Vec::new();
            }
            let mut buffer = vec![0u64; (bytes as usize).div_ceil(8)];
            let items = buffer.as_mut_ptr() as *mut PDH_FMT_COUNTERVALUE_ITEM_W;
            if PdhGetFormattedCounterArrayW(counter, FORMAT, &mut bytes, &mut count, items) != 0 {
                return Vec::new();
            }
            (0..count as usize)
                .filter_map(|index| {
                    let item = &*items.add(index);
                    if item.FmtValue.CStatus != 0 || item.szName.is_null() {
                        return None;
                    }
                    let mut length = 0;
                    while *item.szName.add(length) != 0 {
                        length += 1;
                    }
                    let name =
                        String::from_utf16_lossy(std::slice::from_raw_parts(item.szName, length));
                    Some((name, item.FmtValue.Anonymous.doubleValue))
                })
                .collect()
        }
    }

    fn memory() -> Option<(u64, u64)> {
        // SAFETY: dwLength must be set before the call; the struct is plain data.
        unsafe {
            let mut status: MEMORYSTATUSEX = std::mem::zeroed();
            status.dwLength = std::mem::size_of::<MEMORYSTATUSEX>() as u32;
            (GlobalMemoryStatusEx(&mut status) != 0)
                .then_some((status.ullTotalPhys, status.ullAvailPhys))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn items(pairs: &[(&str, f64)]) -> Vec<(String, f64)> {
        pairs.iter().map(|(n, v)| (n.to_string(), *v)).collect()
    }

    #[test]
    fn total_and_busiest_core_ignore_group_totals_and_cap_at_100() {
        let cpu = items(&[
            ("_Total", 41.5),
            ("0,_Total", 41.5),
            ("0,0", 20.0),
            ("0,1", 130.0), // a core above base speed
            ("0,2", f64::NAN),
        ]);
        assert_eq!(cpu_loads(&cpu), (Some(41.5), Some(100.0)));
        assert_eq!(cpu_loads(&[]), (None, None));
    }

    #[test]
    fn clock_is_frequency_times_performance() {
        assert_eq!(cpu_clock_mhz(Some(3600.0), Some(125.0)), Some(4500.0));
        assert_eq!(cpu_clock_mhz(Some(3600.0), None), None);
        assert_eq!(cpu_clock_mhz(Some(0.0), Some(100.0)), None);
    }

    #[test]
    fn gpu_load_is_the_busiest_adapter_summed_over_processes() {
        let engines = items(&[
            (
                "pid_100_luid_0x00000000_0x0000C2E1_phys_0_eng_0_engtype_3D",
                55.0,
            ),
            (
                "pid_200_luid_0x00000000_0x0000C2E1_phys_0_eng_0_engtype_3D",
                30.0,
            ),
            (
                "pid_300_luid_0x00000000_0x0000D111_phys_0_eng_0_engtype_3D",
                12.0,
            ),
        ]);
        assert_eq!(busiest_gpu(&engines), Some(85.0));
        let over = items(&[
            ("pid_1_luid_0x0_0x1_phys_0_eng_0_engtype_3D", 80.0),
            ("pid_2_luid_0x0_0x1_phys_0_eng_0_engtype_3D", 40.0),
        ]);
        assert_eq!(busiest_gpu(&over), Some(100.0));
        assert_eq!(busiest_gpu(&[]), None);
        assert_eq!(adapter_of("pid_9_luid_0xA_0xB_phys_0"), Some("0xA_0xB"));
    }

    #[test]
    fn ram_in_use() {
        assert_eq!(ram_used_pct(16, 4), Some(75.0));
        assert_eq!(ram_used_pct(0, 0), None);
        assert_eq!(ram_used_pct(4, 8), None);
    }

    #[test]
    fn a_sample_fills_only_the_columns_windows_can_give() {
        let sample = sample_from(
            &items(&[("_Total", 50.0), ("0,0", 90.0)]),
            Some(110.0),
            Some(3000.0),
            &items(&[("pid_1_luid_0x0_0x1_phys_0_eng_0_engtype_3D", 97.0)]),
            Some((32, 8)),
        );
        assert_eq!(sample.get(Column::CpuLoad), Some(50.0));
        assert_eq!(sample.get(Column::CpuCoreMaxLoad), Some(90.0));
        assert_eq!(sample.get(Column::CpuPerf), Some(110.0));
        assert_eq!(sample.get(Column::CpuClock), Some(3300.0));
        assert_eq!(sample.get(Column::GpuLoad), Some(97.0));
        assert_eq!(sample.get(Column::RamUsed), Some(75.0));
        assert_eq!(sample.get(Column::CpuTemp), None);
        assert_eq!(sample.get(Column::GpuTemp), None);
    }
}
