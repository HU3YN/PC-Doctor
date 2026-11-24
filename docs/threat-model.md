# Threat model

Written from the code at commit `1ae894f` (November 2026), not from the plans,
and updated on 2026-11-14 and 2026-11-15 after the fixes marked in section 4 and
the additions in section 3.9.
Every mitigation below names the file and function that does it; if you change
one of them, change this page too. "Open" means it is not handled today.

PC Doctor is a one-person project meant to run on a technician's own computer,
on a trusted LAN, or (Phase 3, never applied yet) on one k3s server behind
HTTPS. The threat model is written for those three set-ups:

| Set-up | How it is reached | Transport |
|---|---|---|
| **Local** (default) | `docker-compose.yml` binds nginx to `127.0.0.1:8080`; the Python route binds uvicorn to `127.0.0.1` (`Start-PCDoctor.ps1`) | HTTP, loopback only |
| **LAN** (`Start-PCDoctor.cmd -Lan`) | Binds `0.0.0.0`; every device on the network can reach it | **Plain HTTP** |
| **Cloud** (`deploy/k8s`, untested) | Traefik ingress with a Let's Encrypt certificate, HTTP redirected to HTTPS | HTTPS |

## 1. What is protected

| Asset | Where it lives | Why it matters |
|---|---|---|
| Stored runs (zips, findings, the parts list of each PC) | `data/runs/*.zip`, `runs` and `findings` tables | Hardware details of customers' PCs; the master's notes on them |
| The work log | `work_log` table | The technician's private record of jobs and fixes |
| Photos in the inbox | `data/photos/*.jpg`, `photos` table | Photos of customers' PCs (may show more than intended) |
| The master account | `accounts` (role `master`), scrypt hash | Whoever holds it sees and deletes everything |
| Sign-in sessions | `pcdoctor_session` cookie; `sessions` table keeps only a SHA-256 of the token | A stolen cookie is the account for 30 days |
| Share keys (guest links `/r/<key>`) | Given to the uploader once; `runs.share_hash` keeps only a SHA-256 | Each one opens one run |
| Photo-link tokens (QR codes) | Shown once; `photo_links.token_hash` | Lets a phone add photos for 12 hours |
| OAuth identities | `identities` table: provider + provider's user id only | Links a Discord/Google account to a PC Doctor account |
| Secrets | `.env` (git-ignored, `.gitignore`), Compose environment, the k8s `pcdoctor-secrets` Secret | `POSTGRES_PASSWORD`, OAuth client secrets, `ANTHROPIC_API_KEY`, `PCDOCTOR_BOT_TOKEN`, the Discord webhook URL, `PCDOCTOR_METRICS_TOKEN`, the Discord bot's own `DISCORD_BOT_TOKEN`, the setup code (`data/setup-code.txt`) |
| Integrity of the collector zip | Built on the fly by `GET /api/collector.zip` | It is run **as administrator** on the PC being checked |
| The PCs that run the collector | Customers' and the technician's machines | The collector is read-only by design, with one exception (a temporary temperature driver, only after a yes; item #21); a tampered one would not be |

## 2. Actors

| Actor | What they can do by design | What they must not be able to do |
|---|---|---|
| **Guest uploader** (no account) | Download the collector; upload a run; read that one run through its share key | List or read any other run, the work log, photos |
| **Phone with a QR link** | `GET /api/photo-links/{token}` (label, expiry) and add photos for 12 h | Read any photo or anything else |
| **Member** (Discord/Google sign-in, `role="member"`) | Everything a guest can; list, read and delete the runs they uploaded while signed in (`/api/me/...`) | Any master-only route (403), other people's runs, the work log, notes, similar cases |
| **Master** | Everything | - |
| **Discord bot** (`bot/`) | Upload as a guest. With `PCDOCTOR_BOT_TOKEN` it gets its own, higher upload limit; nothing else | Read anything other than the share link the API hands back for its own upload |
| **Someone on the same LAN** | In LAN mode: everything a guest can, plus watch and change plain-HTTP traffic (ARP spoofing, a rogue Wi-Fi access point) | - |
| **Internet attacker** (cloud set-up, or a LAN set-up port-forwarded by mistake) | Everything a guest can, from many addresses; password guessing; resource exhaustion | - |
| **A malicious file** (run zip, CSV, photo) | Reaches the zip reader, the CSV/JSON parsers, the rules engine, Pillow, Tesseract, and (as text) the Discord webhook and the AI prompts | Write outside the temp folder, exhaust memory/disk, run code |
| **A compromised dependency** | Python (exact versions and hashes in `api/requirements.lock`), npm (lockfile), Go (`go.sum`), base and Compose images (digests), GitHub Actions (commit SHAs), PresentMon (shipped inside the collector zip; SHA-256 pinned at build, Intel signature checked at run time) | - |

## 3. Entry points

The "Still open" cells below say what is open today. Where section 4 marks a
problem **Fixed**, the cell says "Was (fixed, item #n)" and keeps only what is
left.

### 3.1 The API (FastAPI, `api/pcdoctor_api/`)

How access is decided, for every route below: `deps.py` - `current_account`
reads the `pcdoctor_session` cookie and looks up the hash
(`services/auth.py:account_for`, which also checks expiry); `require_master`
answers 401 without a session and 403 for a member. `api/tests/test_auth.py`
(`test_every_api_route_is_either_master_only_or_deliberately_public`) fails the
build if a new route is in neither list.

The session cookie is set in `routers/auth.py:set_cookie`: `HttpOnly`,
`SameSite=Lax`, `Secure` only when the request was HTTPS (or
`X-Forwarded-Proto: https`). **There is no CSRF token.** Cross-site protection
rests on `SameSite=Lax` (a cross-site POST/PATCH/DELETE carries no cookie, so it
arrives as a guest) and on CORS being off unless `PCDOCTOR_CORS_ORIGINS` is set
(`main.py:create_app`). No route that changes state is a GET, except the OAuth
callback, which is guarded by `state`.

| Entry point | Threats | Mitigation that exists | Still open |
|---|---|---|---|
| **Sign-in** `POST /api/auth/setup`, `/login`, `/logout`, `GET /status` (`routers/auth.py`) | First visitor claims the master account; password guessing; stolen session | `setup` needs the code from `services/auth.py:setup_code` (16 hex chars, 64 bits, printed on the server console, stored in `data/setup-code.txt`, deleted after use), compared with `hmac.compare_digest`; refuses once a master exists (409). Set-up attempts are rate-limited like logins (`setup:` key), and a partial unique index (`uq_accounts_one_master`) allows one master only. `login` is limited to 8 attempts / 15 min per client (`login_attempts`, `RateLimiter.allow`), checks a dummy hash for unknown users so timing is the same, scrypt hashes (`hash_password`, `verify_password`), 10-character minimum. Session tokens are 256-bit (`new_token`) and only their SHA-256 is stored (`create_session`, `token_hash`). The master can change the password (`POST /api/auth/password`) and sign out everywhere (`POST /api/auth/logout-everywhere`). | No password reset if the master password is lost, no list of sessions; sessions last 30 days with no idle timeout. The limiter counts successful logins too. Was (fixed, items #9 and #11): `/setup` had no rate limit and a 32-bit code; two `/setup` requests at the same moment could create two masters; no password change and no "sign out everywhere". |
| **OAuth** `GET /api/auth/oauth/{name}/start`, **callback** `/api/auth/oauth/{name}/callback` (`routers/oauth.py`, `services/oauth.py`) | Login CSRF (attacker's identity signed in on the victim's browser); stolen authorization code; linking someone else's identity; open redirect | `start` puts a random `state` and PKCE verifier in a short-lived HttpOnly cookie scoped to `/api/auth/oauth` (`FLOW_COOKIE`, 600 s); `callback` compares `state` in constant time and sends the verifier with the code (`fetch_subject`, S256 challenge in `challenge_for`). The redirect URI is built from `PCDOCTOR_PUBLIC_URL`, never from the request (`redirect_uri`, `back`). `http_client` does not follow redirects. Linking needs a signed-in session at both ends and refuses an identity owned by another account (`"taken"`). New members only with `PCDOCTOR_OAUTH_SIGNUP=true` and only once a master exists (`member_for`). Only the provider's id is stored; the access token is dropped. Sign-in stays off unless `PCDOCTOR_PUBLIC_URL` is HTTPS, or HTTP to this computer or a private address (`oauth.public_url_ok`, item #17). | Never tried against real Discord or Google (docs/oauth.md). With sign-up on, anyone with a Discord or Google account gets a member account (by design; each gets guest upload limits). |
| **Accounts** `GET /api/accounts`, `DELETE /api/accounts/{id}`, `GET/DELETE /api/auth/identities...` | A member removing others or the master; a member locking themselves out | `list_accounts`/`remove_account` are `Master`; the master cannot be removed. `unlink` only touches the caller's own identity and will not remove a member's last one. Removing an account cascades to its identities and sessions (`ondelete="CASCADE"` in `models.py`; SQLite gets `PRAGMA foreign_keys=ON` in `db.py`). | - |
| **Run upload** `POST /api/runs` (`routers/runs.py:upload_run`) | Zip bombs, path traversal, huge files, parser bugs; flooding; using it to read others' runs | Size capped while reading (`read_limited`, `PCDOCTOR_MAX_UPLOAD_MB`, nginx `client_max_body_size 250m`). `services/ingest.py:unpack` reads only the eight names in `RUN_FILES`, at most one folder deep, never uses the archive's path, caps entries (`MAX_ARCHIVE_ENTRIES`), refuses encrypted entries, counts real bytes against `PCDOCTOR_MAX_UNPACKED_MB`, turns every zip-library error into `UploadError`. `_clean_zip` stores only what was read. Unpacking and analysis run on a worker thread (`run_in_threadpool`), so one upload does not stall the API (item #6). JSON files over 20 MB are refused (`workers/.../loader.py`, `MAX_JSON_BYTES`); PresentMon over 2 M rows is refused (`presentmon.py`, `MAX_ROWS`). Non-master uploads are rate-limited, 30/hour per client (`_check_upload_limit`, `guest_uploads`) and get a fresh 256-bit share key whose hash is stored. Every guest upload gets its own key in the `share_keys` table (`add_share_key`) with the uploader's own label, so a duplicate upload (same bytes, matched on `content_hash`) leaves earlier links working and does not show another uploader's label (item #7). The upload path is fuzzed (`fuzz/`). | Memory use of the analysis on a 1 GB unpacked run has not been measured. See also 3.6 for the client key used for limits. Was (fixed, items #6 and #7): `upload_run` called the synchronous `ingest` inside `async def` and blocked every other request; a duplicate upload replaced the share key of the earlier uploader. |
| **Run reading** `GET /api/runs...`, `PATCH`, `DELETE`, `/download`, `/reanalyze` | Guests or members reading or changing runs | All `Master`. `download_run` serves `runs_dir / run.file_name`, a name the server made (`{id}.zip`). | - |
| **Member runs** `/api/me/runs...` | A member reading another member's run, or guessing run ids | `own_run` checks `owner_id` and answers 404 (not 403) for someone else's run. `my_run` strips `similar_cases`, `work_log` and `notes`. | - |
| **Share links** `GET /api/shared/{key}`, `/series` | Guessing keys; seeing more than one run | `run_for_key` looks up the SHA-256 of a 256-bit key; `read_shared_run` strips work log, similar cases and notes. | No expiry for a share key. The master can revoke one key (`DELETE /api/runs/{id}/links/{link_id}`, `revoke_link`) or delete the run (item #11). Keys sit in URL paths; nginx and uvicorn replace them with a placeholder in the access log (`logs.py:redact`, item #19), so only a proxy in front of nginx would log them whole. |
| **Collector download** `GET /api/collector.zip`, `GET /api/collector` (`routers/intake.py`) | A tampered collector, run as administrator | `collector_zip` ships only the files in `COLLECTOR_FILES` plus the one PresentMon that `Get-Tools.ps1` pins (`collector_build.py:trusted_tools`: that file name, with that SHA-256, checked again on every build; anything else in `tools/` is left out). The zip is built reproducibly, so it has a stable hash, shown by `GET /api/collector` and on the release (item #1, section 5). | Served over plain HTTP in LAN mode (anyone on the LAN can swap it), and the hash only helps someone who compares it with GitHub. **The zip now carries a third-party executable that the collector runs as administrator** (Intel's PresentMon, unmodified): whoever can change both the pin in `Get-Tools.ps1` and the file gets admin code on every PC checked, the same door as changing the scripts. A server without the pinned file serves the scripts alone, with a different hash from the release. `GET /api/collector` tells anyone the server's LAN address (`lan_addresses`). See section 5. |
| **Photo inbox: phone side** `GET /api/photo-links/{token}`, `POST /api/photo-links/{token}/photos` (`routers/inbox.py`) | Reading photos; flooding the inbox; malicious images; location data in photos | Links are made by the master only (`create_link`), 256-bit, hash stored, 12-hour expiry checked in `link_for`. The phone side can only add; it answers `{"received": true}`. 30 photos/hour per client (`guest_uploads` with a `photo:` key). Each photo is decoded and re-encoded to plain JPEG before it is stored (`services/photo.py:to_jpeg`), which drops EXIF/GPS; `MAX_PIXELS` and a 25 MB cap. Only JPEG, PNG and WebP are decoded (`ALLOWED_FORMATS`), and Pillow's pixel-limit warning is an error (item #16). Pillow and Tesseract run on a worker thread (item #6). The master can revoke a link before its 12 hours are up (`revoke_link`, item #11). The token is in the URL path (`/snap/<token>`), but access logs show a placeholder (item #19). | OCR of one photo can take up to `OCR_SECONDS` (40 s) of a worker thread. Was (fixed, items #6, #11, #16, #19): Pillow and OCR ran inside `async def` and blocked the API; no way to revoke a link; Pillow opened any format and decoded 40-80 M pixel images with only a warning; the token was in access logs. |
| **Photo inbox: master side** `/api/inbox...`, `POST /api/photos` (OCR without storing) | Others reading photos | All `Master`; `photo_image` serves a server-made file name. | Was (fixed, item #6): `read_photo` ran OCR synchronously inside `async def`. It now uses `run_in_threadpool`. |
| **Work log** `/api/worklog...` (`routers/worklog.py`) | Anyone reading or importing | The whole router has `dependencies=[Depends(require_master)]`. Entries that look like they hold personal data are flagged (`services/privacy.py:privacy_warnings`). | `import_entries` takes an unbounded JSON body (master only). |
| **Reference** `/api/health`, `/meta`, `/stopcodes`, `/stopcodes/{code}`, `/noboot`; `/stats`, `/demo` | Leaking work-log cases through the public stop-code page | `stop_code` returns earlier cases only when the caller is the master. `stats`, `load_demo`, `clear_demo` are `Master`. | - |
| **AI helper** `/api/assist`, `/draft`, `/troubleshoot`, `/api/inbox/{id}/describe` (`routers/assist.py`, `services/ai.py`) | Prompt injection from upload text (disk and GPU names, event text, OCR text); data sent to a third party; cost | All `Master`; runs only when pressed and only with `ANTHROPIC_API_KEY`. The model has no tools; the reply is parsed as JSON and cut to known fields, sizes and categories (`parse_json`, `clean_draft`, `clean_photo_notes`); it is a draft the master edits. | Injected text can still steer the draft's wording. Photos and run material go to Anthropic when the master presses the button (documented in docs/privacy.md). |
| **Metrics** `GET /api/metrics` (`metrics.py:metrics`) | Leaking request counts | 404 without `PCDOCTOR_METRICS_TOKEN`; bearer token compared in constant time. | `/api/` is reachable through nginx, so in LAN mode the token is the only protection. Was (fixed, item #14): `docker-compose.scale.yml` defaulted the token to `local-metrics`; now Compose stops without a token and `weak_token` turns metrics off for a token under 16 characters or a well-known one. |
| **Dashboard files** (`main.py:mount_dashboard` for the Python route; nginx in Docker) | Path traversal; XSS; clickjacking | `mount_dashboard` resolves the path and checks `is_relative_to(dist)`. React escapes all text; there is no `dangerouslySetInnerHTML` in `web/src`. nginx (`web/security-headers.conf`) and the API (`main.py`) send a strict CSP, `Referrer-Policy: no-referrer`, `nosniff` and `X-Frame-Options: DENY` (item #13); the k8s ingress adds HSTS through Traefik. | "Same site" ignores the port, so other services on the same host (Grafana on :3000 in the scale stack) count as same-site for `SameSite=Lax`. Was (fixed, item #13): the Compose nginx sent no CSP or other security headers. |

### 3.2 The Go upload service (`upload-service/`)

| Entry point | Threats | Mitigation that exists | Still open |
|---|---|---|---|
| `POST /upload` (`server.go:Server.upload`) | Zip bombs, huge bodies, flooding, spool tampering | Rate limit per client in Redis before reading the body (`redisQueue.Allow`, 30/hour). `http.MaxBytesReader` on the body, `io.LimitReader` on the file. `archive.go:CleanRun` mirrors `ingest.unpack`: allow-listed names only, depth at most 2 (`splitName`), entry cap, encrypted entries refused, declared and real sizes both checked; it writes a new zip of only those files. The spool name is random (`randomToken`), written atomically (`writeAtomically`). The share key is returned once; only its hash goes in the job. Timeouts on the server (`main.go`). | `CleanRun` copies each file straight into the new zip (item #5), so a zip bomb is no longer held in memory. Was (fixed, item #5): it held every decompressed file in memory, up to 1024 MB against a 768 Mi container limit. Its rate-limit counter (`pcdoctor:uploads:<ip>`) is separate from the API's (`pcdoctor:limit:uploads:<ip>`), so a guest gets 30 per hour on each path. |
| `GET /jobs/{id}` | Learning about other uploads | Job ids are 128-bit random. The state holds only status, an error message and a run id (a run id alone opens nothing). | - |
| `GET /metrics`, `GET /healthz` | Information leak | Compose binds 8090 to `127.0.0.1`; the k8s ingress publishes only `/upload` and `/jobs/` (`deploy/k8s/ingress.yaml`). | Unauthenticated inside the cluster/Docker network. |

### 3.3 The worker (`api/pcdoctor_api/worker.py`)

| Entry point | Threats | Mitigation that exists | Still open |
|---|---|---|---|
| Redis list `pcdoctor:jobs` and the spool folder | A forged job reading files outside the spool; a swapped file; a bad job stopping the worker | Redis needs a password in the scale stack and in k3s, and `network.yaml` lets only the app's own pods (api, worker, upload) reach it and PostgreSQL (item #10). `process_job` treats the queue as untrusted: the file name must match `_SAFE_NAME` (no slashes), the share hash `_HASH`, and the file's SHA-256 must match the job's. Then the same `ingest` as the API. `handle` catches everything so one job cannot stop the worker. The spool file is always removed. | Anyone who has the Redis password, or a foothold in the API, worker or upload pod, can still push jobs (for example a job naming a waiting spool file with its own share hash, to get a link to someone else's upload), read job states, or clear rate-limit counters. `deploy/k8s/network.yaml` is only checked for its shape in CI, not applied to a cluster. `BLPOP` drops a job if the worker dies mid-job. Was (fixed, items #7 and #10): Redis had no password in the scale stack or k3s and no NetworkPolicy; a duplicate upload replaced the earlier share key (the worker now adds a key of its own). Worker metrics on port 9101 are unauthenticated (internal). |

### 3.4 Notifications (`api/pcdoctor_api/services/notify.py`)

| Entry point | Threats | Mitigation that exists | Still open |
|---|---|---|---|
| Outgoing Discord webhook on a new guest run (`new_guest_run`) | Leaking the share link or the uploader; SSRF through the URL; pings; a failing webhook breaking uploads | Only verdict and headline are sent (`message_for`); the URL must start with a Discord webhook prefix (`ALLOWED_PREFIXES`); `allowed_mentions: {"parse": []}`; errors are swallowed; it runs after the response (background task). The headline and verdict go through `notify.escape`, the same list as the bot's escaper, because a finding title can hold text from the upload (a disk or GPU name) (item #8). | The webhook URL is itself a secret: anyone with it can post to that channel. Was (fixed, item #8): the headline was not escaped, so a guest could put a masked link into the master's channel. |

### 3.5 The Discord bot (`bot/pcdoctor_bot/`)

| Entry point | Threats | Mitigation that exists | Still open |
|---|---|---|---|
| `/diagnose` slash command (`__main__.py:diagnose`) | Being used in unapproved servers; SSRF through the attachment URL; huge files; leaking the private link; formatting/ping injection; flooding | `core.load_settings` refuses to start without `DISCORD_GUILD_IDS`; `leave_if_not_allowed` leaves any other server; `diagnose` checks the guild again. `check_attachment` allows only `.zip`/`.csv`, only `https://cdn.discordapp.com` or `media.discordapp.net`, no port or credentials, and checks the size before download; `download_attachment` does not follow redirects and counts bytes as they arrive. Per-user cooldown (`Cooldown.retry_after`). The reply is ephemeral unless the user chooses to show the summary; the private link always goes to the user alone. `escape` strips formatting and mentions; `allowed_mentions` is none. Tokens have `repr=False`; `configure_logging` silences httpx so share keys are not logged. | The cooldown is in memory (lost on restart). Was (fixed, item #7): if two people diagnosed the same file, the second upload replaced the first one's share key. Not run against a real Discord server yet. |
| `X-PCDoctor-Bot-Token` header on `POST /api/runs` | A stolen token used to read runs, or to skip limits | `_check_upload_limit`: the token only chooses the `bot_uploads` limit (300/hour, one shared bucket); compared in constant time (`is_bot_token`); a wrong token is 401; the upload is still a guest upload. | Whoever has the token can use up the bot's whole hourly budget (a denial of service for the bot). The token travels over whatever `PCDOCTOR_URL` is, which may be plain HTTP. |

### 3.6 Rate limits and the client address

`deps.py:client_key` uses the peer address, or, when `PCDOCTOR_TRUST_PROXY=true`,
the **last** `X-Forwarded-For` entry. Limits live in process memory, or in
Redis when `PCDOCTOR_REDIS_URL` is set (`services/auth.py:use_shared_limits`;
if Redis fails, `RateLimiter.allow` falls back to memory).

- Compose: `PCDOCTOR_TRUST_PROXY=true`, nginx appends the peer address
  (`$proxy_add_x_forwarded_for`), so the last entry is the real client. Correct.
- k8s: Traefik is in front of nginx, which is in front of the API, so the last
  `X-Forwarded-For` entry is Traefik's. `PCDOCTOR_PROXY_HOPS` (2 in
  `deploy/k8s/app.yaml`) makes `client_key` count back past both proxies, so
  every client has its own bucket (item #4). The default is 1: if you put
  another HTTPS proxy in front of the Compose stack, set it to 2 (docs/lan-https.md),
  or every client shares one bucket and anyone can use up the 8 login attempts
  every 15 minutes and lock the master out.
- Without Redis and with several API processes, each process counts on its own.
- In Redis, `SET NX EX` and `INCR` go in one transaction (`RateLimiter.allow`,
  `queue.go:redisQueue.Allow`), so a key cannot be left without an expiry
  (item #18).

### 3.7 The collector (`collector/`)

What it reads and never reads is listed in docs/privacy.md. Free text from
event messages is scrubbed (`PCDoctorCollector.psm1:Protect-PCDoctorText`), and
CI checks real output for the computer name, user name and serial numbers
(`collector/tests/Invoke-IntegrationTest.ps1`).

| Entry point | Threats | Mitigation that exists | Still open |
|---|---|---|---|
| Running it (`PCDoctor.cmd` -> `Collect-PCDoctor.ps1`) | A tampered script runs as administrator | Read-only by design, apart from the temperature driver (rows below, item #21); open source and short. | `PCDoctor.cmd` asks for administrator rights and runs PowerShell with `-ExecutionPolicy Bypass`, so whatever is in the folder runs elevated. Nothing checks that the folder is the published one (section 5). |
| PresentMon (bundled in `tools/`; `Get-Tools.ps1`, `Find-PCDoctorPresentMon`) | A swapped `PresentMon*.exe` run as administrator; a download made by the checked PC | The zip carries the pinned PresentMon (3.4). A copy without it (a git checkout) fetches it at the first capture: `Collect-PCDoctor.ps1` calls `Get-Tools.ps1`, which downloads over HTTPS from github.com with a 60-second timeout, checks the SHA-256 against the pinned value **and** that the file has a valid Authenticode signature from Intel Corporation, and deletes it otherwise. `-NoDownload` turns the fetch off. At run time `Find-PCDoctorPresentMon` and `Find-PCDoctorNvidiaSmi` run only a file with a valid Intel / NVIDIA signature and skip the `PATH` when elevated (item #2). | The run-time check is the signature only, not the pinned hash: a different Intel-signed PresentMon build placed in `tools/` would run. The automatic fetch is a network request from the checked PC, made while elevated; it sends nothing about the PC, but GitHub sees its IP address. The bundled file, the fetch and the load check have not been run on Windows yet. Was (fixed, item #2): any `PresentMon*.exe` in `tools/` ran without a check, with a `PATH` fallback. |
| Temperature tools (`tools/PawnIO_setup.exe`, `tools/lhm/*.dll`, `temperature-tools.json`; `Get-PCDoctorTemperatureTools`) | A swapped installer or library run as administrator | The zip carries them and the release attests them. `temperature-tools.json` pins the SHA-256 of the installer and of every library; `Get-PCDoctorTemperatureTools` checks each again before use, and the installer must also carry namazso's signature. Any mismatch and none of them is used (a warning says so). | The pins sit beside the files, so someone who can change the zip can change both (section 5). Checked on GitHub's Windows runner (2026-11-24); not yet on the owner's PC. |
| PawnIO kernel driver (`Install-PCDoctorPawnIO`; item #21) | A driver loaded into the kernel by a capture; a driver left behind | Asked first (default no; `-InstallTemperatureDriver` is the explicit switch, `-NoTemperatureDriver` never offers it). If PawnIO was already installed it is used and left alone. Removed in a `finally` (also on Ctrl+C), then checked: PawnIO's uninstaller, `pnputil /remove-device`, `pnputil /delete-driver /uninstall`, `sc delete`. A marker in ProgramData lets the next run as administrator remove it. | While it is loaded, a bug or vulnerability in the driver affects the PC. If the PC loses power or the window is closed mid-capture, it stays until the next run as administrator (or a manual uninstall). |
| `-UploadUrl` (`Send-PCDoctorRun`) | The run read or changed in transit; a hostile server | The server treats it as an untrusted upload (3.1). The answer is only displayed. `Get-PCDoctorResultLink` builds the link only from an http(s) server address plus a `share_key` of 16-128 URL-safe characters or a 32-character run id; anything else gives no link. When the collector runs as administrator it prints the link and does not open a browser; otherwise it opens it only in an interactive session (item #12). | Plain HTTP in LAN mode (the dashboard's own hint is `PCDoctor.cmd -UploadUrl http://...`). Was (fixed, item #12): the link was built from the server's `share_key` without a format check and opened from the elevated process, so the browser could start with administrator rights. |
| LibreHardwareMonitor at `http://localhost:8085` (`Get-PCDoctorLhmSensors`) | A local program serving fake sensor data | Data only; parsed into numbers. | Fake data gives a wrong diagnosis (no security impact beyond that). |

### 3.8 Deployment (`docker-compose*.yml`, `deploy/`)

| Item | Exists | Still open |
|---|---|---|
| Exposure | Compose binds nginx to `127.0.0.1` unless `PCDOCTOR_BIND` is set; Postgres and Redis are not published; the scale add-ons bind to `127.0.0.1`. Terraform opens 80/443 to all, SSH and 6443 to `admin_cidr` only, encrypted disk, IMDSv2. k8s: HTTPS only, cert-manager, security headers, `runAsNonRoot`, dropped capabilities, `readOnlyRootFilesystem` on the upload service. | Never applied to a real cluster or AWS account. The NetworkPolicy (`deploy/k8s/network.yaml`, item #10) covers only PostgreSQL and Redis, has not been applied either, and there is no default-deny for the other pods. LAN mode is plain HTTP by design. (The out-of-date LAN warning in `Start-PCDoctor.ps1` was fixed on 2026-11-14.) |
| Default secrets | `.env` is git-ignored; k8s reads the `pcdoctor-secrets` Secret, created by hand. | `POSTGRES_PASSWORD` still defaults to `pcdoctor` in both Compose files (the database is not published). The setup code also shows in `docker compose logs`. Was (fixed, item #14): the scale stack defaulted `GRAFANA_PASSWORD` and `PCDOCTOR_METRICS_TOKEN`; Redis, Grafana and metrics secrets must now be set (Compose stops without them). |
| Supply chain | `package-lock.json`, `go.sum`; `api/requirements.lock` (made by `api/lock.py`, installed by `api/Dockerfile` with `pip install --require-hashes`); base images in the three Dockerfiles and images in `docker-compose*.yml` pinned by digest; every GitHub Action in `.github/workflows/*.yml` pinned by commit SHA (item #15); `Get-Tools.ps1` pins PresentMon, and the release workflow and `api/Dockerfile` fetch it with `collector_build.py fetch-presentmon`, which keeps it only if its SHA-256 is the pinned one; `.github/dependabot.yml` exists; containers run as non-root (`api/Dockerfile`, `upload-service/Dockerfile`). | The build backend for this repository's own two packages (`setuptools>=77` in `api/pyproject.toml` and `workers/pyproject.toml`) is fetched without a hash when `api/Dockerfile` builds them. The images in `deploy/k8s` (`postgres:16-alpine`, `redis:7-alpine`, Prometheus, Grafana) are pinned by tag, not digest. Was (fixed, item #15): Python dependencies were lower bounds with no lock file; base images and GitHub Actions were pinned by tag. `.github/workflows/security.yml` (added 2026-11-14) runs pip-audit, npm audit, govulncheck and gitleaks on every push and weekly; it found Go 1.26.0 standard-library vulnerabilities, fixed by pinning `toolchain go1.26.11`. |

### 3.9 Added after the first version: live sessions and build comparison

| Entry point | Threat | Exists | Still open |
|---|---|---|---|
| `POST /api/live` and the Live page (`routers/live.py`) | A guest opening sessions or watching one | Master only (in the route lists of `api/tests/test_auth.py`). | - |
| `POST /api/live/{token}/samples` (`routers/live.py:add_samples`, `services/live.py:parse_batch`) | Flooding memory or Redis; junk numbers; reading data back | The token is random and only its hash is kept; it can only add. A batch is capped at 512 KB and 5,000 lines, read in chunks so a lying `Content-Length` does not help; each line must be a known type with finite numbers in range and sensor names matching `^[a-z][a-z0-9_]{0,39}$`; 600 batches a minute per token; each session keeps only the newest 6,000 frames and 600 sensor rows and expires after 6 hours; at most 20 sessions. The answer is only counts. | The per-token limit is counted in this process even when Redis holds the buffer. Plain HTTP on the LAN, as elsewhere. |
| `--live-url` in `collector-rs` (`src/live.rs`) | Run data sent in the clear across the internet, or redirected | `check_url` refuses `http://` except to loopback and private addresses; redirects are not followed; only frame times and sensor values are sent. | - |
| `GET /api/runs/{id}/compare` (`services/compare.py`) | SQL injection through DuckDB | Master only; the only values in the query are bound parameters, and column names come from a fixed list in the code. | - |

## 4. Open items, ranked

Ranked by how likely and how bad, for the set-ups people actually use (local
and LAN first, cloud second). Items marked **Fixed** were fixed on 2026-11-14,
each with a test; they stay in the table so the history is visible.

| # | Item | Where | Set-up | Why this rank |
|---|---|---|---|---|
| 1 | **Fixed in part (2026-11-14):** the collector zip is built reproducibly (`services/collector_build.py`) and `.github/workflows/release-collector.yml` attests and publishes it with its SHA-256; the server serves the same bytes and shows the hash; `collector/README.md` says how to check. Since 2026-11-17 the zip also contains Intel's PresentMon, unmodified, so the attestation covers it too: the build (`--require-presentmon` in the release workflow) fails unless the file's SHA-256 is the one pinned in `Get-Tools.ps1`. Still open: in LAN mode the download is plain HTTP, and only someone who checks is protected (section 5); the zip now carries third-party executables that run as administrator, so a wrong pin would ship in an attested release. Since 2026-11-24 it also carries PawnIO's installer (`tools/PawnIO_setup.exe`) and 14 LibreHardwareMonitorLib libraries (`tools/lhm`), each pinned by SHA-256 in `temperature-tools.json`, so the attestation covers them too (item #21). Was: The collector is fetched and run with no integrity check, as administrator; in LAN mode it travels over plain HTTP | `routers/intake.py:collector_zip`, `collector/PCDoctor.cmd` | LAN | Someone on the LAN gets admin code execution on every PC checked. Section 5 is the plan. |
| 2 | **Fixed:** `Find-PCDoctorPresentMon` and `Find-PCDoctorNvidiaSmi` run only a file with a valid Intel / NVIDIA signature (`Test-PCDoctorSignedBy`) and skip the PATH when elevated; the Rust collector does the same for nvidia-smi and, since 2026-11-24, for `--start-presentmon` (`collector-rs/src/signature.rs`); the server and the release pack only the pinned PresentMon, inside the collector zip (the separate download `/api/collector/presentmon.zip` was removed on 2026-11-17). A copy without it fetches it on the checked PC through `Get-Tools.ps1` (pinned SHA-256 and Intel signature; `-NoDownload` turns it off) - one more network download, guarded the same way. Since 2026-11-24 the other third-party files run as administrator are checked differently: the PawnIO installer must match its pinned SHA-256 **and** carry namazso's signature, and each LibreHardwareMonitorLib library must match its pinned SHA-256, all before use (`Get-PCDoctorTemperatureTools`); any mismatch and none is used. Residual: the run-time check for PresentMon is the signature, not the hash. Was: `PresentMon*.exe` is not re-verified, neither when the server zips it nor when the collector runs it; PATH fallback for `PresentMon.exe` and `nvidia-smi.exe` | `intake.py:collector_zip`, `PCDoctorCollector.psm1:Find-PCDoctorPresentMon`, `Find-PCDoctorNvidiaSmi` | All | Same outcome as #1 by a different door; easy to fix (check hash + signature before `Start-Process`, drop the PATH fallback when elevated). |
| 3 | **Mitigated (2026-11-15):** [lan-https.md](lan-https.md) puts HTTPS with a local certificate authority in front on a shared network; plain HTTP stays the default for a network you control. Was: Plain HTTP in LAN mode: session cookie, share keys, photo tokens and run data in clear | `Start-PCDoctor.ps1 -Lan`, `docker-compose.yml` | LAN | Documented and deliberate, but a LAN attacker can take the master's session. |
| 4 | **Fixed:** `PCDOCTOR_PROXY_HOPS` (2 in `deploy/k8s/app.yaml`) skips exactly our own proxies in `deps.py:client_key`; `test_the_rate_limit_address_skips_only_our_own_proxies`. Was: Rate-limit key is the proxy's address in k8s (Traefik -> nginx -> API) | `deps.py:client_key` with `web/nginx.conf` | Cloud | **Bug.** Anyone can lock the master out of password sign-in and use up guest uploads for everyone. Fix with nginx `set_real_ip_from` + `real_ip_header`, or count back a configured number of hops. |
| 5 | **Fixed:** `CleanRun` copies each file straight into the new zip; a 300 MB bomb now allocates about 1 MB (`TestZipBombIsNotHeldInMemoryUnpacked`). Was: Upload service keeps up to 1 GB of unpacked files in memory; pod limit is 768 Mi | `upload-service/archive.go:CleanRun`, `deploy/k8s/app.yaml` | Cloud, scale stack | **Bug.** A small zip bomb OOM-kills the upload service. Stream to a temp file as the Python side does, or lower the default limit well under the container limit. |
| 6 | **Fixed:** unpacking, re-encoding and OCR run on a worker thread (`run_in_threadpool`). Was: Blocking work inside `async def` routes: one upload or photo stalls the whole API | `routers/runs.py:upload_run`, `routers/inbox.py:send_photo`, `routers/intake.py:read_photo` | All | **Bug** (availability). Make them `def` after reading the body, or use `run_in_threadpool` for `ingest`/OCR. |
| 7 | **Fixed:** a run has one key per guest upload (`share_keys` table), each with its uploader's own label; `test_a_second_upload_of_the_same_file_does_not_break_the_first_link`. Was: A duplicate upload replaces the share key; the earlier link dies and the re-uploader sees the run's label | `routers/runs.py:upload_run`, `worker.py:process_job` | All | **Bug** (untested behaviour). Keep the existing share hash, or store several keys per run. |
| 8 | **Fixed:** `notify.escape` escapes the headline like the bot does; tested in `test_oauth.py`. Was: Discord webhook text is not escaped; a guest can post masked links in the master's channel | `services/notify.py:message_for` | When the webhook is set | Phishing in a trusted channel. Reuse the bot's `escape`. |
| 9 | **Fixed:** set-up attempts are rate-limited, the code is 64 bits, and a partial unique index allows one master. Was: `/api/auth/setup` has no rate limit; two simultaneous setups can make two masters | `routers/auth.py:setup` | LAN/cloud before setup | Small window, but the fix is one line (`login_attempts.allow`) plus a lock or unique check. |
| 10 | **Fixed:** Redis requires a password in the scale stack and k3s (checked in CI), and `deploy/k8s/network.yaml` lets only the app's own pods reach Redis and PostgreSQL (schema-checked in CI, not applied to a cluster). Was: Redis without a password; no NetworkPolicy | `docker-compose.scale.yml`, `deploy/k8s/data.yaml` | Scale/cloud | Needs a foothold inside the network first. |
| 11 | **Fixed:** "Sign out everywhere" and a master password change (Account page); the master can revoke a single private run link or phone photo link (run page, Photos page). Was: Session and link management: 30-day sessions, no revoke, no password change/reset; photo links and share keys cannot be revoked | `services/auth.py`, `routers/inbox.py`, `routers/runs.py` | All | Limits recovery after a leak. |
| 12 | **Fixed:** `Get-PCDoctorResultLink` builds the link only from well-formed parts, and an elevated collector prints it instead of opening it. Was: Collector opens the browser from the elevated process; `share_key` from the server is not checked | `collector/Collect-PCDoctor.ps1` (upload block) | All | Elevated browser; validate the key with `^[A-Za-z0-9_-]{16,128}$` and open the link de-elevated (or just print it when elevated). |
| 13 | **Fixed:** a strict CSP, `Referrer-Policy: no-referrer`, nosniff, `X-Frame-Options: DENY` from the API and nginx (`web/security-headers.conf`), checked in a browser and in CI. Was: No security headers or CSP in the Compose nginx | `web/nginx.conf` | Local/LAN | React escaping covers most of it; `SameSite=Lax` covers framing with a session. Note that "same site" ignores the port: other services on the same host (Grafana on :3000 in the scale stack) count as same-site. |
| 14 | **Fixed:** the scale stack has no default Redis, Grafana or metrics secrets (Compose stops without them) and the API refuses a short or well-known metrics token. Was: Default passwords and metrics token | `docker-compose*.yml` | LAN | Postgres is not published; the metrics token is reachable through nginx. |
| 15 | **Fixed (one small gap):** the API image installs from `api/requirements.lock` with `pip --require-hashes` (pip-audit checks the locked versions weekly; `api/lock.py` refreshes them); every base and Compose image is pinned by digest and every GitHub Action by commit, which Dependabot updates. Still loose: the build backend for this repository's own two packages is fetched without a hash. Was: Python dependencies unpinned; Actions and images pinned by tag | `api/pyproject.toml`, `.github/workflows/*.yml`, Dockerfiles | Build | Supply-chain drift; add a lock file and the planned `security.yml`. |
| 16 | **Fixed:** only JPEG, PNG and WebP are decoded and the pixel-limit warning is an error (`photo.open_photo`). Was: Pillow accepts any format; 40-80 M pixel images are decoded with only a warning | `services/photo.py:to_jpeg`, `read_text` | Behind a photo link or master | Pass `formats=("JPEG", "PNG", "WEBP")` to `Image.open` and turn the warning into an error. |
| 17 | **Fixed:** sign-in is off unless the public address is HTTPS (or local/private HTTP) (`oauth.public_url_ok`). Was: `PCDOCTOR_PUBLIC_URL` may be `http://` for a non-local host | `services/oauth.py:configured` | Cloud | Flow cookie without `Secure`; docs say it must be HTTPS. |
| 18 | **Fixed:** `SET NX EX` and `INCR` in one MULTI/EXEC, in Python and Go. Was: Redis `INCR`/`EXPIRE` not atomic | `services/auth.py:RateLimiter.allow`, `upload-service/queue.go:redisQueue.Allow` | Scale | Rare permanent block of one key; use `SET NX EX` + `INCR` in a pipeline or a Lua script. |
| 19 | **Fixed:** the API (`pcdoctor_api/logs.py`) and nginx (a `map` and a redacted log format) replace keys and tokens in the access log with placeholders. Was: Share keys and photo tokens in access logs | nginx, uvicorn | All | Logs are on the master's own server. |
| 20 | **Fixed:** the launcher now says it uses plain HTTP. Was: Out-of-date LAN warning in the launcher | `Start-PCDoctor.ps1` | LAN | Wrong text, not a hole. |
| 21 | **Open, accepted by the owner (2026-11-17), measured 2026-11-24:** a capture may load a kernel driver (PawnIO 2.2.0.0 by namazso) to read CPU temperature. Mitigations: only after a yes (default no) or `-InstallTemperatureDriver`; the installer's SHA-256 is pinned and it must carry namazso's signature; the installed PawnIO.sys was signed by "Microsoft Windows Hardware Compatibility Publisher" on GitHub's Windows Server 2025 runner, loaded with the vulnerable-driver blocklist on, and Microsoft Defender reported nothing; removed after the capture (the collector also removes the package and service PawnIO's uninstaller leaves, and checks). Residual: a bug or vulnerability in the driver affects the PC while it is loaded; the driver stays if the PC loses power mid-capture, until the next run as administrator. Not yet known: a real CPU's reading (the runner is a VM), Memory Integrity (HVCI) on, anti-cheat games | `collector/PCDoctorCollector.psm1` (CPU temperature driver), `collector/Collect-PCDoctor.ps1`, `collector/temperature-tools.json` | All | A kernel driver is more access than anything else the collector does, but it is short-lived, asked for, and checked. |

## 5. Plan: signing the collector zip without a paid certificate

**Status: built on 2026-11-14 and changed on 2026-11-17; not run yet.** No
`collector-v*` tag exists, so there is no release, no attestation and no
published hash. The workflow runs on such a tag, or by hand ("Run workflow"
builds and attests without publishing a release). The steps below are what `.github/workflows/release-collector.yml` and
`api/pcdoctor_api/services/collector_build.py` do. One thing changed on
2026-11-17: PresentMon, first a separate download, is now inside the zip
(steps 1 and 4 below say how), so one download is all a PC needs.

The goal is that a technician can prove the collector they are about to run as
administrator is exactly what this repository's release workflow built from a
known commit. GitHub artifact attestations do this for free on a public
repository: the workflow signs a statement "this file, with this SHA-256, was
built by this workflow at this commit" with a short-lived Sigstore certificate
tied to the workflow's identity, and anyone can check it with `gh`.

### Steps

1. **Build the zip reproducibly.** One small script (shared with the server)
   writes the files in `COLLECTOR_FILES` in a fixed order, with a fixed
   timestamp and CRLF line endings for `PCDoctor.cmd`, into
   `PCDoctor-collector.zip`. PresentMon is in the zip, byte for byte as
   Intel published it, as `tools/PresentMon-2.6.0-x64.exe`, with Intel's
   licence (`PresentMon-LICENSE.txt`). Its binary is not in git: the
   workflow fetches it (`collector_build.py fetch-presentmon`), keeps it
   only if its SHA-256 is the one pinned in `Get-Tools.ps1`, and the build
   (`--require-presentmon`) checks that hash again and fails without it.
2. **Release workflow** (`.github/workflows/release-collector.yml`), run on a
   tag such as `collector-v1.2.0`:

   ```yaml
   permissions:
     contents: write      # create the release
     id-token: write      # get the Sigstore certificate
     attestations: write  # store the attestation
   jobs:
     release:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@<commit sha>
         - run: python3 api/pcdoctor_api/services/collector_build.py fetch-presentmon collector
         - run: >-
             python3 api/pcdoctor_api/services/collector_build.py --require-presentmon
             collector dist/PCDoctor-collector.zip
         - run: cd dist && sha256sum PCDoctor-collector.zip > PCDoctor-collector.zip.sha256
         - uses: actions/attest-build-provenance@<commit sha>   # v2 or current major
           with:
             subject-path: dist/PCDoctor-collector.zip
         - run: gh release create "$GITHUB_REF_NAME" dist/* --verify-tag
           env:
             GH_TOKEN: ${{ github.token }}
   ```

   Pin actions to commit SHAs in this workflow; it is the one that signs.
3. **Publish the SHA-256** in the release notes and as
   `PCDoctor-collector.zip.sha256` next to the zip.
4. **Serve the same bytes from PC Doctor.** Today `GET /api/collector.zip`
   rebuilds the zip on every request (new timestamps, optional PresentMon), so
   its hash never matches anything. Change it to serve the released zip when
   one is in the collector folder (or build with the same reproducible script),
   and show its SHA-256 on the "Get the collector" page. (Done. PresentMon
   was at first a separate download; it is now packed inside, pinned by
   SHA-256, and the API Docker image fetches it at build time so the server's
   zip matches the release. A server without the pinned file serves the
   scripts alone - a different hash - and the page says so.)
5. **Document how to check** (in `collector/README.md`):

   ```bash
   gh attestation verify PCDoctor-collector.zip --repo HU3YN/PC-Doctor
   ```

   This checks the signature, that the signer was a workflow in
   `HU3YN/PC-Doctor`, and that the digest matches the file. On a Windows PC
   without `gh`, compare the hash with the one on the GitHub release page
   (opened over HTTPS, not from the PC Doctor server):

   ```powershell
   Get-FileHash .\PCDoctor-collector.zip -Algorithm SHA256
   ```

### What this does not do

- **Windows SmartScreen and "Mark of the Web" warnings stay.** They look for
  an Authenticode signature from a certificate with reputation; an attestation
  is not one.
- **The `.ps1`, `.psm1` and `.cmd` files are not Authenticode-signed.** And
  `PCDoctor.cmd` runs PowerShell with `-ExecutionPolicy Bypass`, so a
  signature on the scripts would not be enforced anyway.
- **It only helps someone who checks.** A user who downloads over plain HTTP
  on a LAN and runs the zip without comparing the hash is exactly as exposed
  as today. A hash shown by the same PC Doctor server over plain HTTP proves
  nothing against someone who can change that page; compare with GitHub.
- **It says where the file came from, not that it is safe.** A bad commit
  that passes the workflow gets a valid attestation.
- **It does not vouch for PresentMon itself, and does not cover
  LibreHardwareMonitor.** The attestation covers the PresentMon file in the
  zip only in the sense that it is the file this repository pinned. That it
  is Intel's is checked separately: by the pinned SHA-256 at build time and
  by Intel's signature each time the collector runs it (item #2). A copy the
  collector fetches itself (a git checkout) is covered by `Get-Tools.ps1`,
  not by the attestation. LibreHardwareMonitor is the user's own install.
- **Private repositories** need GitHub Enterprise Cloud for attestations; this
  plan assumes the repository stays public.
