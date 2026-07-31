# Tier 2: always-on VPS (paid guide placeholder)

The full guide ships with the paid tier. Outline: a $6-8/mo VPS (2GB minimum, agent turns
are memory-hungry: swap configured before first OOM, not after), the gateway as a systemd
service bound to loopback, SSH tunnel or Tailscale for any remote surface (never an exposed
port), the vault as a bare git repo with both your machines syncing to it, all guard timers
enabled from day one, and the hardening checklist executed in order and verified by doctor.
