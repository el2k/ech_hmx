# tgo-device-agent — AGENTS.md

> Language: Go 1.22 · Entry: `cmd/agent/main.go` · Protocol: TCP JSON-RPC 2.0 (newline-delimited JSON)

## Rules

- Identify change layer: `protocol`, `transport`, `tools`, or `sandbox`
- Protocol field changes: update `protocol/` first, then call chain — avoid implicit decode failures
- Tool behavior changes must re-check sandbox rules
- Protocol doc: `../tgo-device-control/docs/json-rpc.md`

## Key Paths

| Area | Files |
|------|-------|
| CLI entry | `cmd/agent/main.go` |
| Config | `internal/config/` |
| Protocol structs | `internal/protocol/` |
| Transport/auth/heartbeat | `internal/transport/client.go` |
| Tools | `internal/tools/` (fs_read, fs_write, fs_edit, shell_exec) |
| Sandbox | `internal/sandbox/sandbox.go` |

## Constraints

- Standard library only — no external dependencies
- Prefer explicit structs over `interface{}` (tool param dynamic schema is the exception)
- New tools must implement `Tool` interface and register in `Registry`
- All file/command ops must go through `internal/sandbox` validation
- No bypassing `work_root`/allowed paths
- No weakening of dangerous command interception, output truncation, or timeout limits
- Reconnection and heartbeat must remain idempotent
- Token persistence changes must be backward-compatible

## Verify

```bash
make vet && make test
```
