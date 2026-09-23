# Chrome Web Store submission draft

**Name:** Questionnaire Assistant

**Short description:** Reuse local answers and request AI help deliberately. Requires the Windows companion.

**Listing copy:** Stop answering the same questions from scratch. Keep reusable answers and private variables on your computer. Open the assistant on a form, find saved wording, preview it, and insert it yourself. With your own provider API account, request generated alternatives for questions you choose.

The extension requires a separately installed Windows companion. Saved reuse needs no API key. Generation may incur provider charges. Inserted text becomes visible to the website immediately. Supports ordinary top-level text fields, textareas, and tested plain-text editable regions. Never submits forms.

**Publisher:** SocratesOne Development LLC

**Permissions:** activeTab/scripting for explicit field activation and insertion; sidePanel for trusted workspace; nativeMessaging for local companion; storage for temporary form identity and interrupted-operation metadata. No broad host permissions, externally connectable messages, external analytics or remotely loaded code.

**Privacy draft:** Data is local except authorized model context sent directly to the selected provider and selected answers inserted into websites. DPAPI protects credentials/private bindings. General engine SQLite is not encrypted. Question labels, descriptors, approved model-visible wording and explicit feedback may enter model context. No cloud synchronization or hosted inference.

**Before submission:** actual support/privacy/download URLs, final validated screenshots, store identity, Windows acceptance, disclosure-form review and dependency/model notices. Do not publish placeholders or universal compatibility claims.

`npm run build && npm run package:store` creates `artifacts/questionnaire-extension-0.1.0.zip`. It does not upload or publish.
