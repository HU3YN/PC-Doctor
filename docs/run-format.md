# Run format (version 1)

A run is one folder written by the collector, zipped for upload. Every file is
plain text and every file is optional: the analyzer uses what is there and
says what it could not check.

| File | Contents |
|---|---|
| `manifest.json` | What was collected, when, how. `schema_version`, `run_id`, `collector` (name, version), `started_at` / `finished_at` (UTC, ISO 8601), `mode` (`quick` or `capture`), `label`, `capture`, `event_window_days`, `is_admin`, `warnings` |
| `specs.json` | `os`, `system` (manufacturer, model, `type`: desktop / laptop / server), `cpu[]`, `gpu[]`, `memory` (`total_bytes`, `slots_total`, `modules[]`: `slot`, `capacity_bytes`, `speed_mhz`, `configured_speed_mhz`, `manufacturer`, `part_number`, `type`, `form_factor`, `bank`), `motherboard`, `bios`, `power_plan`, `power_plan_guid`, `battery` |
| `events.json` | `window_days`, `collected_at`, `events[]` (`time`, `provider`, `id`, `level`, `log`, `message`, `data`), `errors[]` |
| `disks.json` | `physical_disks[]` (`name`, `media_type`, `bus_type`, `health_status`, `operational_status`, `size_bytes`, `firmware`, `reliability`, `number`) and `volumes[]` (`drive_letter`, `file_system`, `size_bytes`, `free_bytes`, `health_status`, `is_system`) |
| `presentmon.csv` | PresentMon's own output, filtered to one program. Any PresentMon header style is accepted (see `workers/pcdoctor_analysis/presentmon.py`) |
| `sensors.csv` | One row per sample: `elapsed_s` then the fixed columns below. An empty cell means "no reading" |
| `sensors_raw.json` | One snapshot of LibreHardwareMonitor's sensor names, for debugging the mapping on unusual hardware |
| `collector.log` | What the collector did and any warnings |

`capture` in the manifest: `requested_seconds`, `actual_seconds`,
`target_process`, `presentmon` (`used`, `version`, `exit_code`, `frames`,
`other_processes_removed`), `sensors` (`source`, `interval_seconds`, `samples`).
`sensors.source` is `librehardwaremonitor`, `windows+nvidia-smi` or `windows`.

## Optional fields added later

Runs written before these fields existed are still valid: a missing field
means the same as `null`.

- `disks.json` `physical_disks[].number` (added 2026-11-15): the Windows disk
  number as an integer (from `Get-PhysicalDisk`'s `DeviceId`), the "Disk 3"
  that disk events name. `null` if Windows gave none. A disk event naming a
  number that no listed disk has is a drive that is not plugged in now (or one
  Windows does not list as a physical disk).
- `specs.json` `memory.modules[].bank` (added 2026-11-15): the module's
  `BankLabel` from Windows, trimmed, at most 40 characters, `null` if empty.
  On some boards every module has the same `slot` (e.g. `DIMM 1`) and only
  `bank` tells the channels apart (e.g. `P0 CHANNEL A` / `P0 CHANNEL B`).
- `manifest.json` `capture.load_at_start` (added 2026-11-17): what the
  collector saw just before the capture began - `busy` (`true`, `false`, or
  `null` when the PC gave no load reading), `gpu_load_pct` and `cpu_load_pct`
  (medians of three readings) and `waited_seconds` (how long it waited for a
  game or stress test to start). "Busy" is a GPU at 30% or more, or a CPU at
  50% or more.

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
