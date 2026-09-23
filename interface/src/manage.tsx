import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { Brand, Notice, Unavailable } from "./components/common";
import { host } from "./integration/client";
import type { HostInfo, Match } from "./integration/types";
import "./styles.css";
const tabs = [
  "Overview",
  "Answers",
  "Variables",
  "Categories",
  "Provider & budget",
  "Diagnostics",
];
const id = (prefix: string) =>
  `${prefix}_${crypto.randomUUID().replaceAll("-", "")}`;
function App() {
  const [tab, setTab] = useState("Overview"),
    [info, setInfo] = useState<HostInfo | null>(null),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false);
  const [question, setQuestion] = useState(""),
    [body, setBody] = useState(""),
    [disclosure, setDisclosure] = useState("local_only"),
    [matches, setMatches] = useState<Match[]>([]);
  const [variables, setVariables] = useState<
      { id: string; safe_description: string }[]
    >([]),
    [varId, setVarId] = useState(""),
    [description, setDescription] = useState(""),
    [privateValue, setPrivateValue] = useState("");
  const [categoryId, setCategoryId] = useState(""),
    [categoryLabel, setCategoryLabel] = useState(""),
    [valueId, setValueId] = useState(""),
    [valueLabel, setValueLabel] = useState("");
  const [provider, setProvider] = useState("openai"),
    [key, setKey] = useState(""),
    [routine, setRoutine] = useState(""),
    [advanced, setAdvanced] = useState(""),
    [budget, setBudget] = useState("0.50");
  const [diagnostics, setDiagnostics] = useState(""),
    [preview, setPreview] = useState(""),
    [templateVariable, setTemplateVariable] = useState(""),
    [requires, setRequires] = useState(false);
  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setMessage("");
    try {
      await fn();
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function connect() {
    const status = await host<HostInfo>("hello");
    setInfo(status);
    setBudget(String(status.budget.max_session_cost_usd));
    if (status.settings.roles) {
      setRoutine(
        `${status.settings.roles.routine.provider}:${status.settings.roles.routine.model}`,
      );
      setAdvanced(
        `${status.settings.roles.advanced.provider}:${status.settings.roles.advanced.model}`,
      );
    }
  }
  useEffect(() => {
    void connect().catch((e) =>
      setMessage(`Companion not connected. ${e.message}`),
    );
  }, []);
  const loadVariables = async () =>
    setVariables((await host("variables")).variables);
  function role(raw: string) {
    const at = raw.indexOf(":");
    if (at < 1) throw Error("Use provider:model for each role.");
    return { provider: raw.slice(0, at), model: raw.slice(at + 1) };
  }
  async function saveTemplate() {
    const references = [
      ...new Set(
        [...body.matchAll(/\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}/g)].map(
          (m) => m[1],
        ),
      ),
    ];
    await host("ingest", {
      record: {
        kind: "template",
        id: id("T"),
        intent: question.trim(),
        aliases: [question.trim()],
        body,
        variables: references,
        evidence: [],
        context:
          categoryId && valueId
            ? [
                {
                  dimension: categoryId,
                  value: valueId,
                  mode: requires ? "requires" : "applies",
                },
              ]
            : [],
        disclosure,
        approved_by: "user",
        approved_at: new Date().toISOString(),
      },
    });
    setMessage(
      "Approved wording saved. Refresh active forms before using changed local information.",
    );
    setBody("");
    setPreview("");
  }
  return (
    <div className="management">
      <Brand>
        <span className="tag">Local workspace</span>
      </Brand>
      <div className="management-layout">
        <nav aria-label="Management">
          {tabs.map((t) => (
            <button
              key={t}
              aria-current={tab === t ? "page" : undefined}
              onClick={() => {
                setTab(t);
                setMessage("");
              }}
            >
              {t}
            </button>
          ))}
        </nav>
        <main>
          <div className="eyebrow">Your reusable knowledge</div>
          <h1>
            {tab === "Overview" ? "Good answers deserve a second use." : tab}
          </h1>
          {message && <Notice>{message}</Notice>}
          {tab === "Overview" && (
            <>
              <p className="muted">
                Keep your answers close. Choose exactly when a model helps.
              </p>
              <div className="grid">
                <div className="stat">
                  Local application
                  <strong>{info ? "Connected" : "Not connected"}</strong>
                </div>
                <div className="stat">
                  Provider
                  <strong>
                    {info?.configured
                      ? "Credential stored"
                      : "Optional — not configured"}
                  </strong>
                </div>
                <div className="stat">
                  Generation
                  <strong>
                    {info?.generationReady
                      ? "Configured; live availability untested"
                      : "Setup needed"}
                  </strong>
                </div>
                <div className="stat">
                  Saved-answer reuse<strong>No API key required</strong>
                </div>
              </div>
              <section className="card">
                <h2>Start with one answer</h2>
                <ol>
                  <li>
                    Install the Windows companion and add the Chrome extension.
                  </li>
                  <li>Create an answer in the Answers tab.</li>
                  <li>
                    Open a test form, activate the extension, and preview your
                    saved answer.
                  </li>
                </ol>
                <div className="actions">
                  <button className="primary" onClick={() => setTab("Answers")}>
                    Create an answer
                  </button>
                  <a href="demo.html" target="_blank">
                    Synthetic demo form
                  </a>
                  <button disabled={busy} onClick={() => run(connect)}>
                    Reconnect
                  </button>
                </div>
                <p className="muted">
                  The bundled demo supports local saved-answer lookup and
                  insertion without a terminal. Testing website detection uses
                  an ordinary supported website or the localhost developer
                  fixture.
                </p>
              </section>
              <section className="card">
                <h2>Installation</h2>
                <p>
                  Run the companion installer supplied with this build. It
                  packages Python and registers the native host. Chrome must
                  still confirm extension installation.
                </p>
                <p className="muted">
                  Public download and Chrome Web Store URLs are not available in
                  this development build. No signing or store approval is
                  implied.
                </p>
              </section>
            </>
          )}
          {tab === "Answers" && (
            <>
              <section className="card">
                <h2>Find an answer</h2>
                <label>
                  Question or search phrase
                  <input
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                  />
                </label>
                <button
                  disabled={busy || !question}
                  onClick={() =>
                    run(async () =>
                      setMatches(
                        (await host("search", { query: question })).matches,
                      ),
                    )
                  }
                >
                  Search locally
                </button>
                {matches.map((m) => (
                  <article className="card" key={m.id}>
                    <span className="tag">Approved template</span>
                    <h3>{m.intent}</h3>
                    <p className="answer">{m.body}</p>
                    <small>{m.id}</small>
                  </article>
                ))}
                <Unavailable>
                  Complete library browsing and existing-template editing are
                  unavailable.
                </Unavailable>
              </section>
              <section className="card">
                <h2>Create reusable wording</h2>
                <label>
                  Question wording
                  <input
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                  />
                </label>
                <label>
                  Answer template
                  <textarea
                    value={body}
                    onChange={(e) => {
                      setBody(e.target.value);
                      setPreview("");
                    }}
                    placeholder="Write an answer in your own words…"
                  />
                </label>
                <div className="row">
                  <label>
                    Variable
                    <select
                      value={templateVariable}
                      onChange={(e) => setTemplateVariable(e.target.value)}
                    >
                      <option value="">Select a variable</option>
                      {variables.map((v) => (
                        <option key={v.id} value={v.id}>
                          {v.safe_description || v.id}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button disabled={busy} onClick={() => run(loadVariables)}>
                    Load variables
                  </button>
                  <button
                    disabled={!templateVariable}
                    onClick={() =>
                      setBody((b) => b + `{{${templateVariable}}}`)
                    }
                  >
                    Insert variable
                  </button>
                </div>
                <label>
                  Disclosure
                  <select
                    value={disclosure}
                    onChange={(e) => setDisclosure(e.target.value)}
                  >
                    <option value="local_only">Local reuse only</option>
                    <option value="model_visible">
                      Allow this wording in model context
                    </option>
                  </select>
                </label>
                <p className="muted">
                  Private values belong in Variables. Model-visible templates
                  should use placeholders. Approving wording does not certify
                  facts.
                </p>
                <details>
                  <summary>Contextual applicability</summary>
                  <label>
                    Category ID
                    <input
                      value={categoryId}
                      onChange={(e) => setCategoryId(e.target.value)}
                    />
                  </label>
                  <label>
                    Value ID
                    <input
                      value={valueId}
                      onChange={(e) => setValueId(e.target.value)}
                    />
                  </label>
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={requires}
                      onChange={(e) => setRequires(e.target.checked)}
                    />
                    Require this value to reuse the answer
                  </label>
                  <p className="muted">
                    Otherwise this category is a soft preference. Category/value
                    IDs come from Categories below.
                  </p>
                </details>
                <div className="actions">
                  <button
                    disabled={busy || !body}
                    onClick={() =>
                      run(async () => {
                        const r = await host("render", { body });
                        setPreview(r.text || r.problems.join("; "));
                      })
                    }
                  >
                    Preview locally
                  </button>
                  <button
                    className="primary"
                    disabled={busy || !body.trim() || !question.trim()}
                    onClick={() => run(saveTemplate)}
                  >
                    Approve & save
                  </button>
                </div>
                {preview && <p className="answer">{preview}</p>}
              </section>
              <Unavailable>
                Context-specific remembered question wording and cross-session
                generated-candidate browsing are unavailable.
              </Unavailable>
            </>
          )}
          {tab === "Variables" && (
            <>
              <p className="muted">
                Descriptions can enter model context. Private values stay in the
                companion’s protected store.
              </p>
              <section className="card">
                <h2>Create a variable</h2>
                <label>
                  Variable identifier
                  <input
                    value={varId}
                    onChange={(e) => setVarId(e.target.value)}
                    placeholder="motivation_statement"
                    pattern="[A-Za-z_][A-Za-z0-9_]*"
                  />
                </label>
                <label>
                  Description permitted in model context
                  <textarea
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="An approved statement explaining interest in engineering roles"
                  />
                </label>
                <button
                  disabled={busy || !varId || !description}
                  onClick={() =>
                    run(async () => {
                      if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(varId))
                        throw Error(
                          "Use letters, numbers and underscores; start with a letter or underscore.",
                        );
                      await host("ingest", {
                        record: {
                          kind: "variable",
                          id: varId,
                          safe_description: description,
                          value_type: "text",
                          permitted_use: "verbatim",
                        },
                      });
                      await loadVariables();
                      setMessage(
                        "Description created. Add its private value separately.",
                      );
                    })
                  }
                >
                  Save description
                </button>
              </section>
              <section className="card">
                <h2>Set a private value</h2>
                <button disabled={busy} onClick={() => run(loadVariables)}>
                  Load variables
                </button>
                <label>
                  Variable
                  <select
                    value={varId}
                    onChange={(e) => setVarId(e.target.value)}
                  >
                    <option value="">Choose a variable</option>
                    {variables.map((v) => (
                      <option key={v.id} value={v.id}>
                        {v.id} — {v.safe_description}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Private value used locally
                  <textarea
                    value={privateValue}
                    onChange={(e) => setPrivateValue(e.target.value)}
                    autoComplete="off"
                  />
                </label>
                <button
                  disabled={busy || !varId}
                  onClick={() =>
                    run(async () => {
                      await host("binding", { id: varId, value: privateValue });
                      setPrivateValue("");
                      setMessage(
                        "Private value saved. Refresh active forms before continuing.",
                      );
                    })
                  }
                >
                  Store private value
                </button>
              </section>
              <Unavailable>
                Rename/delete and template-reference checks are unavailable.
              </Unavailable>
            </>
          )}
          {tab === "Categories" && (
            <>
              <p className="muted">
                Create your own categories and values. Nothing is classified
                automatically.
              </p>
              <section className="card">
                <h2>Create a category</h2>
                <label>
                  Category name
                  <input
                    value={categoryLabel}
                    onChange={(e) => setCategoryLabel(e.target.value)}
                    placeholder="Role type"
                  />
                </label>
                <label>
                  Stable category ID
                  <input
                    value={categoryId}
                    onChange={(e) => setCategoryId(e.target.value)}
                    placeholder="role_type"
                  />
                </label>
                <button
                  disabled={busy || !categoryId || !categoryLabel}
                  onClick={() =>
                    run(async () => {
                      await host("ingest", {
                        record: {
                          kind: "dimension",
                          id: categoryId,
                          label: categoryLabel,
                        },
                      });
                      setMessage(`Category created: ${categoryId}`);
                    })
                  }
                >
                  Create category
                </button>
              </section>
              <section className="card">
                <h2>Add a value</h2>
                <label>
                  Category ID
                  <input
                    value={categoryId}
                    onChange={(e) => setCategoryId(e.target.value)}
                  />
                </label>
                <label>
                  Value name
                  <input
                    value={valueLabel}
                    onChange={(e) => setValueLabel(e.target.value)}
                    placeholder="Agent engineering"
                  />
                </label>
                <label>
                  Stable value ID
                  <input
                    value={valueId}
                    onChange={(e) => setValueId(e.target.value)}
                    placeholder="agent_engineering"
                  />
                </label>
                <button
                  disabled={busy || !categoryId || !valueId || !valueLabel}
                  onClick={() =>
                    run(async () => {
                      await host("ingest", {
                        record: {
                          kind: "value",
                          id: valueId,
                          dimension_id: categoryId,
                          label: valueLabel,
                        },
                      });
                      setMessage(
                        `Value created: ${valueId}. Use these IDs in the panel’s context controls.`,
                      );
                    })
                  }
                >
                  Create value
                </button>
              </section>
              <Unavailable>
                Listing, renaming and deleting categories are unavailable.
              </Unavailable>
            </>
          )}
          {tab === "Provider & budget" && (
            <>
              <section className="card">
                <h2>Your provider account</h2>
                <p className="muted">
                  API access is billed separately from consumer chat
                  subscriptions. Saving settings makes no paid test request.
                </p>
                <label>
                  Provider
                  <select
                    value={provider}
                    onChange={(e) => setProvider(e.target.value)}
                  >
                    <option value="openai">OpenAI</option>
                    <option value="anthropic">Anthropic</option>
                  </select>
                </label>
                <label>
                  API key
                  <input
                    type="password"
                    value={key}
                    onChange={(e) => setKey(e.target.value)}
                    autoComplete="new-password"
                  />
                </label>
                <button
                  disabled={busy || !key}
                  onClick={() =>
                    run(async () => {
                      await host("configure", { provider, key });
                      setKey("");
                      await connect();
                      setMessage(
                        "Credential stored in Windows protection. No provider call was made.",
                      );
                    })
                  }
                >
                  Store credential
                </button>
                <p className="muted">
                  <a
                    href="https://platform.openai.com/api-keys"
                    target="_blank"
                    rel="noreferrer"
                  >
                    OpenAI API keys
                  </a>{" "}
                  ·{" "}
                  <a
                    href="https://console.anthropic.com/settings/keys"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Anthropic API keys
                  </a>
                </p>
              </section>
              <section className="card">
                <h2>Model roles & spending</h2>
                <Unavailable>
                  The engine does not yet expose supported model choices.
                  Development setup accepts explicit provider:model identifiers.
                </Unavailable>
                <label>
                  Routine model
                  <input
                    value={routine}
                    onChange={(e) => setRoutine(e.target.value)}
                    placeholder="provider:model"
                  />
                </label>
                <label>
                  Advanced model
                  <input
                    value={advanced}
                    onChange={(e) => setAdvanced(e.target.value)}
                    placeholder="provider:model"
                  />
                </label>
                <label>
                  Maximum cost per form session (USD)
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={budget}
                    onChange={(e) => setBudget(e.target.value)}
                  />
                </label>
                <p className="muted">
                  Engine pricing is an estimate, not a provider billing limit.
                  Unknown-priced models cannot guarantee a dollar cap. Token
                  limits still apply. Changing the limit requires refreshing
                  active forms.
                </p>
                <button
                  disabled={
                    busy ||
                    !routine ||
                    !advanced ||
                    !Number.isFinite(Number(budget))
                  }
                  onClick={() =>
                    run(async () => {
                      await host("configure", {
                        roles: {
                          routine: role(routine),
                          advanced: role(advanced),
                        },
                        budget: Number(budget),
                      });
                      await connect();
                      setMessage("Configuration saved. Refresh active forms.");
                    })
                  }
                >
                  Save configuration
                </button>
              </section>
            </>
          )}
          {tab === "Diagnostics" && (
            <>
              <section className="card">
                <h2>Connection details</h2>
                <button
                  disabled={busy}
                  onClick={() =>
                    run(async () =>
                      setDiagnostics(
                        JSON.stringify(await host("diagnostics"), null, 2),
                      ),
                    )
                  }
                >
                  Review diagnostics
                </button>
                {diagnostics && (
                  <>
                    <pre>{diagnostics}</pre>
                    <button
                      onClick={() => {
                        const url = URL.createObjectURL(
                          new Blob([diagnostics], { type: "application/json" }),
                        );
                        const a = document.createElement("a");
                        a.href = url;
                        a.download = "questionnaire-diagnostics.json";
                        a.click();
                        setTimeout(() => URL.revokeObjectURL(url), 1000);
                      }}
                    >
                      Export reviewed diagnostics
                    </button>
                  </>
                )}
                <p className="muted">
                  Diagnostics contain versions and capability state, not keys,
                  private values or full answers.
                </p>
              </section>
              <section className="card">
                <h2>Data portability</h2>
                <Unavailable>
                  Backup, restore, export and coordinated data deletion are
                  unavailable.
                </Unavailable>
                <p className="muted">
                  Windows uninstall offers a separate explicit choice to retain
                  or delete application data. Do not delete files while the
                  companion is running.
                </p>
              </section>
            </>
          )}
          {busy && <Notice>Working with the local application…</Notice>}
        </main>
      </div>
      <footer>
        SocratesOne Development LLC · Local storage · No external analytics
      </footer>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
