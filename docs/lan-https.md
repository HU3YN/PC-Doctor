# HTTPS on your own network

`Start-PCDoctor.cmd -Lan` serves plain HTTP: anyone else on the same network
could read the sign-in cookie, private links and run data as they travel
(threat model item #3). On a network you control alone that may be fine. On
a shop or shared network, put HTTPS in front with a certificate from your own
small certificate authority. This page shows one way, with
[Caddy](https://caddyserver.com/) (free, one program).

**Not verified:** written from the code and Caddy's documentation; it has not
been tried end to end on a real network. Expect to adjust it.

## 1. Run PC Doctor for this computer only, behind the proxy

Start PC Doctor **without** `-Lan`, so only Caddy (on the same computer) can
reach it, and tell it a proxy is in front so rate limits count the real
caller. In `.env`:

```
PCDOCTOR_TRUST_PROXY=true
# Python route (Start-PCDoctor without Docker): Caddy is the only proxy.
PCDOCTOR_PROXY_HOPS=1
# Docker Compose: Caddy, then the stack's own nginx.
# PCDOCTOR_PROXY_HOPS=2
```

Without `PCDOCTOR_TRUST_PROXY`, every visitor looks like Caddy's own address
and shares one rate limit - anyone could lock you out of signing in.

## 2. Start Caddy with its own certificate authority

With the master's network address (Start-PCDoctor prints it, e.g.
`192.168.1.20`):

```powershell
caddy reverse-proxy --from https://192.168.1.20:8443 --to localhost:8080 --internal-certs
```

Caddy creates a local certificate authority the first time and signs a
certificate for that address. PC Doctor sees `X-Forwarded-Proto: https`, so
it marks the sign-in cookie `Secure`.

Allow port 8443 through Windows Firewall when asked.

## 3. Make each device trust that certificate authority

Browsers warn about a certificate they do not know. Trust Caddy's root
certificate once on each device that will use PC Doctor:

- **The master itself:** `caddy trust`.
- **Other PCs and phones:** copy the root certificate - on Windows it is
  `%AppData%\Caddy\pki\authorities\local\root.crt` - and install it as a
  trusted root (Windows: double-click it, "Install Certificate", Local
  Machine, "Trusted Root Certification Authorities"; Android and iOS: open
  the file and enable it in the certificate settings).

The root certificate's private key stays on the master; keep that folder
private. Anyone with it could impersonate PC Doctor to every device that
trusts it.

## 4. Use the HTTPS address

Open `https://192.168.1.20:8443` instead of the `http://` one. For the
collector's upload, the PC being checked must trust the root too:

```
PCDoctor.cmd -UploadUrl https://192.168.1.20:8443
```

If you would rather not install the root on customers' PCs, use the USB route
instead: the collector saves the run on the stick and you drop it on the
dashboard yourself.
