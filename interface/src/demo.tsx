import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import { host } from "./integration/client";
import { assignText, valueOf, mayUndo } from "./browser/fields";
function Demo() {
  const [replace, setReplace] = useState(0),
    [extra, setExtra] = useState(false),
    [notice, setNotice] = useState(""),
    [preview, setPreview] = useState(""),
    [before, setBefore] = useState<string | null>(null);
  async function lookup() {
    try {
      const r = await host("search", {
        query: "Why are you interested in this role?",
      });
      if (!r.matches.length) {
        setNotice(
          "Create a saved answer for this question in Manage answers first.",
        );
        return;
      }
      const rendered = await host("render", {
        body: r.matches[0].body,
        constraints: { max_length: 600 },
      });
      if (rendered.problems.length) {
        setNotice(rendered.problems.join("; "));
        return;
      }
      setPreview(rendered.text);
      setNotice("Local preview ready. No model request was made.");
    } catch (e) {
      setNotice((e as Error).message);
    }
  }
  return (
    <main className="demo">
      <div className="eyebrow">Synthetic practice form</div>
      <h1>A safe place to try your answers.</h1>
      <p>
        All examples here are fictional. This form never submits or sends data
        anywhere.
      </p>
      <section className="card">
        <h2>Provider-free demonstration</h2>
        <p>
          Create an answer for “Why are you interested in this role?” in{" "}
          <a href="manage.html" target="_blank">
            Manage answers
          </a>
          , then try local reuse here.
        </p>
        <button onClick={lookup}>Find my saved answer</button>
        {notice && <p role="status">{notice}</p>}
        {preview && (
          <>
            <p className="answer">{preview}</p>
            <button
              onClick={() => {
                const el =
                  document.querySelector<HTMLTextAreaElement>(
                    "#practice-answer",
                  )!;
                if (valueOf(el)) {
                  setNotice("Clear the practice field before inserting.");
                  return;
                }
                setBefore(valueOf(el));
                assignText(el, preview);
                setNotice("Inserted into this local practice form.");
              }}
            >
              Insert into practice field
            </button>
            <button
              disabled={before === null}
              onClick={() => {
                const el =
                  document.querySelector<HTMLTextAreaElement>(
                    "#practice-answer",
                  )!;
                if (!mayUndo(valueOf(el), preview)) {
                  setNotice("Undo will not erase your later edits.");
                  return;
                }
                assignText(el, before || "");
                setBefore(null);
              }}
            >
              Undo practice insertion
            </button>
          </>
        )}
      </section>
      <form onSubmit={(e) => e.preventDefault()}>
        <h2>Example application</h2>
        <label>
          Why are you interested in this role?
          <textarea id="practice-answer" maxLength={600} />
        </label>
        <label>
          Describe your strongest technical skill.
          <textarea key={replace} maxLength={400} />
        </label>
        <button type="button" onClick={() => setReplace((n) => n + 1)}>
          Replace skill field
        </button>
        <label>
          Short introduction
          <input maxLength={80} />
        </label>
        <label>
          Existing answer
          <textarea defaultValue="Synthetic example — preserve my edits." />
        </label>
        <label>
          Plain text editable region
          <div
            contentEditable="plaintext-only"
            aria-label="Plain text editable region"
          />
        </label>
        <button type="button" onClick={() => setExtra(!extra)}>
          Toggle another question
        </button>
        {extra && (
          <label>
            Would you consider moving for this role?
            <textarea />
          </label>
        )}
      </form>
      <form onSubmit={(e) => e.preventDefault()}>
        <h2>Independent second form</h2>
        <label>
          Why are you interested in this role?
          <textarea />
        </label>
        <label>
          Password (excluded)
          <input type="password" />
        </label>
        <label>
          One-time authentication code (excluded)
          <input autoComplete="one-time-code" />
        </label>
        <label>
          Read-only text (excluded)
          <input readOnly value="Synthetic fixed value" />
        </label>
        <input type="hidden" value="Do not capture" />
        <label>
          Unsupported selection
          <select>
            <option>Manual choice only</option>
          </select>
        </label>
      </form>
      <p>
        This local demonstration uses the same insertion helper. To test actual
        website detection, serve this page over localhost using the developer
        instructions.
      </p>
    </main>
  );
}
createRoot(document.getElementById("root")!).render(<Demo />);
