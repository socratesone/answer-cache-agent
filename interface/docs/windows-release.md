# Windows packaging and release gates

Use native Windows x64 with Python, Node and Inno Setup 6 on the build machine. End users need none of those tools.

```powershell
.\packaging\build-windows.ps1 -ExtensionId '<actual 32-character Chrome extension ID>'
```

The ID is an explicit input, never a wildcard. The build snapshots engine source inside `interface/artifacts/engine-source`, installs that copy, downloads the configured embedding model into build assets, verifies local-only loading, bundles runtime/native libraries with PyInstaller, and compiles a per-user installer. Root engine files are not build outputs.

Installer behavior: HKCU native-host registration restricted to the chosen extension; optional store-listing launch requiring Chrome confirmation; data outside the install directory retained across upgrades; host must close for install/uninstall; uninstall separately asks whether to delete local data, defaulting to retain.

Release checklist:

- [ ] Clean Windows VM install with no Python/Node and model-download access blocked.
- [ ] Actual Chrome native framing and DPAPI save/reopen as the same Windows user.
- [ ] Provider-free creation/lookup/preview/insertion/undo, in practice flow and website fixture.
- [ ] Disconnect, worker restart, reconciliation and profile contention.
- [ ] Upgrade preserving data and credentials; both uninstall retention choices.
- [ ] Live providers with explicitly approved spending and supplied test credentials.
- [ ] Model/dependency license review and complete notices.
- [ ] Installer/executable signing and signature verification.
- [ ] Final support/privacy/download URLs, screenshots, store submission/approval.

Source packaging scripts do not satisfy these gates. No installer binary is claimed validated from Linux/WSL.
