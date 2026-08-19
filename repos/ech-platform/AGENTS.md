# tgo-platform — AGENTS.md

> Port: 8003 · Entry: `app/main.py` · Channels: WeChat/企微/飞书/钉钉/Telegram/Slack/邮件/WuKongIM

## Rules

- Identify change layer: API, listener, or normalizer
- Keep channel input model and normalized output model boundaries clear
- Listener changes must verify startup/shutdown behavior
- Changes to `tgo-api` call fields must check upstream compatibility
- Model changes must include Alembic migration

## Key Paths

| Area | Files |
|------|-------|
| Message intake | `app/api/v1/messages.py` |
| Platform config | `app/api/v1/platforms.py` |
| Callbacks | `app/api/v1/callbacks.py` |
| Channel listeners | `app/domain/services/listeners/*` |
| Normalizer | `app/domain/services/normalizer.py` |
| API client | `app/infra/` (tgo-api HTTP client, visitor client, SSE) |
| Config | `app/core/config.py` |

## Constraints

- New listeners must integrate into startup/stop lifecycle — no leaked tasks
- No blocking calls in listeners — use async I/O
- External messages must be normalized before forwarding — no channel-specific fields leaking upstream
- Callback retries need idempotent handling
- Platform keys, callback URLs, API base from config — no hardcoding

## Verify

```bash
# Static
poetry run ruff check . && poetry run ruff format --check .

# Functional (requires running server)
TGO_CLI="node ../tgo-cli/dist/index.js"
$TGO_CLI platform list                  # platform CRUD

WIDGET_CLI="node ../tgo-widget-cli/dist/index.js"
$WIDGET_CLI platform info               # visitor-side platform
```
