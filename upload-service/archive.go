package main

// Checking an uploaded run. This mirrors api/pcdoctor_api/services/ingest.py:
// the same file names, the same limits, the same messages. An upload is
// untrusted, so only known file names are read, sizes are counted while
// reading (the size a zip declares can lie), and nothing in the archive can
// choose where a file is written.

import (
	"archive/zip"
	"bytes"
	"fmt"
	"io"
	"sort"
	"strings"
)

// The only files a run may contain. Anything else in the archive is ignored.
var runFiles = map[string]bool{
	"manifest.json":    true,
	"specs.json":       true,
	"events.json":      true,
	"disks.json":       true,
	"presentmon.csv":   true,
	"sensors.csv":      true,
	"sensors_raw.json": true,
	"collector.log":    true,
}

const maxArchiveEntries = 200

// UploadError is a problem with the upload that is safe to show to the user.
type UploadError struct{ Message string }

func (e *UploadError) Error() string { return e.Message }

func reject(format string, args ...any) error {
	return &UploadError{Message: fmt.Sprintf(format, args...)}
}

func isZip(data []byte) bool {
	return len(data) >= 4 && (bytes.Equal(data[:4], []byte("PK\x03\x04")) || bytes.Equal(data[:4], []byte("PK\x05\x06")))
}

func looksLikePresentMonCSV(data []byte) bool {
	head := data
	if len(head) > 4096 {
		head = head[:4096]
	}
	head = bytes.TrimPrefix(head, []byte("\xef\xbb\xbf"))
	line, _, _ := bytes.Cut(head, []byte("\n"))
	for _, column := range strings.Split(string(line), ",") {
		switch strings.ToLower(strings.TrimSpace(column)) {
		case "msbetweenpresents", "frametime":
			return true
		}
	}
	return false
}

// depth is the number of path parts, with either kind of slash.
func splitName(name string) (base string, depth int) {
	parts := []string{}
	for _, part := range strings.Split(strings.ReplaceAll(name, "\\", "/"), "/") {
		if part != "" && part != "." {
			parts = append(parts, part)
		}
	}
	if len(parts) == 0 {
		return "", 0
	}
	return strings.ToLower(parts[len(parts)-1]), len(parts)
}

// CleanRun checks an upload and returns a new zip holding only the known
// files, under their own names. A bare PresentMon CSV becomes a one-file run.
func CleanRun(data []byte, maxUnpacked int64) ([]byte, []string, error) {
	if len(data) == 0 {
		return nil, nil, reject("The uploaded file is empty.")
	}
	// The cleaned run is written as we read. Each file goes straight from the
	// upload into a new zip, compressed again, so a zip bomb never sits in
	// memory unpacked: memory follows the compressed size, not the unpacked one.
	var out bytes.Buffer
	writer := zip.NewWriter(&out)
	if !isZip(data) {
		if !looksLikePresentMonCSV(data) {
			return nil, nil, reject("This is not a PC Doctor run. Upload the .zip the collector made, or a PresentMon .csv file.")
		}
		if int64(len(data)) > maxUnpacked {
			return nil, nil, reject("The run unpacks to more than %d MB, which is over the limit.", maxUnpacked/(1024*1024))
		}
		entry, err := writer.Create("presentmon.csv")
		if err != nil {
			return nil, nil, err
		}
		if _, err := entry.Write(data); err != nil {
			return nil, nil, err
		}
		if err := writer.Close(); err != nil {
			return nil, nil, err
		}
		return out.Bytes(), []string{"presentmon.csv"}, nil
	}

	archive, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	if err != nil {
		return nil, nil, reject("The zip file is damaged and cannot be opened.")
	}
	if len(archive.File) > maxArchiveEntries {
		return nil, nil, reject("The zip has far more files than a PC Doctor run contains.")
	}
	// Files at the top level or inside one folder. The shallower copy wins.
	type pick struct {
		file  *zip.File
		depth int
	}
	chosen := map[string]pick{}
	for _, file := range archive.File {
		if file.FileInfo().IsDir() {
			continue
		}
		name, depth := splitName(file.Name)
		if !runFiles[name] || depth > 2 {
			continue
		}
		if previous, seen := chosen[name]; !seen || depth < previous.depth {
			chosen[name] = pick{file, depth}
		}
	}
	if len(chosen) == 0 {
		return nil, nil, reject("No PC Doctor files were found in this zip (expected manifest.json, specs.json, events.json, ...).")
	}
	tooBig := reject("The run unpacks to more than %d MB, which is over the limit.", maxUnpacked/(1024*1024))
	var declared uint64
	for _, p := range chosen {
		if p.file.Flags&0x1 != 0 {
			return nil, nil, reject("The zip is password-protected.")
		}
		declared += p.file.UncompressedSize64
	}
	if declared > uint64(maxUnpacked) {
		return nil, nil, tooBig
	}
	names := make([]string, 0, len(chosen))
	for name := range chosen {
		names = append(names, name)
	}
	sort.Strings(names)
	var written int64
	for _, name := range names {
		reader, err := chosen[name].file.Open()
		if err != nil {
			return nil, nil, reject("The zip file is damaged and cannot be opened.")
		}
		entry, err := writer.Create(name)
		if err != nil {
			reader.Close()
			return nil, nil, err
		}
		// Copy one byte past what is left of the budget to notice an overrun:
		// the size a zip declares can lie.
		copied, err := io.Copy(entry, io.LimitReader(reader, maxUnpacked-written+1))
		reader.Close()
		written += copied
		if written > maxUnpacked {
			return nil, nil, tooBig
		}
		if err != nil {
			return nil, nil, reject("The zip file is damaged and cannot be opened.")
		}
	}
	if err := writer.Close(); err != nil {
		return nil, nil, err
	}
	return out.Bytes(), names, nil
}
