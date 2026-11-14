//! Following a file while another program writes to it.
//!
//! PresentMon appends rows to its CSV as frames happen. We read whatever is new
//! every few hundred milliseconds. A read can end in the middle of a line (the
//! writer has not finished it yet), so bytes are kept in [`LineBuffer`] until
//! their newline arrives.

use std::fs::File;
use std::io::{self, Read};
use std::path::{Path, PathBuf};

/// Turns chunks of bytes into complete lines, holding back an unfinished one.
#[derive(Debug, Default)]
pub struct LineBuffer {
    pending: Vec<u8>,
}

impl LineBuffer {
    pub fn new() -> Self {
        Self::default()
    }

    /// Add bytes; return every line they complete (without `\n` or `\r\n`).
    pub fn push(&mut self, bytes: &[u8]) -> Vec<String> {
        self.pending.extend_from_slice(bytes);
        let mut lines = Vec::new();
        // Find the last newline: everything before it is complete lines,
        // everything after it waits for the next push.
        let Some(last_newline) = self.pending.iter().rposition(|&b| b == b'\n') else {
            return lines;
        };
        let rest = self.pending.split_off(last_newline + 1);
        let complete = std::mem::replace(&mut self.pending, rest);
        for raw in complete.split(|&b| b == b'\n') {
            // Blank lines carry nothing (and split() yields an empty piece
            // after the final '\n'), so they are skipped.
            let line = decode_line(raw);
            if !line.is_empty() {
                lines.push(line);
            }
        }
        lines
    }

    /// True when bytes are waiting for their newline.
    pub fn has_partial(&self) -> bool {
        !self.pending.is_empty()
    }

    /// Take the unfinished last line, if any. Only call this once the writer
    /// has stopped: a line without a newline is then complete, just unterminated.
    pub fn take_partial(&mut self) -> Option<String> {
        if self.pending.is_empty() {
            return None;
        }
        let raw = std::mem::take(&mut self.pending);
        Some(decode_line(&raw)).filter(|line| !line.is_empty())
    }
}

/// Bytes -> text. PresentMon writes ASCII (or UTF-8); a stray invalid byte
/// becomes U+FFFD instead of failing the whole capture.
fn decode_line(raw: &[u8]) -> String {
    let raw = raw.strip_suffix(b"\r").unwrap_or(raw);
    String::from_utf8_lossy(raw).into_owned()
}

/// Reads new lines from a file that may not exist yet and may still grow.
#[derive(Debug)]
pub struct FileTail {
    path: PathBuf,
    file: Option<File>,
    buffer: LineBuffer,
    /// The last reason the file could not be opened, for the final report.
    last_open_error: Option<io::Error>,
}

impl FileTail {
    pub fn new(path: impl AsRef<Path>) -> Self {
        Self {
            path: path.as_ref().to_path_buf(),
            file: None,
            buffer: LineBuffer::new(),
            last_open_error: None,
        }
    }

    /// Read everything appended since the last call and return the complete
    /// lines. A file that cannot be opened yet gives no lines, not an error:
    /// PresentMon creates its file a moment after it starts, and on Windows the
    /// writer may hold it without read sharing until it exits (not verified on
    /// a real PC - see README), in which case everything is read at the end.
    pub fn poll(&mut self) -> io::Result<Vec<String>> {
        if self.file.is_none() {
            match File::open(&self.path) {
                Ok(file) => {
                    self.file = Some(file);
                    self.last_open_error = None;
                }
                Err(error) => {
                    self.last_open_error = Some(error);
                    return Ok(Vec::new());
                }
            }
        }
        let mut chunk = Vec::new();
        if let Some(file) = self.file.as_mut() {
            // read_to_end continues from where the previous read stopped, so
            // each byte is read exactly once.
            file.read_to_end(&mut chunk)?;
        }
        Ok(self.buffer.push(&chunk))
    }

    /// The last read. With `writer_finished`, an unterminated last line is
    /// returned too; without it (the file may still be written), it is dropped,
    /// because a half-written row would carry a truncated number.
    /// Fails if the file never could be opened.
    pub fn finish(&mut self, writer_finished: bool) -> io::Result<Vec<String>> {
        let mut lines = self.poll()?;
        if self.file.is_none() {
            return Err(self
                .last_open_error
                .take()
                .unwrap_or_else(|| io::Error::new(io::ErrorKind::NotFound, "file not found")));
        }
        if writer_finished {
            lines.extend(self.buffer.take_partial());
        }
        Ok(lines)
    }

    /// True once the file has been opened at least once.
    pub fn is_open(&self) -> bool {
        self.file.is_some()
    }

    /// True when an unfinished line is being held back.
    pub fn has_partial(&self) -> bool {
        self.buffer.has_partial()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    #[test]
    fn holds_back_a_partial_line_until_its_newline() {
        let mut buffer = LineBuffer::new();
        assert_eq!(buffer.push(b"Application,Ms"), Vec::<String>::new());
        assert!(buffer.has_partial());
        assert_eq!(
            buffer.push(b"BetweenPresents\r\nGame.exe,7.1\r\nGa"),
            vec!["Application,MsBetweenPresents", "Game.exe,7.1"]
        );
        assert_eq!(buffer.push(b"me.exe,7.2\n"), vec!["Game.exe,7.2"]);
        assert!(!buffer.has_partial());
    }

    #[test]
    fn skips_empty_lines_and_handles_invalid_utf8() {
        let mut buffer = LineBuffer::new();
        let lines = buffer.push(b"a\n\n\r\nb\xff\n");
        assert_eq!(lines, vec!["a", "b\u{fffd}"]);
    }

    #[test]
    fn take_partial_returns_the_unterminated_tail_once() {
        let mut buffer = LineBuffer::new();
        buffer.push(b"x\nlast,7.5");
        assert_eq!(buffer.take_partial().as_deref(), Some("last,7.5"));
        assert_eq!(buffer.take_partial(), None);
    }

    #[test]
    fn tails_a_growing_file() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("pm.csv");
        let mut tail = FileTail::new(&path);

        // Not created yet: no lines, no error.
        assert!(tail.poll().unwrap().is_empty());
        assert!(!tail.is_open());

        let mut writer = File::create(&path).unwrap();
        writer
            .write_all(b"Application,MsBetweenPresents\nGame.exe,7.")
            .unwrap();
        writer.flush().unwrap();
        assert_eq!(tail.poll().unwrap(), vec!["Application,MsBetweenPresents"]);
        assert!(tail.has_partial());

        writer.write_all(b"1\nGame.exe,7.3").unwrap();
        writer.flush().unwrap();
        assert_eq!(tail.poll().unwrap(), vec!["Game.exe,7.1"]);

        // The writer may still be busy: the half row is dropped...
        let mut copy = FileTail::new(&path);
        assert_eq!(copy.finish(false).unwrap().len(), 2);
        // ...but once it has exited, the unterminated row is complete data.
        assert_eq!(tail.finish(true).unwrap(), vec!["Game.exe,7.3"]);
    }

    #[test]
    fn finish_reports_a_file_that_never_appeared() {
        let dir = tempfile::tempdir().unwrap();
        let mut tail = FileTail::new(dir.path().join("missing.csv"));
        assert!(tail.finish(true).is_err());
    }
}
