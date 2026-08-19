# tgo-ai — AGENTS.md

> Port: 8081 · Entry: `app/main.py` · Prefix: `/api/v1`

## Rules

- Chat link changes must verify both `stream=false` and `stream=true` paths
- Change schema/types first, then service and router
- Model structure changes must include Alembic migration
- Cross-service calls go through `app/services/*` — no hardcoded URLs or private implementation details

## Key Paths

| Area | Files |
|------|-------|
| Chat | `app/api/v1/chat.py` → `app/services/chat_service.py` |
| Orchestration | `app/runtime/supervisor/` |
| Tools | `app/runtime/tools/`, `app/services/tool_executor.py` |
| Streaming | `app/streaming/` |
| Schemas | `app/schemas/` |
| Models | `app/models/` |

## Constraints

- No `Any` in core interfaces
- No bare `dict` for business objects
- SSE chunk format and event order are stable API — do not break
- External addresses from `app/config.py` + `.env` only
- API input/output must be modeled in `app/schemas/*`

## Verify

```bash
# Static
poetry run mypy app && poetry run flake8 app && poetry run pytest

# Functional (requires running server)
TGO_CLI="node ../tgo-cli/dist/index.js"
$TGO_CLI agent list --limit 1           # agent CRUD
$TGO_CLI provider list                  # provider connectivity
$TGO_CLI chat team --message "say ok"   # chat e2e (stream)

WIDGET_CLI="node ../tgo-widget-cli/dist/index.js"
$WIDGET_CLI chat send --message "say ok" --no-stream  # visitor chat e2e
```
