# tgo-cli — AGENTS.md

> Stack: TypeScript + Commander.js + MCP Server · Role: Staff-side CLI + MCP server

## Rules

- All API calls go through `src/client.ts` — handles auth headers and error formatting
- Each command exports both Commander registration (CLI) and standalone action functions (MCP/test)
- Action functions accept `TgoClient` as parameter — dependency injection for testability
- MCP tools map 1:1 to CLI commands with `tgo_<resource>_<action>` naming
- **When adding/removing/modifying any command or MCP tool, update `COMMANDS.md`**

## Key Paths

| Area | Files |
|------|-------|
| CLI entry | `src/index.ts` |
| API client | `src/client.ts` |
| Config | `src/config.ts` (`~/.tgo/config.json`) |
| Output formatting | `src/output.ts` |
| WuKongIM | `src/wukongim.ts` |
| Commands | `src/commands/*.ts` |
| MCP server | `src/mcp/server.ts` |

## Constraints

- Config priority: CLI flags > env vars (`TGO_SERVER`, `TGO_TOKEN`) > config file
- Dual send paths: website visitors via WuKongIM WS only; non-website platforms via HTTP API first, then WS
- Tests co-located with source (`*.test.ts` next to `*.ts`)
- Test patterns: mock `TgoClient` directly — no module mocking needed for commands

## Verify

```bash
npm run build && npm test
```
