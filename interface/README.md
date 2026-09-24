# Questionnaire Assistant interface

React management UI, Chrome MV3 popup and inline field adapter, and Windows native-messaging companion for `answer_cache_agent` 0.1. All application code and tooling lives under `interface/`; the engine is consumed as a library. No hosted application or telemetry.

## Development

From `interface/`:

```bash
npm ci --cache .npm-cache
npm run check
npm run dev -- --port 4173
```

Python checks require the existing engine dependencies. `test:host` configures only the command's Python import search path; it does not install/edit the engine. Test databases use temporary directories. `npm run contracts` reads the root `schemas/` and writes only local generated types/snapshots; if the engine contract changes, re-export the root schemas first (`python scripts/export_schemas.py`).

Open `http://127.0.0.1:4173/manage.html` for a disconnected management preview. Load `dist/` through Chrome's **Load unpacked** for browser behavior. Production does not use Vite or an HTTP transport.

Build/install the companion using [Windows instructions](docs/windows-release.md). Registration must use the exact extension ID. Windows DPAPI has no plaintext Linux fallback.

## Supported

- A per-tab questionnaire session survives page and SPA navigation; a new tab opened from the session inherits it. The popup starts/stops the session and selects a category.
- Inline field controls discover text, native selects, radios, checkboxes, accessible comboboxes and file inputs. Choosing a saved answer immediately maps the field question to that same answer ID; an exact mapped question can fill automatically on a later visit.
- Editing an answer's label or wording updates the existing companion record. Typing into a form field automatically creates or updates its mapped local answer; **Create another answer** remains an explicit action. New aliases are indexed with the companion's existing semantic vectors.
- File inputs offer an explicit picker and attach the chosen file to the page input. The extension does not retain files across pages or silently upload them.
- Explicit targeted generation is available inline when a provider is configured. A page may be deliberately captured as context for later steps.
- Protected credentials/bindings, configuration, category/variable creation, diagnostics and event reconciliation.
- Synthetic provider-free practice flow accessible from the installed extension.

## Gated

Unattended filling from semantic search remains gated: the companion explicitly returns `autofillEligible: false` and semantic search is not an authoritative unique match. Exact user-approved mappings may fill automatically. Universal custom-control support, exhaustive browsing, variable rename/delete, backup/restore/export and active cancellation need further engine or site-specific services. Changing local data requires a fresh engine form session. See [the redesign status](docs/form-centric-redesign.md).

See the [engine gap list](docs/engine-gaps.md), [Fable handoff](docs/fable-handoff.md), [integration](docs/integration.md), [acceptance](docs/acceptance.md), and [store materials](docs/store-listing.md). Development builds are not signed or publicly released products.
