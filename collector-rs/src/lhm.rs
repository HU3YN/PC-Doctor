//! LibreHardwareMonitor's `data.json`, flattened into a list of sensors.
//!
//! LibreHardwareMonitor (Options > Remote Web Server > Run) serves its sensor
//! tree at `http://localhost:8085/data.json`. Each node has `Text` and
//! `Children`; sensor nodes also have `SensorId` (e.g.
//! `/intelcpu/0/temperature/8`), `Type`, a formatted `Value` ("45.0 °C") and,
//! in recent versions, `RawValue`. Field names were read from its
//! `HttpServer.cs` (docs/verified-facts.md); the PowerShell collector reads
//! the same fields.

use std::path::PathBuf;
use std::sync::LazyLock;
use std::time::Duration;

use regex::Regex;
use serde::Serialize;
use serde_json::Value;

/// One sensor reading. Serialized with the same field names the PowerShell
/// collector uses in `sensors_raw.json`.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Sensor {
    #[serde(rename = "SensorId")]
    pub id: String,
    #[serde(rename = "Type")]
    pub kind: String,
    #[serde(rename = "Text")]
    pub text: String,
    #[serde(rename = "Value")]
    pub value: Option<f64>,
}

/// Every sensor node of the tree, in document order (parents before
/// children, siblings in the order they appear).
///
/// Only sensor nodes are returned. Hardware nodes (which carry model names)
/// are walked through but not kept.
pub fn flatten(tree: &Value) -> Vec<Sensor> {
    let mut out = Vec::new();
    // An explicit stack instead of recursion: a deeply nested (damaged or
    // hostile) file cannot overflow the call stack.
    let mut stack = vec![tree];
    while let Some(node) = stack.pop() {
        let Some(object) = node.as_object() else {
            continue;
        };
        if let Some(id) = object.get("SensorId").and_then(Value::as_str) {
            if !id.is_empty() {
                // RawValue is the plain number. Older versions lack it, and a
                // value that does not parse falls back to the formatted one.
                let value = object
                    .get("RawValue")
                    .and_then(number_from_json)
                    .or_else(|| object.get("Value").and_then(number_from_json));
                out.push(Sensor {
                    id: id.to_string(),
                    kind: text_field(object.get("Type")),
                    text: text_field(object.get("Text")),
                    value,
                });
            }
        }
        if let Some(children) = object.get("Children").and_then(Value::as_array) {
            // Pushed in reverse so they are popped in document order.
            stack.extend(children.iter().rev());
        }
    }
    out
}

fn text_field(value: Option<&Value>) -> String {
    value
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string()
}

/// A JSON number, or a string like "45.0 °C", "7,5 GB" -> a number.
fn number_from_json(value: &Value) -> Option<f64> {
    match value {
        Value::Number(n) => n.as_f64().filter(|x| x.is_finite()),
        Value::String(s) => parse_number(s),
        _ => None,
    }
}

/// "45.0 °C", "7,5 GB", "1500 RPM" -> 45.0, 7680.0, 1500.0.
///
/// The same rule as the PowerShell collector's `ConvertTo-PCDoctorNumber`:
/// the first number in the text, a comma accepted as the decimal mark, and
/// data sizes converted to megabytes so two of them can be compared.
pub fn parse_number(text: &str) -> Option<f64> {
    static NUMBER: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(r"(-?\d+(?:[.,]\d+)?)\s*([KMGT]B)?").expect("valid regex"));
    let captures = NUMBER.captures(text.trim())?;
    let number: f64 = captures[1].replace(',', ".").parse().ok()?;
    let megabytes = match captures.get(2).map(|m| m.as_str()) {
        Some("KB") => number / 1024.0,
        Some("GB") => number * 1024.0,
        Some("TB") => number * 1024.0 * 1024.0,
        _ => number,
    };
    Some(megabytes).filter(|x| x.is_finite())
}

/// Where readings come from: the web server, or a saved `data.json` (tests).
#[derive(Debug, Clone)]
pub enum LhmSource {
    Http { url: String, agent: ureq::Agent },
    File(PathBuf),
}

impl LhmSource {
    /// `http://localhost:8085` and `http://localhost:8085/data.json` both work.
    pub fn http(url: &str, timeout: Duration) -> Self {
        let mut url = url.trim().trim_end_matches('/').to_string();
        if !url.ends_with(".json") {
            url.push_str("/data.json");
        }
        let agent = ureq::AgentBuilder::new().timeout(timeout).build();
        LhmSource::Http { url, agent }
    }

    /// Read the sensors once. An error is a short reason for the log, never
    /// a crash: one missed sample just leaves an empty row.
    pub fn read(&self) -> Result<Vec<Sensor>, String> {
        let text = match self {
            LhmSource::Http { url, agent } => agent
                .get(url)
                .call()
                .map_err(|e| format!("LibreHardwareMonitor did not answer ({})", short_error(&e)))?
                .into_string()
                .map_err(|e| format!("LibreHardwareMonitor's answer could not be read ({e})"))?,
            LhmSource::File(path) => std::fs::read_to_string(path)
                .map_err(|e| format!("the sensor file could not be read ({})", e.kind()))?,
        };
        let tree: Value = serde_json::from_str(&text)
            .map_err(|e| format!("data.json is not valid JSON ({e})"))?;
        let sensors = flatten(&tree);
        if sensors.is_empty() {
            return Err("data.json has no sensors".to_string());
        }
        Ok(sensors)
    }
}

/// ureq's error text includes the URL; keep only the kind of failure so the
/// log stays short (the URL is localhost anyway).
fn short_error(error: &ureq::Error) -> String {
    match error {
        ureq::Error::Status(code, _) => format!("HTTP {code}"),
        ureq::Error::Transport(transport) => format!("{:?}", transport.kind()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn parses_formatted_values() {
        assert_eq!(parse_number("45.0 °C"), Some(45.0));
        assert_eq!(parse_number("45,5 %"), Some(45.5));
        assert_eq!(parse_number("7,5 GB"), Some(7680.0));
        assert_eq!(parse_number("512 KB"), Some(0.5));
        assert_eq!(parse_number("-3.5 W"), Some(-3.5));
        assert_eq!(parse_number("[N/A]"), None);
        assert_eq!(parse_number(""), None);
    }

    #[test]
    fn flattens_the_tree_using_raw_value_then_value() {
        let tree = json!({
            "Text": "Sensor", "Children": [{
                "Text": "PC", "Children": [{
                    "Text": "Some CPU model", "HardwareId": "/intelcpu/0", "Children": [
                        {"Text": "CPU Package", "SensorId": "/intelcpu/0/temperature/8",
                         "Type": "Temperature", "Value": "70,0 °C", "RawValue": 71.5, "Children": []},
                        {"Text": "CPU Total", "SensorId": "/intelcpu/0/load/0",
                         "Type": "Load", "Value": "42,5 %", "Children": []},
                        {"Text": "Broken", "SensorId": "/intelcpu/0/load/9",
                         "Type": "Load", "Value": "-", "RawValue": "n/a", "Children": []}
                    ]
                }]
            }]
        });
        let sensors = flatten(&tree);
        assert_eq!(sensors.len(), 3);
        assert_eq!(sensors[0].text, "CPU Package");
        assert_eq!(sensors[0].value, Some(71.5));
        assert_eq!(sensors[1].value, Some(42.5));
        assert_eq!(sensors[2].value, None);
        // Hardware names are not sensors and are not kept.
        assert!(sensors.iter().all(|s| !s.text.contains("model")));
    }

    #[test]
    fn raw_value_as_a_string_is_accepted() {
        let tree = json!({"SensorId": "/ram/load/0", "Type": "Load", "Text": "Memory",
                          "RawValue": "55.25", "Value": "55.3 %"});
        assert_eq!(flatten(&tree)[0].value, Some(55.25));
    }

    #[test]
    fn survives_a_very_deep_tree() {
        let mut tree =
            json!({"SensorId": "/ram/load/0", "Type": "Load", "Text": "Memory", "RawValue": 1});
        for _ in 0..200 {
            tree = json!({"Text": "x", "Children": [tree]});
        }
        // serde_json refuses to *parse* past depth 128, so a real file stays
        // shallow; deeper than that, the walk must still work. (Not much
        // deeper here: dropping a deep Value recurses inside serde_json.)
        assert_eq!(flatten(&tree).len(), 1);
    }

    #[test]
    fn reads_a_saved_data_json() {
        let path = concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/tests/fixtures/lhm_intel_nvidia.json"
        );
        let sensors = LhmSource::File(path.into()).read().unwrap();
        assert!(sensors.iter().any(|s| s.id == "/intelcpu/0/temperature/8"));
    }

    #[test]
    fn a_missing_file_is_an_error_not_a_panic() {
        let error = LhmSource::File("/nonexistent/data.json".into())
            .read()
            .unwrap_err();
        assert!(error.contains("could not be read"));
        assert!(
            !error.contains("nonexistent"),
            "no file paths in messages: {error}"
        );
    }

    /// A one-request HTTP server on localhost, answering with `body`.
    fn serve_once(body: String) -> String {
        use std::io::{Read, Write};
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut request = [0u8; 1024];
            let _ = stream.read(&mut request);
            let answer = format!(
                "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                body.len()
            );
            stream.write_all(answer.as_bytes()).unwrap();
        });
        format!("http://{address}")
    }

    #[test]
    fn reads_from_the_web_server() {
        let path = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/fixtures/lhm_amd.json");
        let url = serve_once(std::fs::read_to_string(path).unwrap());
        let sensors = LhmSource::http(&url, Duration::from_secs(5))
            .read()
            .unwrap();
        assert!(sensors.iter().any(|s| s.id.starts_with("/amdcpu/0/")));
    }

    #[test]
    fn a_server_that_is_not_running_is_an_error() {
        // Take a free port, then close it again.
        let port = std::net::TcpListener::bind("127.0.0.1:0")
            .unwrap()
            .local_addr()
            .unwrap()
            .port();
        let source = LhmSource::http(&format!("http://127.0.0.1:{port}"), Duration::from_secs(2));
        let error = source.read().unwrap_err();
        assert!(
            error.starts_with("LibreHardwareMonitor did not answer"),
            "{error}"
        );
    }

    #[test]
    fn http_url_gets_data_json_appended_once() {
        for url in [
            "http://localhost:8085",
            "http://localhost:8085/",
            "http://localhost:8085/data.json",
        ] {
            match LhmSource::http(url, Duration::from_secs(1)) {
                LhmSource::Http { url, .. } => assert_eq!(url, "http://localhost:8085/data.json"),
                LhmSource::File(_) => unreachable!(),
            }
        }
    }
}
