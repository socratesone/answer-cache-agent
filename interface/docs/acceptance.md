# Acceptance and compatibility

`npm run check` builds schema-derived types and bundles, runs DOM safety tests, and runs Python fixture parity/protocol/privacy tests. `python tests/browser_smoke.py` separately tests built pages and the real field adapter in isolated Chrome, with a synthetic transport and screenshots in `artifacts/`. It never attaches to a user's profile.

| Surface | Behavior | Evidence scope |
|---|---|---|
| Top-level text/email/URL/search/telephone | Plain text, labels/ARIA, limits | DOM checks; Windows acceptance pending |
| Textareas | Plain text, guarded undo | Isolated Chromium fixture |
| Plain editable regions | Only plain text; verify persistence | Site compatibility unclaimed |
| Dynamic/controlled fields | Setter/events, verify, abort stale target | Isolated fixture; not universal support |
| Sensitive/hidden/disabled/read-only | Excluded | DOM and isolated fixture |
| Rich text/cross-origin/closed shadow roots | Manual preview/copy | Unsupported autofill |
| Chrome internal pages | Unsupported message | Explicit URL gate |
| Extension practice page | Local reuse with direct insertion helper | Full roundtrip needs installed companion |

Engine gaps are listed in `engine-gaps.md`. Native Windows install/upgrade/uninstall, actual Chrome native-host linkage, live providers, signing and store approval remain separate gates.
