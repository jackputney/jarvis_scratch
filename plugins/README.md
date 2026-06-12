# Jarvis plugins (Phase 2)

Drop a folder here with a `manifest.json`. At startup the orchestrator will:

1. Discover each `plugins/*/manifest.json`
2. Start the MCP server (`mcp_command`) or connect to `mcp_url`
3. Register tools using `risk_tier` for confirm gating:
   - `read_only` — never confirm
   - `auto_allow` — run immediately
   - `confirm_required` — dashboard Allow/Deny modal

See `example/manifest.json` for the schema.

Triggers (`cron`, `webhook`, `event`) submit ordinary `Command` objects to the
orchestrator queue — same budget, logging, and confirm rules as voice.
