# Tier 2 hardening: exposed VPS deployment

This checklist hardens Neva for an always-on VPS that will be reached from the internet.
Follow it in order, not in parallel. Each item names what to do, how to verify, and what it
protects. Do not expose the gateway without completing every step; an incomplete checklist is
worse than no checklist because it can read as "we thought about this."

**Prerequisites:** a 2GB+ VPS, Ubuntu 24.04 LTS or similar Linux (stock BSD/macOS tooling,
no Homebrew). Swap configured before first OOM (add it now: `dd if=/dev/zero of=/swapfile
bs=1G count=4 && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile`, then
`echo /swapfile none swap sw 0 0 >> /etc/fstab`). Neva installed, doctor running, all core
jobs enabled and firing (see docs/03-scheduled-jobs.md).

## 1. Lock gateway.auth before any proxy

**What:** Set a strong shared secret in the gateway's config so OpenClaw can authenticate
proxy requests.

**Steps:**
`gateway.auth` is an object, not a plain string - `openclaw config set gateway.auth "<string>"`
fails with `Invalid input: expected object, received string` (verified against a real
install, 2026-08-01). Set the two fields the schema actually wants instead:
```
openclaw config set gateway.auth.mode token
openclaw config set gateway.auth.token "$(openssl rand -hex 16)"
```
Then restart the gateway - both commands print "Restart the gateway to apply."
Verify: `openclaw security audit --json` no longer lists `gateway.loopback_no_auth`, and
`python3 -c "import json; c=json.load(open('$HOME/.openclaw/openclaw.json')); print(c.get('gateway',{}).get('auth'))"` shows `{"mode": "token", "token": "..."}`.

**Why:** The gateway will accept authenticated requests from a proxy. Without this, anyone
who knows the VPS IP can connect directly to the loopback gateway (if they have shell access,
which they might, via a different compromise). This protects only against direct HTTP
connections to the gateway itself; a compromised machine remains fully compromised. If your
proxy ever becomes the weak point, the gateway auth is not sufficient. Read docs/09-security.md
again before you rely on auth alone.

**Protects against:** Direct gateway access from a compromised machine's processes that lack
shell privileges.

## 2. Gateway becomes a systemd service

**What:** Configure the gateway to run as a systemd service so it restarts on failure and is
visible to your OS lifecycle.

**Steps:**
Create `/etc/systemd/system/neva-gateway.service`:
```
[Unit]
Description=Neva OpenClaw Gateway
After=network.target

[Service]
Type=simple
User=<your-user>
Environment="PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ExecStart=/usr/local/bin/openclaw gateway
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```
Replace `<your-user>` with the non-root user running Neva (the one who owns `$HOME/.openclaw`).

Enable and start: `sudo systemctl enable --now neva-gateway.service`

Verify: `systemctl status neva-gateway.service` shows "active (running)". After five minutes,
`journalctl -u neva-gateway.service -n 20` shows no startup errors.

**Why:** A process that crashes silently and never restarts means the agent is unreachable
when the VPS reboots or when the gateway hits an edge case. The systemd journal is also
auditable; if something goes wrong later, you have the log.

**Protects against:** Gateway crashes going unnoticed until you try to talk to the agent and
get no response for hours.

## 3. Reverse proxy in front of the gateway

**What:** Set up a reverse proxy (nginx recommended; Apache with mod_proxy works too) that
sits between the internet and the loopback gateway, forwards requests to the gateway at
127.0.0.1:18789, and validates the gateway.auth on every request.

**Steps (nginx):**
Create `/etc/nginx/sites-available/neva`:
```
upstream neva_gateway {
    server 127.0.0.1:18789;
}

server {
    listen 80;
    server_name <your-domain>;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name <your-domain>;

    ssl_certificate /etc/letsencrypt/live/<your-domain>/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/<your-domain>/privkey.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    location / {
        proxy_pass http://neva_gateway;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Gateway-Auth "<gateway.auth-string>";
        proxy_read_timeout 60s;
        proxy_connect_timeout 10s;
    }
}
```
Replace `<your-domain>` with your actual domain and `<gateway.auth-string>` with the secret
from step 1 (exact string, no escaping). Set up DNS first; `certbot certonly --nginx -d
<your-domain>` will fetch the cert.

Enable: `sudo ln -s /etc/nginx/sites-available/neva /etc/nginx/sites-enabled/neva && sudo
systemctl reload nginx`

Verify: `curl -I https://<your-domain>/` returns HTTP 200. The gateway sees the request:
`journalctl -u neva-gateway.service -n 5 | grep GET`

**Why:** The reverse proxy terminates SSL/TLS (so the gateway does not need its own certs),
normalizes traffic (logs, rate limits, blocks bad requests), and sits between the internet
and your machine. If the proxy is compromised, the gateway is protected by the auth header.
Do not skip the auth header; it is the whole point of this layer.

**Protects against:** Unencrypted HTTP traffic to the gateway, exposure of the gateway's raw
logs, and direct access to the loopback gateway from the internet (if you ever misconfigure
the proxy or leave it running when you intended to stop it).

## 4. Rate limit and DDoS mitigation on the proxy

**What:** Configure nginx to reject the most obvious request floods and malformed input,
reducing the noise on the gateway and avoiding OOM on your VPS.

**Steps:**
Add to the nginx config, inside the `server` block (under the location section):
```
limit_req_zone $binary_remote_addr zone=general:10m rate=10r/s;
limit_req_zone $binary_remote_addr zone=telemetry:10m rate=2r/s;

location / {
    limit_req zone=general burst=20 nodelay;
    proxy_pass http://neva_gateway;
    ...
}

location /api/events {
    limit_req zone=telemetry burst=5 nodelay;
    proxy_pass http://neva_gateway;
    ...
}
```

Reload: `sudo systemctl reload nginx`

Verify: `ab -c 100 -n 1000 https://<your-domain>/` (if you have Apache Bench installed).
Responses should include some HTTP 429 (Too Many Requests) after the burst threshold.

**Why:** A malformed request loop or a bot scanning the endpoint can consume all your RAM
before the gateway even sees it. This stops the worst cases at the edge.

**Protects against:** Request floods that would otherwise OOM the gateway process, forcing
it to restart.

## 5. Telegram token rotation and allowlist audit

**What:** Verify the allowlist is locked to YOUR id only, and rotate the bot token if you
have any doubt about its security.

**Steps:**
Run `doctor`. Look for "telegram locked to your id (allowlist)". If it says "FAIL", follow
the message exactly.

If you want to rotate the token anyway (smart, if anyone else has ever seen it):
- Open Telegram, message @BotFather, send `/mybots`.
- Select your bot, then `/revoke`.
- Confirm. Send `/newbot` and follow the prompts to create a new bot with the same username.
- Copy the new token.
- Run: `openclaw config set channels.telegram.botToken "<new-token>"` (exact token, no leaks).
- Run `doctor` again. It should show "telegram token (getMe 200)".

Verify: `doctor` returns "telegram locked to your id (allowlist)" and "telegram token (getMe 200)".

**Why:** A leaked token is a root compromise of the agent; the token, not the allowlist,
controls whether someone can talk to the bot or redirect its messages. Rotating it closes
any window where it was exposed. The allowlist provides defense-in-depth only.

**Protects against:** Use of the token by anyone who ever saw it before.

## 6. Run the full security audit

**What:** Let OpenClaw and doctor check every hardening step you have taken so far.

**Steps:**
Run: `openclaw security audit --json` and read the output. Look for any findings with
severity "critical" or "high". `openclaw security audit --fix` only applies remediations that
do not require a decision from you (mostly file-permission fixes) - it will report "Fixes: no
changes applied" and leave `gateway.loopback_no_auth` (the finding almost every install
starts with) untouched, because setting a real auth secret is exactly the kind of decision it
will not make silently. If step 1 above is done, that finding is already gone; for anything
else `--fix` reports as unfixed, apply the specific remediation text it prints, then re-run.

Also run: `doctor`. It should return exit 0 with "all clear". Every row should say "ok".

Verify: Both commands report no high/critical findings. `doctor` shows no FAILs.

**Why:** Human-written config can hide mistakes. The automated audit catches what the
checklist might have missed (like an outdated TLS version or a gateway binding that crept
back to 0.0.0.0).

**Protects against:** Configuration drift between what you think you set up and what is
actually running.

## 7. SSH access hardening (independent of Neva)

**What:** Make sure the VPS itself cannot be easily compromised, which would compromise Neva
regardless of any application-level hardening.

**Steps:**
- Disable root login and password auth: edit `/etc/ssh/sshd_config` to set
  `PermitRootLogin no` and `PasswordAuthentication no`.
- Allow only your SSH key: `PubkeyAuthentication yes`, `AuthorizedKeysFile ~/.ssh/authorized_keys`.
- Restrict SSH to a non-standard port (optional, adds noise reduction): `Port 2222`.
- Reload: `sudo systemctl reload ssh`.
- Test in a new terminal before closing the current one.
- Consider `fail2ban` for brute-force protection: `sudo apt install fail2ban`.

Verify: You can still SSH in with your key. Password login is rejected. Your monitoring shows
failed login attempts getting blocked after a few tries.

**Why:** SSH is the most common attack vector on a VPS. Closing it makes every other step
matter more.

**Protects against:** Brute-force login, credential compromise via stolen SSH keys from
other machines, privilege escalation via root.

## 8. Vault sync over SSH only, not plaintext git

**What:** If vault-sync is running and pushing to a remote repo, verify it uses SSH keys,
not HTTPS with hardcoded credentials.

**Steps:**
Run: `cat ~/.local/neva/services/neva-vault-sync.service | grep -i url` (the actual sync job).
The URL should start with `git@` (SSH), not `https://`. If it is HTTPS, the credentials are
either embedded in the URL or in `~/.git-credentials`, both of which are leaks.

If you use vault-sync: generate an SSH key on the VPS (`ssh-keygen -t ed25519 -f ~/.ssh/id_vps
-N ""`), add the public key to your git host, and point vault-sync to the SSH URL instead.

Verify: `vault-sync` runs without prompting for a password or token. `doctor` shows no
warnings about vault sync.

**Why:** Credentials in git URLs get logged in command history and error output. SSH keys
are rotatable and can be locked to a specific machine.

**Protects against:** Credential leaks in process listings or shell history.

## 9. Monitoring and alerting: set up a weekly self-check

**What:** Configure the diag job to run weekly and send you the results, so you know if any
hardening steps silently failed.

**Steps:**
Enable the diag job if you have not already: see docs/03-scheduled-jobs.md.

Run: `doctor`. It should show "diag firing on schedule (last run X minutes ago, Y recorded)".

Verify: After one week, you receive a Telegram message with the diag results. It names every
check that is not ok. Reply to it; the agent will help.

**Why:** "No news is good news" does not work for self-hosted systems. A config that was
correct yesterday can be wrong tomorrow (a certificate expiring, a cron job that never
started, a gateway that crashed at 3 AM). A human checking the logs once a week catches
these before they cause hours of downtime.

**Protects against:** Silent failures going unnoticed for days.

## 10. Backup plan: Telegram is not a substitute for real logs

**What:** Make sure you have a way to see what happened if Telegram ever goes down or your
internet connection is bad when a critical failure occurs.

**Steps:**
Enable systemd journal persistence: `sudo mkdir -p /var/log/journal && sudo systemctl restart
systemd-journald`.

Set up log rotation for OpenClaw's output: create `/etc/logrotate.d/neva`:
```
/var/log/neva/*.log {
    daily
    missingok
    rotate 7
    compress
    delaycompress
    notifempty
    create 0640 <user> <user>
}
```

Back up your vault: vault-sync already handles this if it is running. If you prefer manual
backups, add to your crontab: `0 2 * * * tar -czf /backups/neva-vault-$(date +%Y%m%d).tar.gz
~/.local/neva/vault` (create /backups first, and rotate old backups).

Verify: `journalctl --vacuum-time=7d` runs without error. The last 7 days of system logs are
preserved. `ls -la /var/log/journal/` shows journal files.

**Why:** A backup is only a backup if you have tested it. A log is only a log if you can read
it after the fact.

**Protects against:** Recovery being impossible because all evidence of what went wrong was
lost or purged.

## After all steps: hand-test the system

**What:** Manually verify that the end-to-end flow works before declaring it done.

**Steps:**
1. Send a message to your bot on Telegram from a different device (phone, laptop).
2. Verify the message arrives at the gateway: `journalctl -u neva-gateway.service -n 5`.
3. Verify the response comes back: you receive a reply on Telegram.
4. Verify the vault is up to date locally: `cd <vault-path> && git status` shows no diffs.
5. Verify the proxy is handling traffic: `tail -n 20 /var/log/nginx/access.log` shows your
   Telegram request.

If any of these fails, stop. Debug from the logs (named in each step). Do not assume "it will
probably work when I am not looking."

**Why:** A system that reads as "hardened" on a checklist but does not actually work is worse
than no system, because you might rely on it and not notice it has failed.

## Ongoing: run doctor weekly

Set a calendar reminder to run `doctor` every Sunday. Each row tells you what is ok and what
has drifted. Every FAIL should be fixed the same day. Every WARN should be understood. Over
months, a config that passed today can drift: a certificate expired, a token was rotated and
a config was not updated, a new OpenClaw CVE landed and your version is behind. A weekly
check catches all three before they cause an outage.

If `doctor` output ever stops matching what you expect, stop and debug. The tool is read-only
and cannot hurt you; an unexpected difference is a signal, not a false alarm.

---

## Not in this tier, and not shipped at all

Spoken voice, meaning text-to-speech or a voice channel, does NOT exist in this product.
There is no audio code anywhere in it. If you came here expecting it, stop looking: the word
"voice" in these docs means the writing voice your agent learns from how you type, which is
covered in docs/11-agent-voice.md and is part of the free tier, not this one.
