//! Live streaming: send frame times and sensor readings to PC Doctor while
//! the capture runs, so the master's Live page can show them.
//!
//! About once a second, everything new is POSTed to the session's samples
//! address as NDJSON, one JSON object per line:
//!
//! ```text
//! {"type":"frame","t":12.34,"ms":7.1}
//! {"type":"sensor","t":12.0,"values":{"cpu_temp_c":71.5}}
//! {"type":"end"}
//! ```
//!
//! Streaming is best effort. The run on disk is the record: if the server
//! cannot be reached, lines wait (up to a limit) and the capture carries on.
//! Only frame times and sensor values are sent - never program names, paths
//! or anything else from the PC.

use std::net::IpAddr;
use std::time::{Duration, Instant};

use crate::sensors::{Column, Sample};

/// How often a batch goes out.
pub const SEND_EVERY: Duration = Duration::from_secs(1);
/// Lines kept while the server cannot be reached; the oldest go first.
const MAX_PENDING: usize = 20_000;
/// The server takes at most 5000 lines in one batch.
const MAX_BATCH_LINES: usize = 4_000;

/// Refuse a samples address that would send data in the clear across the
/// internet. Plain HTTP is allowed only to this PC or a private network.
pub fn check_url(url: &str) -> Result<(), String> {
    let lower = url.trim().to_ascii_lowercase();
    if lower.starts_with("https://") {
        return Ok(());
    }
    let Some(rest) = lower.strip_prefix("http://") else {
        return Err(
            "the live address must start with https:// (or http:// on your own network)".into(),
        );
    };
    let authority = rest.split('/').next().unwrap_or("");
    let host = if let Some(bracketed) = authority.strip_prefix('[') {
        bracketed.split(']').next().unwrap_or("") // [::1]:8080
    } else {
        authority
            .rsplit_once(':')
            .map_or(authority, |(host, _port)| host)
    };
    if is_local_host(host) {
        Ok(())
    } else {
        Err(format!(
            "plain http:// is only allowed to this PC or a private network address, not \"{host}\": use https://"
        ))
    }
}

fn is_local_host(host: &str) -> bool {
    if host == "localhost" {
        return true;
    }
    match host.parse::<IpAddr>() {
        Ok(IpAddr::V4(ip)) => ip.is_loopback() || ip.is_private() || ip.is_link_local(),
        Ok(IpAddr::V6(ip)) => {
            // ::1, or a unique local address (fc00::/7).
            ip.is_loopback() || (ip.segments()[0] & 0xfe00) == 0xfc00
        }
        Err(_) => false,
    }
}

/// Reads frame times out of the target's PresentMon rows.
#[derive(Debug, Default)]
pub struct FrameTimes {
    time_index: Option<usize>,
    ms_index: Option<usize>,
    /// Without a TimeInSeconds column, time is the running sum of frame times.
    running_seconds: f64,
}

impl FrameTimes {
    pub fn from_header(header: &str) -> Self {
        let columns: Vec<&str> = header
            .trim_start_matches('\u{feff}')
            .split(',')
            .map(str::trim)
            .collect();
        let find = |names: &[&str]| {
            names
                .iter()
                .find_map(|name| columns.iter().position(|c| c.eq_ignore_ascii_case(name)))
        };
        Self {
            time_index: find(&["TimeInSeconds"]),
            ms_index: find(&["MsBetweenPresents", "FrameTime"]),
            running_seconds: 0.0,
        }
    }

    /// `(seconds, frame time in ms)` for one kept row, if it has a usable one.
    pub fn read(&mut self, row: &str) -> Option<(f64, f64)> {
        let fields: Vec<&str> = row.split(',').collect();
        let ms: f64 = fields.get(self.ms_index?)?.trim().parse().ok()?;
        if !ms.is_finite() || ms <= 0.0 || ms > 3_600_000.0 {
            return None;
        }
        self.running_seconds += ms / 1000.0;
        let seconds = match self.time_index {
            Some(index) => fields.get(index)?.trim().parse().ok()?,
            None => self.running_seconds,
        };
        (0.0..86_400.0).contains(&seconds).then_some((seconds, ms))
    }
}

/// One line of the batch format.
fn frame_line(seconds: f64, ms: f64) -> String {
    format!(r#"{{"type":"frame","t":{seconds:.4},"ms":{ms:.4}}}"#)
}

fn sensor_line(seconds: f64, sample: &Sample) -> Option<String> {
    let values: Vec<String> = Column::ALL
        .iter()
        .filter_map(|column| {
            sample
                .get(*column)
                .map(|value| format!(r#""{}":{value:.2}"#, column.name()))
        })
        .collect();
    if values.is_empty() {
        return None;
    }
    Some(format!(
        r#"{{"type":"sensor","t":{seconds:.2},"values":{{{}}}}}"#,
        values.join(",")
    ))
}

/// What happened to one attempt to send.
#[derive(Debug, PartialEq, Eq)]
pub enum Sent {
    Nothing,
    Lines(usize),
    /// The server is unreachable or busy; the lines wait for the next try.
    Later(String),
    /// The session is gone (closed, expired, or a wrong address): stop.
    Stopped(String),
}

pub struct LiveSender {
    url: String,
    agent: ureq::Agent,
    pending: Vec<String>,
    last_attempt: Option<Instant>,
    stopped: bool,
    pub lines_sent: u64,
    pub lines_dropped: u64,
    pub failures: u64,
}

impl LiveSender {
    pub fn new(url: &str) -> Result<Self, String> {
        check_url(url)?;
        let agent = ureq::AgentBuilder::new()
            .timeout(Duration::from_secs(3))
            .redirects(0) // a redirect could carry the samples somewhere else
            .build();
        Ok(Self {
            url: url.trim().to_string(),
            agent,
            pending: Vec::new(),
            last_attempt: None,
            stopped: false,
            lines_sent: 0,
            lines_dropped: 0,
            failures: 0,
        })
    }

    pub fn is_stopped(&self) -> bool {
        self.stopped
    }

    fn push(&mut self, line: String) {
        if self.stopped {
            return;
        }
        if self.pending.len() >= MAX_PENDING {
            self.pending.remove(0);
            self.lines_dropped += 1;
        }
        self.pending.push(line);
    }

    pub fn frame(&mut self, seconds: f64, ms: f64) {
        self.push(frame_line(seconds, ms));
    }

    pub fn sensors(&mut self, seconds: f64, sample: &Sample) {
        if let Some(line) = sensor_line(seconds, sample) {
            self.push(line);
        }
    }

    /// Send what is waiting, if a second has passed since the last try.
    pub fn tick(&mut self, now: Instant) -> Sent {
        let due = self
            .last_attempt
            .map_or(true, |last| now.duration_since(last) >= SEND_EVERY);
        if !due || self.pending.is_empty() || self.stopped {
            return Sent::Nothing;
        }
        self.last_attempt = Some(now);
        self.send_some()
    }

    /// Mark the end and send everything left (a few tries at most).
    pub fn finish(&mut self) -> Sent {
        self.push(r#"{"type":"end"}"#.to_string());
        let mut last = Sent::Nothing;
        for _ in 0..(self.pending.len() / MAX_BATCH_LINES + 3) {
            if self.pending.is_empty() || self.stopped {
                break;
            }
            last = self.send_some();
            if matches!(last, Sent::Later(_)) {
                std::thread::sleep(Duration::from_millis(500));
            }
        }
        last
    }

    fn send_some(&mut self) -> Sent {
        let count = self.pending.len().min(MAX_BATCH_LINES);
        let body = self.pending[..count].join("\n");
        let answer = self
            .agent
            .post(&self.url)
            .set("Content-Type", "application/x-ndjson")
            .send_string(&body);
        match answer {
            Ok(_) => {
                self.pending.drain(..count);
                self.lines_sent += count as u64;
                Sent::Lines(count)
            }
            Err(ureq::Error::Status(code @ (404 | 401 | 403), _)) => {
                self.stopped = true;
                self.lines_dropped += self.pending.len() as u64;
                self.pending.clear();
                Sent::Stopped(format!(
                    "the live session answered HTTP {code}: it has ended or the address is wrong"
                ))
            }
            Err(ureq::Error::Status(400, _)) => {
                // The server could not use this batch at all; do not resend it.
                self.pending.drain(..count);
                self.lines_dropped += count as u64;
                self.failures += 1;
                Sent::Later("the server refused one batch".into())
            }
            Err(ureq::Error::Status(code, _)) => {
                self.failures += 1;
                Sent::Later(format!("HTTP {code}"))
            }
            Err(ureq::Error::Transport(transport)) => {
                self.failures += 1;
                Sent::Later(format!("{:?}", transport.kind()))
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{BufRead, BufReader, Read, Write};
    use std::net::TcpListener;
    use std::sync::mpsc;

    #[test]
    fn https_anywhere_http_only_nearby() {
        for ok in [
            "https://pcdoctor.example.com/api/live/k/samples",
            "http://localhost:8080/api/live/k/samples",
            "http://127.0.0.1:8080/x",
            "http://192.168.1.20:8080/x",
            "http://10.0.0.5/x",
            "http://172.16.4.2/x",
            "http://[::1]:8080/x",
            "HTTP://LOCALHOST/x",
        ] {
            assert!(check_url(ok).is_ok(), "{ok}");
        }
        for bad in [
            "http://pcdoctor.example.com/x",
            "http://8.8.8.8/x",
            "http://172.32.0.1/x",
            "ftp://localhost/x",
            "localhost:8080/x",
            "http://localhost.evil.example/x",
        ] {
            assert!(check_url(bad).is_err(), "{bad}");
        }
    }

    #[test]
    fn frame_times_from_each_header_style() {
        let mut v2 = FrameTimes::from_header(
            "Application,ProcessID,TimeInSeconds,MsBetweenPresents,MsBetweenDisplayChange",
        );
        assert_eq!(v2.read("Game.exe,1,12.5,7.25,7.0"), Some((12.5, 7.25)));
        let mut v1 = FrameTimes::from_header("Application,TimeInSeconds,msBetweenPresents");
        assert_eq!(v1.read("Game.exe,3.0,16.6"), Some((3.0, 16.6)));
        // --v2_metrics has no TimeInSeconds: time is the running sum.
        let mut metrics = FrameTimes::from_header("\u{feff}Application,CPUStartTime,FrameTime");
        assert_eq!(metrics.read("Game.exe,100,10"), Some((0.01, 10.0)));
        assert_eq!(metrics.read("Game.exe,110,20"), Some((0.03, 20.0)));
    }

    #[test]
    fn unusable_rows_are_skipped() {
        let mut times = FrameTimes::from_header("Application,TimeInSeconds,MsBetweenPresents");
        for row in [
            "Game.exe,1.0,NA",
            "Game.exe,1.0,-3",
            "Game.exe,1.0,0",
            "Game.exe,1.0,inf",
            "Game.exe,1.0",
            "Game.exe,x,5",
        ] {
            assert_eq!(times.read(row), None, "{row}");
        }
        let mut unknown = FrameTimes::from_header("Application,Something");
        assert_eq!(unknown.read("Game.exe,5"), None);
    }

    #[test]
    fn sensor_lines_hold_only_readings() {
        let mut sample = Sample::default();
        assert_eq!(sensor_line(1.0, &sample), None);
        sample.set(Column::CpuTemp, Some(71.456));
        sample.set(Column::GpuLoad, Some(98.0));
        let line = sensor_line(2.5, &sample).unwrap();
        let parsed: serde_json::Value = serde_json::from_str(&line).unwrap();
        assert_eq!(parsed["type"], "sensor");
        assert_eq!(parsed["t"], 2.5);
        assert_eq!(parsed["values"]["cpu_temp_c"], 71.46);
        assert_eq!(parsed["values"]["gpu_load_pct"], 98.0);
        assert_eq!(parsed["values"].as_object().unwrap().len(), 2);
    }

    /// A one-shot HTTP server that answers each request with the next status
    /// and hands the request bodies to the test.
    fn server(statuses: Vec<u16>) -> (String, mpsc::Receiver<String>) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let url = format!(
            "http://{}/api/live/token/samples",
            listener.local_addr().unwrap()
        );
        let (tx, rx) = mpsc::channel();
        std::thread::spawn(move || {
            for status in statuses {
                let (stream, _) = listener.accept().unwrap();
                let mut reader = BufReader::new(stream);
                let mut length = 0usize;
                loop {
                    let mut line = String::new();
                    reader.read_line(&mut line).unwrap();
                    if line.trim().is_empty() {
                        break;
                    }
                    if let Some(value) = line.to_ascii_lowercase().strip_prefix("content-length:") {
                        length = value.trim().parse().unwrap();
                    }
                }
                let mut body = vec![0; length];
                reader.read_exact(&mut body).unwrap();
                tx.send(String::from_utf8(body).unwrap()).unwrap();
                let mut stream = reader.into_inner();
                let answer = format!(
                    "HTTP/1.1 {status} X\r\nContent-Type: application/json\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{{}}"
                );
                stream.write_all(answer.as_bytes()).unwrap();
            }
        });
        (url, rx)
    }

    #[test]
    fn sends_batches_about_once_a_second_and_ends() {
        let (url, bodies) = server(vec![200, 200]);
        let mut sender = LiveSender::new(&url).unwrap();
        let start = Instant::now();
        sender.frame(0.5, 7.0);
        sender.frame(0.51, 8.0);
        assert_eq!(sender.tick(start), Sent::Lines(2));
        sender.frame(0.52, 9.0);
        // Too soon: nothing goes out until a second has passed.
        assert_eq!(
            sender.tick(start + Duration::from_millis(300)),
            Sent::Nothing
        );
        assert_eq!(sender.finish(), Sent::Lines(2));
        let first = bodies.recv().unwrap();
        assert_eq!(first.lines().count(), 2);
        assert!(first.starts_with(r#"{"type":"frame","t":0.5000,"ms":7.0000}"#));
        let last = bodies.recv().unwrap();
        assert!(last.ends_with(r#"{"type":"end"}"#));
        assert_eq!(sender.lines_sent, 4);
    }

    #[test]
    fn keeps_lines_while_the_server_is_busy_and_stops_when_the_session_is_gone() {
        let (url, bodies) = server(vec![503, 200, 404]);
        let mut sender = LiveSender::new(&url).unwrap();
        let start = Instant::now();
        sender.frame(1.0, 7.0);
        assert!(matches!(sender.tick(start), Sent::Later(_)));
        assert_eq!(sender.tick(start + SEND_EVERY), Sent::Lines(1)); // resent
        sender.frame(2.0, 7.0);
        assert!(matches!(
            sender.tick(start + SEND_EVERY * 2),
            Sent::Stopped(_)
        ));
        assert!(sender.is_stopped());
        sender.frame(3.0, 7.0); // ignored once stopped
        assert_eq!(sender.tick(start + SEND_EVERY * 3), Sent::Nothing);
        assert_eq!(bodies.iter().take(3).count(), 3);
    }

    #[test]
    fn plain_http_to_the_internet_is_refused_up_front() {
        assert!(LiveSender::new("http://pcdoctor.example.com/api/live/k/samples").is_err());
    }
}
