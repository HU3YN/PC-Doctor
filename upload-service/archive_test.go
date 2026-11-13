package main

import (
	"archive/zip"
	"bytes"
	"errors"
	"strings"
	"testing"
)

func makeZip(t testing.TB, files map[string]string) []byte {
	t.Helper()
	var buffer bytes.Buffer
	writer := zip.NewWriter(&buffer)
	for name, content := range files {
		entry, err := writer.Create(name)
		if err != nil {
			t.Fatal(err)
		}
		entry.Write([]byte(content))
	}
	writer.Close()
	return buffer.Bytes()
}

func names(t testing.TB, data []byte) map[string]string {
	t.Helper()
	archive, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	if err != nil {
		t.Fatal(err)
	}
	out := map[string]string{}
	for _, file := range archive.File {
		reader, _ := file.Open()
		var content bytes.Buffer
		content.ReadFrom(reader)
		out[file.Name] = content.String()
	}
	return out
}

const mb = 1024 * 1024

func TestKeepsOnlyKnownFilesUnderTheirOwnNames(t *testing.T) {
	data := makeZip(t, map[string]string{
		"run/manifest.json":       `{"schema_version": 1}`,
		"run/SPECS.JSON":          `{}`,
		"run/passwords.txt":       "secret",
		"../../etc/manifest.json": "escape",
		"a/b/c/events.json":       "too deep",
		"run\\disks.json":         "{}",
	})
	clean, kept, err := CleanRun(data, mb)
	if err != nil {
		t.Fatal(err)
	}
	got := names(t, clean)
	if strings.Join(kept, ",") != "disks.json,manifest.json,specs.json" {
		t.Fatalf("kept %v", kept)
	}
	if got["manifest.json"] != `{"schema_version": 1}` {
		t.Fatalf("the two-part path should beat the three-part one, got %q", got["manifest.json"])
	}
	for name := range got {
		if strings.ContainsAny(name, "/\\") || !runFiles[name] {
			t.Fatalf("unexpected entry %q", name)
		}
	}
}

func TestShallowerCopyWins(t *testing.T) {
	data := makeZip(t, map[string]string{"run/specs.json": "inner", "specs.json": "outer"})
	clean, _, err := CleanRun(data, mb)
	if err != nil || names(t, clean)["specs.json"] != "outer" {
		t.Fatalf("got %v %v", names(t, clean), err)
	}
}

func TestRejections(t *testing.T) {
	many := map[string]string{}
	for i := 0; i < maxArchiveEntries+1; i++ {
		many[strings.Repeat("x", i+1)] = ""
	}
	cases := map[string]struct {
		data []byte
		want string
	}{
		"empty":       {nil, "empty"},
		"not a run":   {[]byte("hello there"), "not a PC Doctor run"},
		"broken zip":  {[]byte("PK\x03\x04 broken"), "damaged"},
		"no known":    {makeZip(t, map[string]string{"notes.txt": "x"}), "No PC Doctor files"},
		"too many":    {makeZip(t, many), "far more files"},
		"unpacks big": {makeZip(t, map[string]string{"sensors.csv": strings.Repeat("0", 2*mb)}), "over the limit"},
	}
	for name, c := range cases {
		_, _, err := CleanRun(c.data, mb)
		var upload *UploadError
		if !errors.As(err, &upload) || !strings.Contains(upload.Message, c.want) {
			t.Errorf("%s: got %v, want a message containing %q", name, err, c.want)
		}
	}
}

func TestBarePresentMonCSV(t *testing.T) {
	csv := []byte("\xef\xbb\xbfApplication,ProcessID, MsBetweenPresents \ngame.exe,1,16.6\n")
	clean, kept, err := CleanRun(csv, mb)
	if err != nil || len(kept) != 1 || kept[0] != "presentmon.csv" {
		t.Fatalf("got %v %v", kept, err)
	}
	if names(t, clean)["presentmon.csv"] != string(csv) {
		t.Fatal("the CSV should be stored unchanged")
	}
}

// go test -fuzz=FuzzCleanRun  (Phase 9: whatever comes in, never panic and
// never emit a file name outside the known list).
func FuzzCleanRun(f *testing.F) {
	f.Add(makeZip(f, map[string]string{"manifest.json": "{}", "x/specs.json": "{}"}))
	f.Add([]byte("Application,MsBetweenPresents\na,1\n"))
	f.Add([]byte("PK\x03\x04"))
	f.Fuzz(func(t *testing.T, data []byte) {
		clean, kept, err := CleanRun(data, 4*mb)
		if err != nil {
			return
		}
		for name := range names(t, clean) {
			if !runFiles[name] {
				t.Fatalf("emitted %q", name)
			}
		}
		if len(kept) == 0 {
			t.Fatal("accepted an upload with no files")
		}
	})
}
