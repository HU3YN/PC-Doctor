//! NVIDIA card readings from `nvidia-smi`, for when LibreHardwareMonitor is
//! not running: temperature, load, power and video memory - the same as the
//! PowerShell collector's fallback (`Get-PCDoctorWindowsSample`).
//!
//! Only `System32\nvidia-smi.exe` is used (the NVIDIA driver puts it there,
//! and only administrators can change that folder), and only if it carries
//! a valid Authenticode signature from NVIDIA Corporation. The signature is
//! checked by Windows PowerShell's `Get-AuthenticodeSignature`, the same
//! check the PowerShell collector makes (see `signature`).

use std::path::{Path, PathBuf};
use std::process::Command;

use crate::sensors::{Column, Sample};
use crate::signature::signed_by;

/// The query asked of nvidia-smi, and the order of the answer's fields.
pub const QUERY: &str =
    "--query-gpu=temperature.gpu,utilization.gpu,power.draw,memory.used,memory.total";

/// Read the first GPU's line of `nvidia-smi --query-gpu=... --format=csv,noheader,nounits`.
/// "[N/A]" or "[Not Supported]" fields stay empty.
pub fn parse_line(output: &str) -> Sample {
    let mut sample = Sample::default();
    let Some(line) = output.lines().map(str::trim).find(|line| !line.is_empty()) else {
        return sample;
    };
    let fields: Vec<Option<f64>> = line
        .split(',')
        .map(|field| field.trim().parse::<f64>().ok().filter(|v| v.is_finite()))
        .collect();
    if fields.len() < 5 {
        return sample;
    }
    sample.set(Column::GpuTemp, fields[0]);
    sample.set(
        Column::GpuLoad,
        fields[1].map(|load| load.clamp(0.0, 100.0)),
    );
    sample.set(Column::GpuPower, fields[2]);
    if let (Some(used), Some(total)) = (fields[3], fields[4]) {
        if total > 0.0 {
            sample.set(Column::GpuVramUsed, Some((100.0 * used / total).min(100.0)));
        }
    }
    sample
}

/// System32\nvidia-smi.exe, if it is there and signed by NVIDIA.
pub fn find() -> Option<PathBuf> {
    let path = PathBuf::from(std::env::var_os("SystemRoot")?).join(r"System32\nvidia-smi.exe");
    (path.is_file() && signed_by(&path, "NVIDIA Corporation")).then_some(path)
}

/// One reading. Any failure is an empty sample: the capture carries on.
pub fn read(nvidia_smi: &Path) -> Sample {
    match Command::new(nvidia_smi)
        .args([QUERY, "--format=csv,noheader,nounits"])
        .output()
    {
        Ok(output) if output.status.success() => {
            parse_line(&String::from_utf8_lossy(&output.stdout))
        }
        _ => Sample::default(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reads_the_first_gpu_line() {
        let sample = parse_line("67, 98, 201.35, 6144, 8192\n55, 3, 20.1, 100, 8192\n");
        assert_eq!(sample.get(Column::GpuTemp), Some(67.0));
        assert_eq!(sample.get(Column::GpuLoad), Some(98.0));
        assert_eq!(sample.get(Column::GpuPower), Some(201.35));
        assert_eq!(sample.get(Column::GpuVramUsed), Some(75.0));
    }

    #[test]
    fn missing_fields_stay_empty() {
        let sample = parse_line("61, 40, [N/A], 512, 0");
        assert_eq!(sample.get(Column::GpuTemp), Some(61.0));
        assert_eq!(sample.get(Column::GpuPower), None);
        assert_eq!(sample.get(Column::GpuVramUsed), None); // total 0
        assert!(parse_line("").is_empty());
        assert!(parse_line("NVIDIA-SMI has failed").is_empty());
    }
}
