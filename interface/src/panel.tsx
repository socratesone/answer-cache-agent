import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Brand, Empty, Notice } from "./components/common";
import {
  extensionAvailable,
  getPage,
  host,
  pending,
  rpc,
} from "./integration/client";
import type {
  Page,
  Field,
  FormState,
  Result,
  Target,
  Match,
  Pending,
  HostInfo,
} from "./integration/types";
import type { CandidateOut } from "./generated/CandidateOut";
import "./styles.css";
function App() {
  const [page, setPage] = useState<Page | null>(null),
    [selected, setSelected] = useState(""),
    [mode, setMode] = useState<"saved" | "ai">("saved");
  const [info, setInfo] = useState<HostInfo | null>(null),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false),
    [query, setQuery] = useState("");
  const [matches, setMatches] = useState<Match[]>([]),
    [result, setResult] = useState<Result | null>(null),
    [candidate, setCandidate] = useState<CandidateOut | null>(null);
  const [body, setBody] = useState(""),
    [rendered, setRendered] = useState(""),
    [problems, setProblems] = useState<string[]>([]),
    [editing, setEditing] = useState(false);
  const [batch, setBatch] = useState(false),
    [included, setIncluded] = useState<string[]>([]),
    [replace, setReplace] = useState(false),
    [question, setQuestion] = useState("");
  const [hintDim, setHintDim] = useState(""),
    [hintValue, setHintValue] = useState(""),
    [reason, setReason] = useState("wrong_emphasis"),
    [feedback, setFeedback] = useState("");
  const [recover, setRecover] = useState<Pending[]>([]),
    [savedBody, setSavedBody] = useState<string | null>(null);
  const operation = useRef<string | null>(null),
    stopped = useRef(false),
    version = useRef(0),
    session = useRef<FormState | null>(null);
  const field = page?.fields.find((f) => f.id === selected),
    formFields = page?.fields.filter((f) => f.formId === field?.formId) || [];
  const formKey = page && field ? `${page.documentToken}:${field.formId}` : "";
  const currentTarget = (): Target => {
    if (!page || !field || !page.tabId || !page.documentId)
      throw Error("Select a field first");
    return {
      ...field,
      documentToken: page.documentToken,
      tabId: page.tabId,
      documentId: page.documentId,
    };
  };
  const previewTarget = useRef<Target | null>(null),
    lastFocus = useRef(""),
    lastIntent = useRef("");
  async function attempt(fn: () => Promise<void>) {
    setBusy(true);
    setMessage("");
    try {
      await fn();
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
      operation.current = null;
    }
  }
  useEffect(() => {
    if (!extensionAvailable) return;
    const update = () =>
      getPage()
        .then((p) => {
          setPage(p);
          const focusKey = `${p?.documentToken}:${p?.activeId}`;
          const changedFocus = focusKey !== lastFocus.current;
          lastFocus.current = focusKey;
          setSelected((old) =>
            changedFocus && p?.activeId
              ? p.activeId
              : p?.fields.some((f) => f.id === old)
                ? old
                : p?.activeId || p?.fields[0]?.id || "",
          );
        })
        .catch((e) => setMessage(e.message));
    void update();
    void host<HostInfo>("hello")
      .then(setInfo)
      .catch((e) =>
        setMessage(
          `Companion unavailable: ${e.message}. Install the local application, then reconnect.`,
        ),
      );
    void pending().then(setRecover);
    const changed = () => {
      void update();
    };
    chrome.storage.onChanged.addListener(changed);
    chrome.tabs.onActivated.addListener(changed);
    return () => {
      chrome.storage.onChanged.removeListener(changed);
      chrome.tabs.onActivated.removeListener(changed);
    };
  }, []);
  useEffect(() => {
    version.current++;
    setCandidate(null);
    setResult(null);
    setBody("");
    setRendered("");
    setMatches([]);
    setBatch(false);
    setReplace(false);
    setQuestion(field?.question || "");
    setQuery(field?.question || "");
    setSavedBody(null);
    previewTarget.current = null;
  }, [page?.documentToken, selected, field?.signature]);
  useEffect(() => {
    session.current = null;
  }, [formKey]);
  useEffect(() => {
    const intent = page?.intent;
    if (!intent || intent.id === lastIntent.current) return;
    if (intent.fieldId !== selected) {
      setSelected(intent.fieldId);
      return;
    }
    lastIntent.current = intent.id;
    setMode(intent.mode);
    if (intent.mode === "ai" && !busy) void attempt(() => cached());
  }, [page?.intent?.id, selected]);
  async function engine(
    type: string,
    payload: Record<string, unknown>,
    authorized = false,
  ): Promise<Result> {
    if (!page || !field) throw Error("Select a field first");
    let state =
      session.current ||
      (await rpc<FormState | null>("state.get", { key: formKey }));
    const hints =
      hintDim.trim() && hintValue.trim()
        ? [
            {
              dimension: hintDim.trim(),
              value: hintValue.trim(),
              source: "user" as const,
            },
          ]
        : [];
    const prepare = {
      questions: formFields.map((f) => ({
        id: f.id,
        text: f.id === selected ? question : f.question,
        constraints: f.constraints,
        prefilled: f.prefilled,
      })),
      page_url: page.url,
      hints,
    };
    const prepareKey = JSON.stringify(prepare);
    if (!state)
      state = {
        sessionId: crypto.randomUUID(),
        revision: null,
        prepared: false,
        formId: field.formId,
        hints,
      };
    async function send(
      eventType: string,
      eventPayload: Record<string, unknown>,
      auth = false,
    ) {
      const id = crypto.randomUUID();
      operation.current = id;
      const r = await host<Result>(
        "event",
        {
          event: {
            event_id: id,
            session_id: state!.sessionId,
            scope_id: "user-default",
            type: eventType,
            expected_revision: state!.revision,
            payload: eventPayload,
          },
          authorized: auth,
        },
        id,
      );
      if (r.revision) state!.revision = r.revision;
      await rpc("state.set", { key: formKey, state });
      session.current = state;
      if (r.status === "stale_context")
        throw Error(
          "Form context changed. Refresh the form before requesting another action.",
        );
      return r;
    }
    if (!state.prepared || state.prepareKey !== prepareKey) {
      const r = await send(
        state.prepared ? "update_form" : "prepare_form",
        prepare,
      );
      if (r.status !== "ready") throw Error("Could not prepare this form");
      state.prepared = true;
      state.prepareKey = prepareKey;
      state.hints = hints;
      session.current = state;
      await rpc("state.set", { key: formKey, state });
    }
    if (stopped.current && authorized)
      throw Error("Stopped before generation started.");
    return send(type, payload, authorized);
  }
  async function show(
    bodyText: string,
    c: CandidateOut | null,
    available: CandidateOut[] = [],
  ) {
    const token = version.current,
      target = currentTarget();
    const r = await host<{ text: string | null; problems: string[] }>(
      "render",
      { body: bodyText, constraints: field!.constraints },
    );
    if (token !== version.current || stopped.current) return;
    setBody(bodyText);
    setRendered(r.text || "");
    setProblems(r.problems);
    setCandidate(c);
    setEditing(false);
    previewTarget.current = target;
    if (c) {
      await new Promise((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(resolve)),
      );
      if (token === version.current)
        await engine("record_feedback", {
          outcome: "shown",
          shown: [c.id],
          alternatives: available
            .filter((item) => item.id !== c.id)
            .map((item) => item.id),
        });
    }
  }
  async function receive(r: Result, token: number) {
    if (token !== version.current || stopped.current) {
      setMessage(
        "The operation finished. Select the original question to retrieve its saved candidates; nothing was inserted.",
      );
      return;
    }
    setResult(r);
    const first = r.candidates?.[0];
    if (first) await show(first.body, first, r.candidates || []);
    else
      setMessage(
        (r.unresolved || []).map((u) => u.needed || u.reason).join("; ") ||
          "No cached answer is available. Generation requires your approval.",
      );
  }
  async function cached(variant?: string) {
    stopped.current = false;
    const token = version.current;
    await receive(
      await engine("get_candidate", {
        question_id: selected,
        ...(variant ? { variant } : {}),
      }),
      token,
    );
  }
  async function generate(regenerate = false) {
    stopped.current = false;
    const token = version.current;
    const r = await engine(
      regenerate ? "regenerate_question" : "generate_initial",
      regenerate
        ? { question_id: selected }
        : {
            target_question_ids: [selected],
            authorized_question_ids: included,
          },
      true,
    );
    setBatch(false);
    await receive(r, token);
  }
  async function useAnswer() {
    const target = previewTarget.current;
    if (!target) throw Error("Preview this answer again before inserting");
    const check = await host<{ text: string | null; problems: string[] }>(
      "render",
      { body, constraints: field!.constraints },
    );
    if (check.problems.length || check.text === null)
      throw Error(check.problems.join("; "));
    if (check.text !== rendered) {
      setRendered(check.text);
      setProblems(check.problems);
      previewTarget.current = currentTarget();
      throw Error(
        "The resolved answer changed. Review the updated preview, then choose Use answer again.",
      );
    }
    await rpc("insert", { target, text: check.text, replace });
    setMessage("Answer inserted. It is now visible to this website.");
    if (candidate) {
      if (body !== candidate.body)
        await engine("record_feedback", {
          outcome: "edited",
          candidate_id: candidate.id,
          edited_body: body,
        });
      await engine("record_feedback", {
        outcome: "selected",
        candidate_id: candidate.id,
      });
    }
  }
  async function refresh() {
    session.current = null;
    await rpc("state.set", { key: formKey, state: null });
    setBody("");
    setRendered("");
    setCandidate(null);
    setResult(null);
    setMessage(
      "Fresh form session ready. Cached answers from the previous session will not be reused.",
    );
  }
  return (
    <div className="panel">
      <Brand>
        <a href="manage.html" target="_blank">
          Manage
        </a>
      </Brand>
      <main>
        <div className="eyebrow">Your local writing companion</div>
        <h1>A little less repetition.</h1>
        <p className="muted">
          Reuse an answer you trust, or ask for help when you need it.
        </p>
        {message && <Notice>{message}</Notice>}
        {!info && (
          <div className="card">
            <h2>Connect your local application</h2>
            <p className="muted">
              Your answers stay on this computer. The companion handles storage
              and model requests.
            </p>
            <a href="manage.html">Installation & settings</a>
            <div className="actions">
              <button
                onClick={() =>
                  attempt(async () => {
                    setInfo(await host("hello"));
                    setRecover(await pending());
                  })
                }
              >
                Reconnect
              </button>
            </div>
          </div>
        )}
        {recover.length > 0 && (
          <section className="card">
            <h2>Interrupted operations</h2>
            <p className="muted">
              Reconcile using the original event. This may resume previously
              authorized work; it does not authorize a new request. Results will
              not be inserted automatically.
            </p>
            {recover.map((p) => (
              <button
                key={p.id}
                disabled={busy || p.stopped}
                onClick={() =>
                  attempt(async () => {
                    await host(p.operation, p.data, p.id);
                    setRecover(await pending());
                    setMessage(
                      "Operation reconciled. Retrieve cached answers from the original form.",
                    );
                  })
                }
              >
                {p.stopped
                  ? "Stopped — active work may have finished"
                  : "Reconcile interrupted action"}
              </button>
            ))}
          </section>
        )}
        {!page ? (
          <Empty title="Start with a form">
            Open a website, then click the extension toolbar button. Ordinary
            text fields are supported; browser settings pages and cross-origin
            embedded forms are not.
          </Empty>
        ) : (
          <>
            <div className="card">
              <div className="eyebrow">Current website</div>
              <div className="site">{page.url}</div>
              <div className="row between">
                <span className="tag">
                  {page.fields.length} supported fields
                </span>
                <button disabled={busy} onClick={() => attempt(refresh)}>
                  Refresh form
                </button>
              </div>
            </div>
            <label>
              Form or section
              <select
                value={field?.formId || ""}
                onChange={(e) =>
                  setSelected(
                    page.fields.find((f) => f.formId === e.target.value)?.id ||
                      "",
                  )
                }
              >
                {[...new Set(page.fields.map((f) => f.formId))].map((id, i) => (
                  <option key={id} value={id}>
                    Section {i + 1} ·{" "}
                    {page.fields
                      .find((f) => f.formId === id)
                      ?.question.slice(0, 30)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Question
              <select
                value={selected}
                onChange={(e) => setSelected(e.target.value)}
              >
                {formFields.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.question}
                    {f.prefilled ? " · has text" : ""}
                  </option>
                ))}
              </select>
            </label>
            {field && (
              <>
                <details>
                  <summary>Question & context details</summary>
                  <label>
                    Interpreted question
                    <input
                      value={question}
                      onChange={(e) => setQuestion(e.target.value)}
                    />
                  </label>
                  <p className="muted">
                    Question text, constraints, the page URL without
                    query/fragment, and chosen categories are eligible for model
                    context. Existing field answers and full-page text are
                    omitted.
                  </p>
                  <label>
                    Category ID
                    <input
                      value={hintDim}
                      onChange={(e) => setHintDim(e.target.value)}
                    />
                  </label>
                  <label>
                    Value ID
                    <input
                      value={hintValue}
                      onChange={(e) => setHintValue(e.target.value)}
                    />
                  </label>
                  <p className="muted">
                    Use IDs from categories you created in Settings. Named
                    category browsing awaits the engine listing service. No
                    automatic classification.
                  </p>
                </details>
                <p className="muted">
                  {hintDim && hintValue
                    ? `Context: ${hintDim} / ${hintValue}`
                    : "No category selected"}
                  {field.constraints.max_length
                    ? ` · ${field.constraints.max_length} character limit`
                    : ""}
                </p>
                <div className="tabs" aria-label="Answer source">
                  <button
                    aria-pressed={mode === "saved"}
                    onClick={() => setMode("saved")}
                  >
                    Saved answers
                  </button>
                  <button
                    aria-pressed={mode === "ai"}
                    onClick={() => {
                      setMode("ai");
                      if (!busy) void attempt(() => cached());
                    }}
                  >
                    AI help
                  </button>
                </div>
                {mode === "saved" ? (
                  <>
                    <label>
                      Search your local answers
                      <input
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                      />
                    </label>
                    <button
                      disabled={busy || !info}
                      onClick={() =>
                        attempt(async () => {
                          stopped.current = false;
                          const r = await host<{ matches: Match[] }>("search", {
                            query,
                            hints:
                              hintDim && hintValue
                                ? [
                                    {
                                      dimension: hintDim,
                                      value: hintValue,
                                      source: "user",
                                    },
                                  ]
                                : [],
                          });
                          setMatches(r.matches);
                          if (!r.matches.length)
                            setMessage(
                              "No saved match found. Save an answer to begin.",
                            );
                        })
                      }
                    >
                      Find saved answers
                    </button>
                    <p className="muted">
                      Local semantic suggestions. No model call or automatic
                      fill.
                    </p>
                    {matches.map((m) => (
                      <article className="card" key={m.id}>
                        <span className="tag">Approved for reuse</span>
                        <h3>{m.intent}</h3>
                        <p className="answer">{m.body.slice(0, 180)}</p>
                        <button
                          disabled={busy}
                          onClick={() => attempt(() => show(m.body, null))}
                        >
                          Preview answer
                        </button>
                        <details>
                          <summary>Match details</summary>
                          <p>
                            Local similarity: {m.similarity.toFixed(3)}. This
                            list is not exhaustive.
                          </p>
                        </details>
                      </article>
                    ))}
                  </>
                ) : (
                  <>
                    <div className="row">
                      <button
                        disabled={busy || !info}
                        onClick={() => attempt(() => cached())}
                      >
                        Saved candidates
                      </button>
                      <button
                        disabled={busy || !info}
                        onClick={() => attempt(() => cached("concise"))}
                      >
                        Use concise version
                      </button>
                    </div>
                    <div className="actions">
                      <button
                        className="primary"
                        disabled={busy || !info}
                        onClick={() => {
                          setIncluded(
                            formFields
                              .filter((f) => !f.prefilled && f.id !== selected)
                              .map((f) => f.id),
                          );
                          setBatch(true);
                        }}
                      >
                        Generate answers…
                      </button>
                    </div>
                  </>
                )}
                {batch && (
                  <section className="card">
                    <h2>Review before generating</h2>
                    <p>
                      Prepare answers for these questions. Insert only an answer
                      you choose.
                    </p>
                    <label className="check">
                      <input type="checkbox" checked disabled />
                      {question}
                    </label>
                    {formFields
                      .filter((f) => f.id !== selected)
                      .map((f) => (
                        <label className="check" key={f.id}>
                          <input
                            type="checkbox"
                            checked={included.includes(f.id)}
                            onChange={(e) =>
                              setIncluded((old) =>
                                e.target.checked
                                  ? [...old, f.id]
                                  : old.filter((id) => id !== f.id),
                              )
                            }
                          />
                          {f.question}
                          {f.prefilled ? " (already has text)" : ""}
                        </label>
                      ))}
                    <p className="muted">
                      Session budget: $
                      {info?.budget.max_session_cost_usd.toFixed(2)}. Calls may
                      incur provider charges. Cost is not a billing guarantee.
                    </p>
                    <button
                      className="primary"
                      disabled={busy || !info?.generationReady}
                      onClick={() => attempt(() => generate())}
                    >
                      Authorize generation
                    </button>
                    {!info?.generationReady && (
                      <p className="muted">
                        Configure both model roles and provider credentials in
                        Settings first.
                      </p>
                    )}
                  </section>
                )}
                {mode === "ai" &&
                  result?.candidates &&
                  result.candidates.length > 1 && (
                    <div className="actions" aria-label="Available candidates">
                      {result.candidates.map((c, i) => (
                        <button
                          key={c.id}
                          disabled={busy}
                          aria-pressed={candidate?.id === c.id}
                          onClick={() =>
                            attempt(() =>
                              show(c.body, c, result.candidates || []),
                            )
                          }
                        >
                          {c.variant === "alternative"
                            ? `Alternative ${i + 1}`
                            : c.variant === "concise"
                              ? "Concise version"
                              : "Standard version"}
                        </button>
                      ))}
                    </div>
                  )}
                {body && (
                  <section className="card">
                    <div className="row between">
                      <span className={`tag ${candidate ? "generated" : ""}`}>
                        {candidate ? "Saved candidate" : "Saved answer preview"}
                      </span>
                      <button onClick={() => setEditing(!editing)}>
                        {editing ? "Close editor" : "Edit"}
                      </button>
                    </div>
                    {editing ? (
                      <>
                        <label>
                          Reusable wording (keep private values as placeholders)
                          <textarea
                            value={body}
                            onChange={(e) => setBody(e.target.value)}
                          />
                        </label>
                        <button
                          onClick={() =>
                            attempt(async () => {
                              const r = await host("render", {
                                body,
                                constraints: field.constraints,
                              });
                              setRendered(r.text || "");
                              setProblems(r.problems);
                              previewTarget.current = currentTarget();
                            })
                          }
                        >
                          Update preview
                        </button>
                      </>
                    ) : null}
                    <p className="answer">{rendered}</p>
                    {problems.length > 0 && (
                      <Notice>{problems.join("; ")}</Notice>
                    )}
                    {field.prefilled && (
                      <label className="check">
                        <input
                          type="checkbox"
                          checked={replace}
                          onChange={(e) => {
                            setReplace(e.target.checked);
                            previewTarget.current = currentTarget();
                          }}
                        />
                        Replace the current field text
                      </label>
                    )}
                    <div className="actions">
                      <button
                        className="primary"
                        disabled={
                          busy ||
                          !!problems.length ||
                          !rendered ||
                          (field.prefilled && !replace)
                        }
                        onClick={() => attempt(useAnswer)}
                      >
                        Use answer
                      </button>
                      <button
                        disabled={!rendered}
                        onClick={() =>
                          attempt(async () => {
                            await navigator.clipboard.writeText(rendered);
                            setMessage(
                              "Copied. Paste only where you intend to disclose this answer.",
                            );
                          })
                        }
                      >
                        Copy
                      </button>
                      <button
                        disabled={busy}
                        onClick={() =>
                          attempt(async () => {
                            await rpc("undo", { target: currentTarget() });
                            setMessage("Previous value restored.");
                          })
                        }
                      >
                        Undo
                      </button>
                    </div>
                    <p className="muted">
                      Inserting an answer discloses it to this website
                      immediately.
                    </p>
                    {candidate && (
                      <>
                        <div className="actions">
                          <button
                            disabled={busy || body !== candidate.body}
                            onClick={() =>
                              attempt(async () => {
                                await engine("record_feedback", {
                                  outcome: "approved",
                                  candidate_id: candidate.id,
                                  approve_as_template_id: `T_${crypto.randomUUID().replaceAll("-", "")}`,
                                });
                                setMessage(
                                  "Approved as reusable wording, not factual evidence.",
                                );
                              })
                            }
                          >
                            Approve for reuse
                          </button>
                          <button
                            disabled={busy || !info?.generationReady}
                            onClick={() => {
                              setIncluded([]);
                              setBatch(true);
                            }}
                          >
                            Review generation scope
                          </button>
                          <button
                            disabled={busy || !info?.generationReady}
                            onClick={() => {
                              if (
                                window.confirm(
                                  "Authorize paid generation of new alternatives for this question?",
                                )
                              )
                                void attempt(() => generate(true));
                            }}
                          >
                            Generate new alternatives
                          </button>
                        </div>
                        <details>
                          <summary>Reject this candidate</summary>
                          <label>
                            Reason
                            <select
                              value={reason}
                              onChange={(e) => setReason(e.target.value)}
                            >
                              <option value="wrong_emphasis">
                                Wrong emphasis
                              </option>
                              <option value="too_generic">Too generic</option>
                              <option value="inaccurate">
                                Incorrect information
                              </option>
                              <option value="other">Other</option>
                            </select>
                          </label>
                          <label>
                            Optional feedback (model-visible)
                            <textarea
                              value={feedback}
                              onChange={(e) => setFeedback(e.target.value)}
                            />
                          </label>
                          <button
                            disabled={busy}
                            onClick={() =>
                              attempt(async () => {
                                await engine("record_feedback", {
                                  outcome: "rejected",
                                  candidate_id: candidate.id,
                                  reasons: [reason],
                                  free_text: feedback || null,
                                });
                                setMessage(
                                  "Explicit rejection recorded. Other candidates were not rejected.",
                                );
                              })
                            }
                          >
                            Reject shown candidate
                          </button>
                        </details>
                        <details>
                          <summary>Evidence & evaluation details</summary>
                          <pre>
                            {JSON.stringify(
                              {
                                evidence: candidate.evidence_refs,
                                templates: candidate.template_refs,
                                validation: candidate.validation,
                                selfReport: candidate.self_report,
                              },
                              null,
                              2,
                            )}
                          </pre>
                          <p className="muted">
                            A model self-report is not independent factual
                            verification.
                          </p>
                        </details>
                      </>
                    )}
                  </section>
                )}
                {result && (
                  <section className="card">
                    <strong>{result.status.replaceAll("_", " ")}</strong>
                    {(result.unresolved || []).map((u, i) => (
                      <p key={i}>{u.needed || u.reason.replaceAll("_", " ")}</p>
                    ))}
                    <details>
                      <summary>Usage & operation details</summary>
                      <p>
                        {result.usage?.calls || 0} calls ·{" "}
                        {result.usage?.tokens || 0} recorded/estimated tokens
                      </p>
                      <p>
                        Engine cost estimate: ${result.usage?.cost_usd ?? 0}.
                        Actual provider cost may be unknown.
                        {!!result.usage?.uncertain &&
                          " A paid response is uncertain. Do not retry without reviewing potential charges."}
                      </p>
                      <p className="muted">{result.diagnostics?.join("; ")}</p>
                    </details>
                  </section>
                )}
                <div className="divider" />
                <button
                  disabled={busy}
                  onClick={() =>
                    attempt(async () => {
                      const r = await rpc<{ text: string }>("capture", {
                        target: currentTarget(),
                      });
                      setSavedBody(r.text);
                    })
                  }
                >
                  Save this field’s answer
                </button>
                {savedBody !== null && (
                  <section className="card">
                    <h2>Save for local reuse</h2>
                    <label>
                      Review the answer
                      <textarea
                        value={savedBody}
                        onChange={(e) => setSavedBody(e.target.value)}
                      />
                    </label>
                    <p className="muted">
                      Saved as local-only. To use a template in model context,
                      author symbolic wording in Manage answers.
                    </p>
                    <button
                      disabled={busy || !savedBody}
                      onClick={() =>
                        attempt(async () => {
                          const id = `T_${crypto.randomUUID().replaceAll("-", "")}`;
                          await host("ingest", {
                            record: {
                              kind: "template",
                              id,
                              intent: question,
                              aliases: [question],
                              body: savedBody,
                              variables: [],
                              evidence: [],
                              context: [],
                              disclosure: "local_only",
                              approved_by: "user",
                              approved_at: new Date().toISOString(),
                            },
                          });
                          setSavedBody(null);
                          await refresh();
                          setMessage(
                            "Saved locally. Search Saved answers to reuse it.",
                          );
                        })
                      }
                    >
                      Approve & save locally
                    </button>
                  </section>
                )}
              </>
            )}
          </>
        )}
        {busy && (
          <Notice>
            Working locally or waiting for the provider.{" "}
            <button
              onClick={() => {
                stopped.current = true;
                version.current++;
                if (operation.current)
                  void rpc("stop", { id: operation.current }).catch(() => {});
                setMessage(
                  "Stopped queued work and disabled late results. An active provider call may finish and incur charges.",
                );
              }}
            >
              Stop
            </button>
          </Notice>
        )}
      </main>
      <footer>Local by default. Generation by choice.</footer>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
