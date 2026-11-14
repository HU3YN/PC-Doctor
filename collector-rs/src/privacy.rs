//! Scrubbing free text before it is saved.
//!
//! The label is the only text a person types into a run. The rule
//! (docs/privacy.md) is "the machine, never the customer", and as a second
//! line of defence the same scrub as the PowerShell collector's
//! `Protect-PCDoctorText` is applied: user-folder paths, serial numbers, the
//! computer name and the user name are replaced with placeholders.

use regex::{NoExpand, Regex};
use std::sync::LazyLock;

/// Scrub with this PC's computer name and user name (from the environment).
pub fn scrub(text: &str, max_chars: usize) -> String {
    let computer = std::env::var("COMPUTERNAME")
        .or_else(|_| std::env::var("HOSTNAME"))
        .ok();
    let user = std::env::var("USERNAME")
        .or_else(|_| std::env::var("USER"))
        .ok();
    scrub_with(text, computer.as_deref(), user.as_deref(), max_chars)
}

/// The scrub itself, with the names passed in so it can be tested.
pub fn scrub_with(
    text: &str,
    computer: Option<&str>,
    user: Option<&str>,
    max_chars: usize,
) -> String {
    static USER_FOLDER: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(r#"(?i)([A-Z]:\\Users\\)[^\\\s"]+"#).expect("valid regex"));
    static SERIAL: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(r"(?i)(serial\s*(?:number|no\.?)?\s*[:=]\s*)\S+").expect("valid regex")
    });
    let mut clean = USER_FOLDER.replace_all(text, "${1}<user>").into_owned();
    clean = SERIAL.replace_all(&clean, "${1}<removed>").into_owned();
    // Names shorter than 3 letters would match inside ordinary words.
    if let Some(name) = computer.filter(|n| n.chars().count() >= 3) {
        let pattern = Regex::new(&format!("(?i){}", regex::escape(name))).expect("escaped");
        clean = pattern
            .replace_all(&clean, NoExpand("<computer>"))
            .into_owned();
    }
    if let Some(name) = user.filter(|n| n.chars().count() >= 3) {
        let pattern = Regex::new(&format!(r"(?i)\b{}\b", regex::escape(name))).expect("escaped");
        clean = pattern.replace_all(&clean, NoExpand("<user>")).into_owned();
    }
    clean.trim().chars().take(max_chars).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn removes_user_folders_serials_and_names() {
        let text = r"Dump at C:\Users\Alice\x.dmp, serial number: ABC123 on BENCH-PC by alice";
        let clean = scrub_with(text, Some("bench-pc"), Some("Alice"), 600);
        assert_eq!(
            clean,
            r"Dump at C:\Users\<user>\x.dmp, serial number: <removed> on <computer> by <user>"
        );
    }

    #[test]
    fn leaves_ordinary_labels_alone_and_caps_the_length() {
        assert_eq!(
            scrub_with("  bench 3, GPU swap ", Some("PC"), Some("al"), 200),
            "bench 3, GPU swap"
        );
        assert_eq!(scrub_with(&"x".repeat(500), None, None, 200).len(), 200);
        // A user name inside a longer word is not a match.
        assert_eq!(scrub_with("tomato", None, Some("tom"), 200), "tomato");
    }
}
