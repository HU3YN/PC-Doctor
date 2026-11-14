# Sign-in with Discord or Google (optional)

Off unless you set it up. The master's password sign-in always keeps working.

**Not tried against real Discord or Google yet** - only against a stand-in in
the tests (`api/tests/test_oauth.py`). The first real sign-in is the test.

## What it does

- The master can **link** a Discord or Google account on the **Account** page
  and then sign in with it.
- With `PCDOCTOR_OAUTH_SIGNUP=true`, anyone who signs in gets a **member**
  account. A member sees only the runs they uploaded - never the work log,
  photos, or anyone else's runs. Leave it `false` to allow nobody new.
- Only the provider's id for the person is stored. No name, email or picture
  is asked for (Discord scope `identify`, Google scope `openid`).

## Set it up

Put these in `.env` (never commit it):

```
PCDOCTOR_PUBLIC_URL=https://pcdoctor.example.com
PCDOCTOR_DISCORD_CLIENT_ID=...
PCDOCTOR_DISCORD_CLIENT_SECRET=...
PCDOCTOR_GOOGLE_CLIENT_ID=...
PCDOCTOR_GOOGLE_CLIENT_SECRET=...
PCDOCTOR_OAUTH_SIGNUP=false
```

`PCDOCTOR_PUBLIC_URL` is the address people type to reach PC Doctor. To try it
on your own computer use `http://localhost:8080`; anywhere else it must be
`https://`.

- **Discord:** https://discord.com/developers/applications > New Application >
  OAuth2. Copy the client id and secret. Add the redirect
  `<PUBLIC_URL>/api/auth/oauth/discord/callback`.
- **Google:** https://console.cloud.google.com > APIs & Services > Credentials >
  Create OAuth client ID (Web application). Add the redirect
  `<PUBLIC_URL>/api/auth/oauth/google/callback`.

Restart PC Doctor. The buttons appear on the sign-in page and the Account page.

## How the flow works

`api/pcdoctor_api/services/oauth.py` explains the five steps (state, PKCE
verifier, code, token, id) at the top of the file. It is written by hand with
no OAuth library so every step can be read.
