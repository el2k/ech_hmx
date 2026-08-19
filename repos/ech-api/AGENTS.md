# tgo-api — AGENTS.md

> Ports: 8000 (main, auth required), 8001 (internal, no auth) · Entry: `app/main.py`, `app/internal.py`

## Rules

- Locate the domain first: endpoint → schema → service → model → task
- Reuse existing `services/*_client.py` for external service calls — no parallel implementations
- Interface field changes must sync schema, service, and callers
- Model changes must include Alembic migration (`alembic/versions/`)
- Internal API must stay internal-only — no public route exposure

## Key Paths

| Area | Files |
|------|-------|
| Chat | `app/services/chat_service.py` |
| Visitors | `app/services/visitor_service.py`, `app/tasks/process_waiting_queue.py` |
| AI client | `app/services/ai_client.py` |
| Platform sync | `app/services/platform_sync.py` |
| Device control | `app/services/device_control_client.py` |
| Endpoints | `app/api/v1/endpoints/` |
| Internal API | `app/api/internal/endpoints/` |
| Schemas | `app/schemas/` |
| Models | `app/models/` |

## Constraints

- No `Any` in core interfaces; no bare `dict` for business objects
- Business logic in `app/services/*`, not in endpoints
- Constants in `app/utils/const.py`, errors via `TGOAPIException`
- No `print` — use project logger
- No cross-service direct DB access

## Verify

```bash
# Static
poetry run mypy app && poetry run flake8 app && poetry run pytest

# Functional (requires running server)
TGO_CLI="node ../tgo-cli/dist/index.js"
$TGO_CLI system info                    # system health
$TGO_CLI auth whoami                    # auth working
$TGO_CLI conversation list --limit 1    # core CRUD
$TGO_CLI visitor list --limit 1         # visitor flow

WIDGET_CLI="node ../tgo-widget-cli/dist/index.js"
$WIDGET_CLI platform info               # visitor-side platform
$WIDGET_CLI chat send --message "ok" --no-stream  # visitor chat e2e
```
