# tgo-workflow — AGENTS.md

> Port: 8004 · Entry: `app/main.py` · Prefix: `/v1/workflows` · Worker: `celery_app/celery.py`

## Rules

- Identify change target: schema, node executor, or dispatch chain
- Node behavior changes: update validation first, then execution logic
- Async task changes must verify API ↔ worker coordination path
- New node types must update: node schema, executor, registry, validation

## Key Paths

| Area | Files |
|------|-------|
| Executor | `app/engine/executor.py` |
| Graph/context | `app/engine/graph.py`, `app/engine/context.py` |
| Node implementations | `app/engine/nodes/*` |
| API | `app/api/workflows.py`, `app/api/executions.py` |
| Celery tasks | `celery_app/tasks.py` |
| Models | `app/models/` |
| Schemas | `app/schemas/` |

## Constraints

- No breaking changes to DAG topology or node state-flow semantics
- Variable references, template rendering, and branch logic must be backward-compatible
- Node execution must not block the event loop
- External calls must have timeout + error mapping
- Model changes must include Alembic migration

## Verify

```bash
# Static
poetry run pytest

# Functional (requires running server)
TGO_CLI="node ../tgo-cli/dist/index.js"
$TGO_CLI workflow list --limit 1        # workflow CRUD
# $TGO_CLI workflow validate <id>       # workflow validation
```
