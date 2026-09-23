# Development validation — 2026-09-22

Validated on Linux/WSL against the currently available engine contract, fingerprint `a009bd503efd319bf047d19e054e3660a4a1e34b8b0fc2b9bdaee41a59504294`.

- Frontend production build and TypeScript checks passed.
- 17 frontend unit tests passed: exclusions, label interpretation, inert insertion, edit-preserving undo, sender trust, frame restrictions and stale-target dispatch.
- 14 Python tests passed: both fixture scripts match direct-engine statuses/candidate counts; saved reuse without provider keys; strict payload checks; spending authorization; budget/stale-context handling; replay; dependency epochs; known-value privacy checks; frame parsing/bounds; origin allowlisting; no plaintext protection fallback.
- Isolated Chromium smoke checks passed: management navigation, narrow layout, field detection, dynamic replacement, safe insertion/undo, document identity and keyboard focus. A separately identified synthetic transport checks paid authorization, concise cache retrieval and shown/selected reporting. These synthetic checks are not live provider/native-host tests.
- Host and frontend schema snapshots match.
- Development extension ZIP produced, including original icons and dependency notices.

Screenshots: `artifacts/management.png`, `artifacts/panel.png`, `artifacts/panel-synthetic-connected.png`. The connected screenshot uses clearly synthetic test answers. Machine-readable browser results: `artifacts/browser-report.json`.

Not validated here: Windows binary build/install, DPAPI roundtrip on Windows, actual Chrome-to-native-host linkage, upgrade/uninstall, real embedding packaging on Windows, live providers, installer signing or store publication. Release must also resolve required engine gaps in `fable-handoff.md`.

No root engine tests/report generators/schema exporters were run; no engine-side files were authored by this implementation. Nothing was staged or committed.
