//! NVIDIA card readings from `nvidia-smi`, for when LibreHardwareMonitor is
//! not running: temperature, load, power and video memory - the same as the
//! PowerShell collector's fallback (`Get-PCDoctorWindowsSample`).
//!
//! Only `System32\nvidia-smi.exe` is used (the NVIDIA driver puts it there,
//! and only administrators can change that folder), and only if it carries
//! a valid Authenticode signature from NVIDIA Corporation. The signature is
//! checked by Windows PowerShell's `Get-AuthenticodeSignature`, the same
//! check the PowerShell collector makes: it understands both embedded and
//! catalog signatures, which a hand-written WinVerifyTrust call easily gets
//! wrong. The file's path reaches PowerShell through an environment
//! variable, never inside the command text.

use std::path::{Path, PathBuf};
use std::process::Command;

use crate::sensors::{Column, Sample};

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

/// True when a certificate subject (as `Get-AuthenticodeSignature` prints it)
/// names the publisher as its CN or O. "CN=NVIDIA Corporation, O=NVIDIA
/// Corporation, L=Santa Clara, ..." matches "NVIDIA Corporation"; a subject
/// that merely contains the words elsewhere does not.
pub fn subject_names(subject: &str, publisher: &str) -> bool {
    subject.split(',').map(str::trim).any(|part| {
        part.split_once('=').is_some_and(|(key, value)| {
            matches!(key.trim(), "CN" | "O") && value.trim().trim_matches('"') == publisher
        })
    })
}

/// The signature check's answer: "Valid|<subject>" or something else.
pub fn signature_ok(answer: &str, publisher: &str) -> bool {
    match answer.trim().split_once('|') {
        Some((status, subject)) => status == "Valid" && subject_names(subject, publisher),
        None => false,
    }
}

const CHECK_SCRIPT: &str = "$s = Get-AuthenticodeSignature -LiteralPath $env:PCDOCTOR_CHECK_FILE; \
     $subject = ''; if ($s.SignerCertificate) { $subject = $s.SignerCertificate.Subject }; \
     Write-Output ('{0}|{1}' -f $s.Status, $subject)";

/// Windows PowerShell's answer about `file`: "Valid|<subject>", or the
/// reason it could not answer.
pub fn signature_answer(file: &Path) -> String {
    let Some(root) = std::env::var_os("SystemRoot") else {
        return "no SystemRoot".into();
    };
    let powershell = PathBuf::from(root).join(r"System32\WindowsPowerShell\v1.0\powershell.exe");
    let output = Command::new(powershell)
        .args(["-NoProfile", "-NonInteractive", "-Command", CHECK_SCRIPT])
        .env("PCDOCTOR_CHECK_FILE", file)
        // Started from PowerShell 7, Windows PowerShell would inherit its
        // module path, load 7's security module, fail, and answer nothing.
        // Without it, 5.1 uses its own modules.
        .env_remove("PSModulePath")
        .output();
    match output {
        Ok(output) if !output.stdout.is_empty() => String::from_utf8_lossy(&output.stdout).into(),
        Ok(output) => format!("no answer: {}", String::from_utf8_lossy(&output.stderr)),
        Err(error) => format!("could not start PowerShell: {error}"),
    }
}

/// Ask Windows PowerShell whether `file` has a valid signature from `publisher`.
pub fn signed_by(file: &Path, publisher: &str) -> bool {
    signature_ok(&signature_answer(file), publisher)
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

    #[test]
    fn only_a_valid_signature_from_the_publisher_counts() {
        let nvidia =
            "CN=NVIDIA Corporation, O=NVIDIA Corporation, L=Santa Clara, S=California, C=US";
        assert!(signature_ok(
            &format!("Valid|{nvidia}\r\n"),
            "NVIDIA Corporation"
        ));
        assert!(!signature_ok(
            &format!("HashMismatch|{nvidia}"),
            "NVIDIA Corporation"
        ));
        assert!(!signature_ok("NotSigned|", "NVIDIA Corporation"));
        assert!(!signature_ok(
            "Valid|CN=Not NVIDIA Corporation Ltd",
            "NVIDIA Corporation"
        ));
        assert!(!signature_ok(
            "Valid|CN=Evil, OU=NVIDIA Corporation",
            "NVIDIA Corporation"
        ));
        assert!(!signature_ok("garbage", "NVIDIA Corporation"));
        assert!(subject_names(
            r#"CN="NVIDIA Corporation", C=US"#,
            "NVIDIA Corporation"
        ));
    }

    // The real check, on the Windows CI runner: a catalog-signed system file
    // (notepad.exe is signed through a Windows catalog, as nvidia-smi.exe in
    // System32 may be) passes for its publisher and fails for any other, and
    // an unsigned file fails.
    #[cfg(windows)]
    #[test]
    fn windows_checks_real_signatures() {
        let notepad =
            PathBuf::from(std::env::var_os("SystemRoot").unwrap()).join(r"System32\notepad.exe");
        let answer = signature_answer(&notepad);
        assert!(
            signed_by(&notepad, "Microsoft Corporation"),
            "PowerShell said: {answer:?}"
        );
        assert!(!signed_by(&notepad, "NVIDIA Corporation"));
        let folder = tempfile::tempdir().unwrap();
        let unsigned = folder.path().join("nvidia-smi.exe");
        std::fs::write(&unsigned, b"not a program").unwrap();
        assert!(!signed_by(&unsigned, "NVIDIA Corporation"));
        // A path with a quote and a $ cannot break out of the check.
        let odd = folder.path().join("a'b$c.exe");
        std::fs::write(&odd, b"x").unwrap();
        assert!(!signed_by(&odd, "Microsoft Corporation"));
    }
}
