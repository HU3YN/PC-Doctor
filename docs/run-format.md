# Run format (version 1)

A run is one folder written by the collector, zipped for upload. Every file is
plain text and every file is optional: the analyzer uses what is there and
says what it could not check.

| File | Contents |
|---|---|
| `manifest.json` | What was collected, when, how. `schema_version`, `run_id`, `collector` (name, version), `started_at` / `finished_at` (UTC, ISO 8601), `mode` (`quick` or `capture`), `label`, `capture`, `event_window_days`, `is_admin`, `warnings` |
| `specs.json` | `os`, `system` (manufacturer, model, `type`: desktop / laptop / server), `cpu[]`, `gpu[]`, `memory` (`total_bytes`, `slots_total`, `modules[]`), `motherboard`, `bios`, `power_plan`, `power_plan_guid`, `battery` |
| `events.json` | `window_days`, `collected_at`, `events[]` (`time`, `provider`, `id`, `level`, `log`, `message`, `data`), `errors[]` |
| `disks.json` | `physical_disks[]` (`name`, `media_type`, `bus_type`, `health_status`, `operational_status`, `size_bytes`, `firmware`, `reliability`) and `volumes[]` (`drive_letter`, `file_system`, `size_bytes`, `free_bytes`, `health_status`, `is_system`) |
| `presentmon.csv` | PresentMon's own output, filtered to one program. Any PresentMon header style is accepted (see `workers/pcdoctor_analysis/presentmon.py`) |
| `sensors.csv` | One row per sample: `elapsed_s` then the fixed columns below. An empty cell means "no reading" |
| `sensors_raw.json` | One snapshot of LibreHardwareMonitor's sensor names, for debugging the mapping on unusual hardware |
| `collector.log` | What the collector did and any warnings |

`capture` in the manifest: `requested_seconds`, `actual_seconds`,
`target_process`, `presentmon` (`used`, `version`, `exit_code`, `frames`,
`other_processes_removed`), `sensors` (`source`, `interval_seconds`, `samples`).
`sensors.source` is `librehardwaremonitor`, `windows+nvidia-smi` or `windows`.

## sensors.csv columns

`cpu_temp_c`, `cpu_load_pct`, `cpu_core_max_load_pct`, `cpu_clock_mhz`,
`cpu_perf_pct` (speed relative to rated speed, from Windows), `cpu_power_w`,
`gpu_temp_c`, `gpu_hotspot_c`, `gpu_load_pct`, `gpu_clock_mhz`, `gpu_power_w`,
`gpu_fan_rpm`, `gpu_vram_used_pct`, `ram_used_pct`.

Decimals always use a dot. Readings outside a sane range (a temperature of 0
or 255) are ignored by the analyzer.

## Changing the format

Add fields freely: readers ignore what they do not know. A change that would
make an old reader misread a file needs a new `schema_version`; the analyzer
warns when it meets a version it does not know. The collector CI job feeds
real collector output to the analyzer, so the two cannot drift apart silently.
