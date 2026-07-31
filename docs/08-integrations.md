# Integrations

Ships enabled (all free, none require Docker):
- **hledger**: money journal in `05 Money/`. The agent appends and reports; figures outside
  the journal do not exist. `brew/apt install hledger`.
- **ntfy**: push channel for guards and nudges. Zero install with ntfy.sh: set NTFY_TOPIC
  in identity.env to a long random string; the agent publishes with one curl.
- **syncthing**: vault on your phone and laptop. Single binary.
- **obsidian-git** plugin: every agent edit becomes a commit you can inspect and revert.
- **Dataview + heatmap**: dashboards over agent-written fields, view-only.

Documented, install when wanted: taskwarrior/timewarrior, beancount + fava, Actual Budget,
jrnl, himalaya (email), khal (CalDAV), Miniflux (RSS), atuin, yt-dlp/ffmpeg/pandoc.
Note on the Tasks plugin: its default emoji signifiers conflict with the no-emoji house
style; use its dataview-field mode.

Nutrition has no good open-source self-hosted answer, so the vault ships a markdown food
log the agent parses (see Food/), with Open Food Facts lookups (no API key) for packaged
items. Compatible with the Obsidian Macros plugin for dashboards.
