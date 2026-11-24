//! Is a program signed by the publisher it should be? Asked before this
//! collector runs, as administrator, a program that lives where others could
//! replace it (nvidia-smi, PresentMon).
//!
//! The signature is checked by Windows PowerShell's `Get-AuthenticodeSignature`,
//! the same check the PowerShell collector makes: it understands both embedded
//! and catalog signatures, which a hand-written WinVerifyTrust call easily gets
//! wrong. The file's path reaches PowerShell through an environment variable,
//! never inside the command text.

use std::path::{Path, PathBuf};
use std::process::Command;

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

#[cfg(test)]
mod tests {
    use super::*;

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
