# Questionnaire Assistant interface

React management UI, Chrome MV3 side panel/field adapter, and Windows native-messaging companion for `answer_cache_agent` 0.1. All application code and tooling lives under `interface/`; the engine is consumed as a library. No hosted application or telemetry.

## Development

From `interface/`:

```bash
npm ci --cache .npm-cache
npm run check
npm run dev -- --port 4173
```

Python checks require the existing engine dependencies. `test:host` configures only the command's Python import search path; it does not install/edit the engine. Test databases use temporary directories. `npm run contracts` reads the root `schemas/` and writes only local generated types/snapshots; if the engine contract changes, re-export the root schemas first (`python scripts/export_schemas.py`).

Open `http://127.0.0.1:4173/manage.html` or `panel.html` for an honest disconnected preview. Load `dist/` through Chrome's **Load unpacked** for actual browser behavior. Production does not use Vite or an HTTP transport.

Build/install the companion using [Windows instructions](docs/windows-release.md). Registration must use the exact extension ID. Windows DPAPI has no plaintext Linux fallback.

## Supported

- Explicit activation, form selection, plain-text insertion, verification and guarded undo.
- Saved-template creation, local semantic suggestions and preview without model access.
- Cached candidates, explicit batch/targeted generation, feedback and approval.
- Protected credentials/bindings, configuration, category/variable creation, diagnostics and event reconciliation.
- Synthetic provider-free practice flow accessible from the installed extension.

## Gated

Exact-match autofill, exhaustive browsing, full record editing, context-scoped aliases, variable rename/delete, backup/restore/export and active cancellation need engine services. Changing local data requires a fresh form session. Saved search returns approved/context-eligible semantic neighbours, not a complete ranking or authoritative unique match.

See the [engine gap list](docs/engine-gaps.md), [integration](docs/integration.md), [acceptance](docs/acceptance.md), and [store materials](docs/store-listing.md). Development builds are not signed or publicly released products.
