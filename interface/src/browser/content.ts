import { eligible, questionFor, valueOf, assignText, mayUndo } from "./fields";
import type { Page, Field, Target } from "../integration/types";
const global = window as unknown as { __questionnaire?: boolean };
if (!global.__questionnaire) {
  global.__questionnaire = true;
  start();
}
function start() {
  const documentToken = crypto.randomUUID();
  const ids = new WeakMap<HTMLElement, string>(),
    groups = new WeakMap<Element, string>();
  const elements = new Map<string, HTMLElement>(),
    versions = new Map<string, number>();
  const undo = new Map<
    string,
    { before: string; inserted: string; signature: string }
  >();
  let activeId: string | undefined,
    fields: Field[] = [],
    timer: number | undefined,
    reportTimer: number | undefined,
    hidden = false;
  const controls = document.createElement("div");
  controls.dataset.questionnaireControls = "true";
  const shadow = controls.attachShadow({ mode: "closed" });
  shadow.innerHTML =
    '<style>:host{all:initial;position:fixed;z-index:2147483647}div{display:flex;gap:4px;padding:4px;background:#fff;border:1px solid #b9c7c2;border-radius:8px;box-shadow:0 3px 12px #0002}button{font:12px system-ui;padding:6px;border:0;border-radius:4px;background:#edf4f0;color:#173f32;cursor:pointer}button:focus-visible{outline:2px solid #00674b}</style><div><button>Saved answers</button><button>AI help</button><button aria-label="Hide assistance on this page">×</button></div>';
  const buttons = shadow.querySelectorAll("button");
  buttons.forEach((button, index) =>
    button.addEventListener("click", (event) => {
      if (!event.isTrusted) return;
      if (index === 2) {
        hidden = true;
        controls.remove();
        return;
      }
      void chrome.runtime.sendMessage({
        type: "open",
        mode: index === 0 ? "saved" : "ai",
        activeId,
      });
    }),
  );
  function field(el: HTMLElement): Field {
    let id = ids.get(el);
    if (!id) {
      id = crypto.randomUUID();
      ids.set(el, id);
      elements.set(id, el);
      versions.set(id, 0);
    }
    const group = el.closest('form,fieldset,[role="form"]') || document.body;
    let formId = groups.get(group);
    if (!formId) {
      formId = crypto.randomUUID();
      groups.set(group, formId);
    }
    const max = "maxLength" in el ? (el as HTMLInputElement).maxLength : -1;
    const constraints = {
      ...(max > 0 ? { max_length: max } : {}),
      required: el.hasAttribute("required"),
    };
    const question = questionFor(el),
      signature = JSON.stringify([formId, question, constraints]);
    return {
      id,
      formId,
      question,
      constraints,
      prefilled: !!valueOf(el),
      version: versions.get(id) || 0,
      signature,
    };
  }
  function snapshot(): Page {
    return {
      documentToken,
      url: location.origin + location.pathname,
      title: document.title.slice(0, 300),
      fields,
      activeId,
    };
  }
  function scan() {
    fields = Array.from(
      document.querySelectorAll<HTMLElement>(
        'input,textarea,[contenteditable="true"],[contenteditable="plaintext-only"]',
      ),
    )
      .filter((el) => eligible(el))
      .slice(0, 200)
      .map(field);
    for (const [id, el] of elements)
      if (!el.isConnected) {
        elements.delete(id);
        undo.delete(id);
        versions.delete(id);
      }
    void chrome.runtime
      .sendMessage({ type: "snapshot", page: snapshot() })
      .catch(() => {});
  }
  function schedule() {
    if (timer !== undefined) return;
    timer = window.setTimeout(() => {
      timer = undefined;
      scan();
    }, 180);
  }
  document.addEventListener(
    "input",
    (event) => {
      if (event.target instanceof HTMLElement) {
        const el = event.target,
          id = ids.get(el);
        if (id) {
          versions.set(id, (versions.get(id) || 0) + 1);
          fields = fields.map((f) => (f.id === id ? field(el) : f));
          if (reportTimer === undefined)
            reportTimer = window.setTimeout(() => {
              reportTimer = undefined;
              void chrome.runtime
                .sendMessage({ type: "snapshot", page: snapshot() })
                .catch(() => {});
            }, 180);
        }
      }
    },
    true,
  );
  document.addEventListener("focusin", (event) => {
    if (!(event.target instanceof HTMLElement) || !eligible(event.target))
      return;
    const f = field(event.target);
    activeId = f.id;
    scan();
    if (hidden) return;
    const rect = event.target.getBoundingClientRect();
    controls.style.left = `${Math.max(4, Math.min(rect.left, innerWidth - 260))}px`;
    controls.style.top = `${Math.min(innerHeight - 42, Math.max(4, rect.bottom + 4))}px`;
    document.documentElement.append(controls);
  });
  new MutationObserver((records) => {
    if (
      records.some((r) => {
        const el =
          r.target instanceof Element ? r.target : r.target.parentElement;
        if (el?.closest("[data-questionnaire-controls]")) return false;
        if (r.type === "characterData" && el?.closest("[contenteditable]"))
          return false;
        return true;
      })
    )
      schedule();
  }).observe(document.body, {
    subtree: true,
    childList: true,
    attributes: true,
    attributeFilter: [
      "disabled",
      "readonly",
      "hidden",
      "aria-label",
      "aria-labelledby",
      "maxlength",
      "required",
      "type",
      "autocomplete",
    ],
    characterData: true,
  });
  chrome.runtime.onMessage.addListener((message, sender, respond) => {
    if (sender.id !== chrome.runtime.id) return;
    if (message.type === "inspect") {
      scan();
      respond({ ok: true, data: snapshot() });
      return;
    }
    if (!["insert", "undo", "capture", "hide"].includes(message.type)) return;
    if (message.type === "hide") {
      hidden = true;
      controls.remove();
      respond({ ok: true });
      return;
    }
    const t = message.target as Target,
      el = elements.get(t?.id);
    if (
      !t ||
      t.documentToken !== documentToken ||
      !el ||
      !el.isConnected ||
      !eligible(el)
    ) {
      respond({ ok: false, error: "The field changed. Select it again." });
      return;
    }
    const current = field(el);
    if (current.formId !== t.formId || current.signature !== t.signature) {
      respond({ ok: false, error: "The question changed. Select it again." });
      return;
    }
    if (message.type === "capture") {
      respond({
        ok: true,
        data: { text: valueOf(el), question: current.question },
      });
      return;
    }
    if (message.type === "undo") {
      const previous = undo.get(t.id);
      if (
        !previous ||
        previous.signature !== current.signature ||
        !mayUndo(valueOf(el), previous.inserted)
      ) {
        respond({ ok: false, error: "Undo cannot replace subsequent edits." });
        return;
      }
      assignText(el, previous.before);
      undo.delete(t.id);
      respond({ ok: true, data: { restored: true } });
      scan();
      return;
    }
    if (
      current.version !== t.version ||
      (current.prefilled && !message.replace)
    ) {
      respond({
        ok: false,
        error:
          "The field was edited. Review the current field before replacing it.",
      });
      return;
    }
    if (
      typeof message.text !== "string" ||
      (current.constraints.max_length &&
        message.text.length > current.constraints.max_length)
    ) {
      respond({ ok: false, error: "The answer exceeds the field limit." });
      return;
    }
    const before = valueOf(el);
    el.focus();
    assignText(el, message.text);
    window.setTimeout(() => {
      if (!el.isConnected || valueOf(el) !== message.text) {
        respond({
          ok: false,
          error: "Insertion could not be verified. Use Copy.",
        });
        return;
      }
      undo.set(t.id, {
        before,
        inserted: message.text,
        signature: t.signature,
      });
      respond({ ok: true, data: { inserted: true } });
      scan();
    }, 120);
    return true;
  });
  scan();
}
