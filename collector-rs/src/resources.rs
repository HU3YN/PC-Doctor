//! This process's own CPU time and peak memory.
//!
//! The point of a Rust collector is to cost the PC less than the PowerShell
//! one while a game runs, so it measures itself. Only this process is
//! counted: PresentMon is a separate program that both collectors run the
//! same way, so it is measured separately (see README).

use serde::Serialize;

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ResourceUsage {
    pub cpu_user_seconds: f64,
    pub cpu_kernel_seconds: f64,
    /// User + kernel: the total CPU time this process used so far.
    pub cpu_seconds: f64,
    pub peak_memory_bytes: Option<u64>,
    /// What `peak_memory_bytes` is, because each OS measures it differently.
    pub peak_memory_kind: String,
}

/// Usage of this process up to now, or `None` if the OS would not say.
pub fn current() -> Option<ResourceUsage> {
    imp::current()
}

#[cfg(unix)]
mod imp {
    use super::ResourceUsage;

    pub fn current() -> Option<ResourceUsage> {
        // SAFETY: getrusage only writes into the struct we pass; an all-zero
        // rusage is a valid value to start from.
        let usage = unsafe {
            let mut usage: libc::rusage = std::mem::zeroed();
            if libc::getrusage(libc::RUSAGE_SELF, &mut usage) != 0 {
                return None;
            }
            usage
        };
        let seconds = |t: libc::timeval| t.tv_sec as f64 + t.tv_usec as f64 / 1e6;
        let user = seconds(usage.ru_utime);
        let kernel = seconds(usage.ru_stime);
        // ru_maxrss is in kilobytes on Linux but in bytes on macOS.
        let scale: u64 = if cfg!(target_os = "macos") { 1 } else { 1024 };
        let peak = u64::try_from(usage.ru_maxrss).ok().map(|v| v * scale);
        Some(ResourceUsage {
            cpu_user_seconds: user,
            cpu_kernel_seconds: kernel,
            cpu_seconds: user + kernel,
            peak_memory_bytes: peak,
            peak_memory_kind: "max resident set size (getrusage)".to_string(),
        })
    }
}

#[cfg(windows)]
mod imp {
    use super::ResourceUsage;
    use windows_sys::Win32::Foundation::FILETIME;
    use windows_sys::Win32::System::ProcessStatus::{
        GetProcessMemoryInfo, PROCESS_MEMORY_COUNTERS,
    };
    use windows_sys::Win32::System::Threading::{GetCurrentProcess, GetProcessTimes};

    /// FILETIME counts 100-nanosecond ticks.
    fn seconds(time: FILETIME) -> f64 {
        let ticks = (u64::from(time.dwHighDateTime) << 32) | u64::from(time.dwLowDateTime);
        ticks as f64 / 1e7
    }

    pub fn current() -> Option<ResourceUsage> {
        let empty = FILETIME {
            dwLowDateTime: 0,
            dwHighDateTime: 0,
        };
        let (mut created, mut exited, mut kernel, mut user) = (empty, empty, empty, empty);
        // SAFETY: GetCurrentProcess returns a pseudo-handle that needs no
        // closing; both calls only write into the structs we pass.
        unsafe {
            let process = GetCurrentProcess();
            if GetProcessTimes(process, &mut created, &mut exited, &mut kernel, &mut user) == 0 {
                return None;
            }
            let mut counters: PROCESS_MEMORY_COUNTERS = std::mem::zeroed();
            counters.cb = std::mem::size_of::<PROCESS_MEMORY_COUNTERS>() as u32;
            let peak = if GetProcessMemoryInfo(process, &mut counters, counters.cb) != 0 {
                Some(counters.PeakWorkingSetSize as u64)
            } else {
                None
            };
            let (user, kernel) = (seconds(user), seconds(kernel));
            Some(ResourceUsage {
                cpu_user_seconds: user,
                cpu_kernel_seconds: kernel,
                cpu_seconds: user + kernel,
                peak_memory_bytes: peak,
                peak_memory_kind: "peak working set (GetProcessMemoryInfo)".to_string(),
            })
        }
    }
}

#[cfg(not(any(unix, windows)))]
mod imp {
    pub fn current() -> Option<super::ResourceUsage> {
        None
    }
}

#[cfg(test)]
mod tests {
    #[test]
    fn measures_this_process() {
        // Burn a little CPU so the number cannot be zero by rounding.
        let mut x = 0u64;
        for i in 0..5_000_000u64 {
            x = x.wrapping_add(i * i);
        }
        std::hint::black_box(x);
        let usage = super::current().expect("usage is available on this OS");
        assert!(usage.cpu_seconds > 0.0);
        assert!(
            (usage.cpu_seconds - usage.cpu_user_seconds - usage.cpu_kernel_seconds).abs() < 1e-9
        );
        assert!(usage.peak_memory_bytes.unwrap() > 100_000);
    }
}
