# Security

## Reporting a problem

Please report security problems privately through GitHub: open the
repository's **Security** tab and choose **Report a vulnerability**
(GitHub private vulnerability reporting). Do not open a public issue for
something that could hurt people running PC Doctor.

Say what you found, how to reproduce it, and what it lets someone do. This is
a one-person student project, so replies can take a few days.

## What is in scope

This repository's own code: the collector (`collector/`), the API (`api/`),
the dashboard (`web/`), the upload service (`upload-service/`), the worker,
the Discord bot (`bot/`) and the deployment files (`deploy/`).

Not in scope: third-party tools the collector downloads (PresentMon,
LibreHardwareMonitor) and services PC Doctor talks to (Discord, Google,
Anthropic). Report those to their owners.

## How it is built to be safe

- The collector is read-only and collects no personal data
  ([docs/privacy.md](docs/privacy.md)).
- Everything stored needs a sign-in; guests reach one run through a private
  key, and a test fails the build if a route is left open
  (`api/tests/test_auth.py`).
- Uploads are checked before anything is unpacked: size, entry count,
  allow-listed names, no paths (`api/pcdoctor_api/services/ingest.py`,
  `upload-service/`), and these checks are fuzzed ([fuzz/](fuzz/)).
- Do not expose PC Doctor to the internet without HTTPS.

The threat model, with what is mitigated and what is still open, is in
[docs/threat-model.md](docs/threat-model.md).

## Supported versions

Only the latest commit on the main development branch.
