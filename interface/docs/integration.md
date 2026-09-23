# Integration and security

Website → content adapter → extension worker → native messaging → Python service → existing engine. Only the companion calls providers. Content adapters may report bounded snapshots or open the panel. Exact extension-owned panel/management/demo URLs may invoke application commands. Tab/document identity comes from Chrome sender metadata.

The transport envelope contains request ID, protocol version, schema fingerprint, operation and operation data. `event` carries an unchanged engine Event and separate generation authorization. Application commands cover settings, bindings, rendering, imports, search and diagnostics. Keys/bindings never enter engine events. Unknown fields are rejected; envelopes and event-specific payloads are validated independently.

Native frames use 32-bit little-endian lengths and UTF-8 JSON, capped below Chrome's 1 MiB response limit. stdout is protocol-only; errors never echo validation input. Registration and executable both allowlist extension origins. A Windows user-session mutex prevents concurrent host processes. One worker owns the Agent and database connection.

## Persistence and recovery

Application data lives under `%LOCALAPPDATA%\SocratesOne\QuestionnaireAssistant`. Engine SQLite contents remain engine-owned. The companion owns DPAPI-protected secrets, engine YAML, role settings and dependency epochs; it introduces no direct engine-table SQL.

Trusted-only `chrome.storage.session` retains form identity, revisions and pending symbolic events across worker restarts, not browser restarts. It stores no credentials or rendered previews. Browser restart requires fresh activation; engine data remains on disk. Interrupted operations reconcile only through user action using unchanged event IDs. Uncertain paid outcomes are never automatically replaced with new requests.

Local data/configuration changes increment an application epoch. Existing sessions cannot continue; **Refresh form** mints a new session. This conservative fallback remains until dependency-aware engine invalidation is available.

## Disclosure and insertion

Captured answers become local-only records only after explicit approval. Snapshots include question labels, constraints and occupancy, not field values. URLs omit query/fragment; no full-page capture. Model-visible templates, questions, category IDs and feedback may reach providers. Known private bindings/credentials are checked before event persistence; this does not guarantee anonymity for unregistered private text.

Only selected insertion text reaches a website. The companion re-renders/rechecks constraints, and the content adapter rechecks document/form/field identity and contents. Populated fields require confirmation; concurrent edits abort. Undo requires the inserted value to remain unchanged. Copy is explicit.

## Limitations

No streaming or active engine cancellation. Stop cancels queued requests and suppresses late results; in-flight work may finish and incur charges. Costs are estimates; unknown cost does not mean free. Self-reports are not independent verification. Model identifiers require explicit development setup pending a catalogue. General engine SQLite is not encrypted; DPAPI protects credentials/private bindings only.
