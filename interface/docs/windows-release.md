# Windows installer

The implemented companion uses Chrome native messaging, a single worker and Windows DPAPI. Packaging retains that transport and startup model. PyInstaller bundles Python, native DLLs, engine YAML/prompts, host contracts and the configured ONNX model. Inno Setup provides a per-user install with HKCU registration; no service, scheduled task or startup item is added.

## Build

Tested tooling: native CPython 3.10.19 x64, Node 22.20.0, PyInstaller 6.16.0, Inno Setup 6.7.3. Exact Python dependencies are in `packaging/requirements-windows.lock`; npm uses the existing `package-lock.json`. Build from a Windows filesystem, never a WSL virtual environment. Internet access is needed to acquire dependencies/model assets; installed local retrieval does not download a model.

From the repository root:

```powershell
powershell -NoProfile -File .\interface\packaging\build-windows.ps1 -InnoCompiler 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
```

Pass `-PythonExe <path-to-python.exe>` when the Python 3.10 launcher is unavailable, and pass `-InnoCompiler <path-to-ISCC.exe>` for a nonstandard Inno Setup installation. Use absolute tool paths if invoking from another directory. Outputs are `interface/artifacts/QuestionnaireAssistant-Setup-0.1.1-x64.exe` and `interface/artifacts/questionnaire-extension-0.1.1.zip`. Artifacts are unsigned local builds; no signing key or development credential is embedded. Signing and clean-machine acceptance remain release work.

The build preserves project licenses, distribution license texts and the model license/provenance. The initial Python resolver was constrained to LangChain 0.3 and checkpoint-sqlite 2.x to match the declared LangGraph 0.3 generation; resulting versions are locked. The configured model assets and license are checked against `packaging/model-lock.json`; unexpected upstream changes fail the build. No engine dependency declarations or npm lock versions were upgraded.

## Install and connect Chrome

1. Extract the extension ZIP into a permanent folder such as `<project-root>\QuestionnaireAssistantExtension`, with `manifest.json` directly inside it. In Chrome open `chrome://extensions`, enable Developer mode, choose **Load unpacked**, and select that folder. This is development setup, not a published-store installation. Keep the folder at that path: unpacked identity may depend on its path.
2. Copy the exact 32-letter ID Chrome displays. Run the installer and enter that ID. The same restricted origin is written to the installed manifest and the host allowlist. No wildcard or assumed production ID is used. There is no verified store link in this repository.
3. Open the extension's management page. Configure your model roles and provider credentials there when you want paid generation. Saved-answer reuse and local retrieval do not need provider credentials.
4. On a job description or form page, click the extension icon and choose **Start**. Chrome asks for site access so the session can continue to later pages. Use **Categories** in Settings to create answer contexts and choose a default; the small popup can switch the current context. Click a form field for inline saved answers, mapping, local saving, or optional AI help. **Use this page as job context** deliberately captures the current page for later generation in this session. Only exact questions you previously mapped fill automatically; review other saved suggestions inline.

Silent installation is supported only with an explicit ID:

```powershell
.\QuestionnaireAssistant-Setup-0.1.1-x64.exe /VERYSILENT /NORESTART /EXTENSIONID=<actual-Chrome-ID>
```

Default program directory: `%LOCALAPPDATA%\Programs\SocratesOne\QuestionnaireAssistant`.
Chrome registration: `HKCU\Software\Google\Chrome\NativeMessagingHosts\com.socratesone.questionnaire` points to the installed `native-host.json`.
User data: `%LOCALAPPDATA%\SocratesOne\QuestionnaireAssistant` (SQLite, DPAPI secrets, YAML/settings and session epochs). It is separate from installed files. Chrome launches the host when needed. Do not double-click the host as a desktop application; it needs Chrome's stdio protocol.

For a future published extension, use the actual assigned store ID in the same installer. A release must verify its listing before adding any link. This build neither installs the extension automatically nor changes browser policies or identity.

## Upgrade and uninstall

Close extension connections first. Run the newer installer into the existing directory and provide the same actual ID. Stable AppId and registry path prevent duplicate application registrations. Setup refuses to take over a native-host registration pointing at another installation directory.

After replacing the files in an existing **Load unpacked** extension folder, open `chrome://extensions` and click **Reload** on Questionnaire Assistant, then refresh any open form page. Replacing files on disk alone can leave Chrome's old background worker running beside a new content script; autosave may then report “Webpage adapters cannot read local data or authorize operations.” The Reload button refreshes both parts together.

Uninstall through Windows Installed Apps or `unins000.exe` in the installation directory. User data is always retained. Only a native-host registry value still pointing to this installation is removed; unrelated registry values are retained. Remove retained data manually only if you intend to permanently discard it. The extension is managed separately in Chrome.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests interface\tests -q
powershell -NoProfile -File .\interface\packaging\test-windows.ps1 -Installer .\interface\artifacts\QuestionnaireAssistant-Setup-0.1.1-x64.exe
```

The lifecycle test refuses an existing registration, uses a unique install directory, and redirects LOCALAPPDATA for child-host synthetic data. Its origin is explicitly a test fixture; it is not a production extension ID. The executable test strips Python/Conda/provider environment variables, limits PATH to System32, uses an unrelated working directory and enables Hugging Face offline mode. It tests the installed host with the real bundled embedder and no provider requests. Existing fixture-parity tests use a mock provider and hash embedder. Neither test is an actual Chrome connection or a disposable clean Windows VM.

For the stronger build-directory independence check, run `test-independence.ps1` from outside the repository. It refuses an existing installation, installs under a unique sibling test directory, temporarily renames only the Windows build checkout, runs the copied protocol test, restores the checkout in a finally block, then uninstalls. Close shells/editors holding the build directory first. This test still does not replace a clean VM.
