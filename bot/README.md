# bot (Phase 4)

A Discord bot with one slash command:

```
/diagnose file:<attachment> [label] [public]
```

Attach the `.zip` the collector made (or a PresentMon `.csv`). The bot uploads
it to PC Doctor as a guest and replies with the verdict, the headline, the
build (CPU / GPU / RAM), the top three findings with the first thing to check
for each, and the private link to the full report.

**Status:** the rules, the upload client and the reply text are tested
(`tests/`). The Discord connection itself has **not** been tried against a
real server yet - see [What is not tested](#what-is-not-tested).

## The rules it follows

- **Private by default.** The reply is shown only to the person who ran the
  command, because it holds the private link. With `public:true` the channel
  sees a summary **without** the link, and the link is sent to the requester
  alone in a second, private message.
- **Approved servers only.** `DISCORD_GUILD_IDS` lists the servers whose
  moderators agreed to have the bot. The command is registered only there. If
  the bot is added anywhere else it leaves at once. With no IDs it will not start.
- **Only Discord's own files.** An attachment is downloaded only over https
  from `cdn.discordapp.com` or `media.discordapp.net`, only if it is named
  `.zip` or `.csv`, and only up to the size cap (200 MB by default). The size
  is checked before the download and counted again while it streams.
  Redirects are not followed.
- **It cannot ping.** Every message is sent with mentions switched off, text
  that came from the upload (the label, part names, findings) is escaped, and
  replies are cut to Discord's 2000 characters.
- **Minimum access.** The only gateway intent is `guilds`. No message content,
  no member list. The bot reads nothing but the commands sent to it.
- **Quiet logs.** The token comes from `DISCORD_BOT_TOKEN` and is never
  logged. User names, user IDs, file names, labels and links are not logged
  either. The file is sent to the API under a fixed name, not the person's own.
- **Cooldown.** One `/diagnose` per person per minute (configurable).

## Settings

Copy `.env.example` to `.env` (git ignores it) and fill it in.

| Variable | Needed | Meaning |
|---|---|---|
| `DISCORD_BOT_TOKEN` | yes | The bot token. Keep it out of the repo. |
| `DISCORD_GUILD_IDS` | yes | Approved server IDs, comma separated. |
| `PCDOCTOR_URL` | yes | Where the bot reaches the API, e.g. `http://localhost:8080`. |
| `PCDOCTOR_PUBLIC_URL` | no | The address people open in a browser, used for the link. Defaults to `PCDOCTOR_URL`. |
| `PCDOCTOR_MAX_UPLOAD_MB` | no | Download cap in MB. Default 200 (the API's own default). |
| `PCDOCTOR_COOLDOWN_SECONDS` | no | Wait between uses per person. Default 60. |

The bot does not read `.env` by itself; load it into the environment (see below).

## Create the Discord application

1. Open the [Discord Developer Portal](https://discord.com/developers/applications),
   **New Application**, give it a name.
2. **Bot** tab: **Reset Token**, copy the token into `.env` as
   `DISCORD_BOT_TOKEN`. Leave all three **Privileged Gateway Intents** off.
   Turn **Public Bot** off so only you can add it to servers.
3. **Installation** tab: install to a **Guild** only, scopes `bot` and
   `applications.commands`. No bot permissions are needed (replies to a slash
   command do not need any).
4. Get the moderators' approval for the server. Then, in Discord, turn on
   **Settings > Advanced > Developer Mode**, right-click the server,
   **Copy Server ID**, and add it to `DISCORD_GUILD_IDS`.
5. Open the install link from step 3 and add the bot to that server.
6. Start the bot. `/diagnose` appears in that server straight away. (If the
   bot was started before it was added, restart it so the command registers.)

## Run it

```bash
cd bot
python -m venv .venv
.venv/bin/pip install -e .          # Windows: .venv\Scripts\pip install -e .
set -a; . ./.env; set +a            # load the settings (bash)
.venv/bin/python -m pcdoctor_bot
```

PC Doctor itself must be running and reachable at `PCDOCTOR_URL`. The private
link is only useful to people who can reach `PCDOCTOR_PUBLIC_URL`, so for a
public server that means the hosted (HTTPS) deployment.

Note: the API allows 30 guest uploads an hour per address, and every upload
through the bot comes from the bot's address. A busy server can reach that;
people then get a "try again in an hour" reply.

## Test and lint

```bash
cd bot
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

The tests need no token and no network: HTTP calls go to a mock transport.

## Layout

| File | What it holds |
|---|---|
| `pcdoctor_bot/core.py` | Everything that does not need Discord: settings, attachment rules, the download, the API client, the cooldown, the reply text. |
| `pcdoctor_bot/__main__.py` | The thin discord.py part: the client, the command, leaving servers that are not approved. |
| `tests/test_core.py` | Tests for `core.py`. |

## What is not tested

- Connecting to Discord, registering the command, and the command handler in
  `__main__.py` (private/public replies, the second private message, leaving a
  server). These need a real token and a test server.
- How Discord draws the escaped text. The escaping follows Discord's markdown
  rules, but has not been looked at in a real client.
- A real upload to a running PC Doctor API. The API's answers are mocked from
  its schema.
