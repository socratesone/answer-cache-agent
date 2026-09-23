import contract from "../generated/contract.json";
import { trustedPage, supportedUrl } from "./security";
import type { Page, Pending, Target } from "../integration/types";
const HOST = "com.socratesone.questionnaire";
let port: chrome.runtime.Port | undefined;
const waiting = new Map<
  string,
  { resolve: (v: any) => void; reject: (e: Error) => void }
>();
const ready = chrome.storage.session.setAccessLevel({
  accessLevel: "TRUSTED_CONTEXTS",
});
async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}
async function native(
  operation: string,
  data: Record<string, unknown>,
  id: string,
): Promise<any> {
  if (waiting.has(id)) throw new Error("This operation is already running.");
  if (!port) {
    port = chrome.runtime.connectNative(HOST);
    port.onMessage.addListener((reply) => {
      const job = waiting.get(reply.id);
      if (!job) return;
      waiting.delete(reply.id);
      reply.ok
        ? job.resolve(reply.data)
        : job.reject(new Error(reply.error || "Local operation failed"));
    });
    port.onDisconnect.addListener(() => {
      const message =
        chrome.runtime.lastError?.message || "Companion disconnected";
      port = undefined;
      for (const job of waiting.values()) job.reject(new Error(message));
      waiting.clear();
    });
  }
  return new Promise((resolve, reject) => {
    waiting.set(id, { resolve, reject });
    try {
      port!.postMessage({
        id,
        operation,
        data,
        protocol: contract.protocol,
        fingerprint: contract.fingerprint,
      });
    } catch (e) {
      waiting.delete(id);
      reject(e);
    }
  });
}
async function getPage() {
  await ready;
  const tab = await activeTab();
  if (!tab?.id) return null;
  const key = `page:${tab.id}`;
  const page = ((await chrome.storage.session.get(key))[key] as Page) || null;
  const intent = (await chrome.storage.session.get(`intent:${tab.id}`))[
    `intent:${tab.id}`
  ];
  return page && intent?.documentId === page.documentId
    ? { ...page, intent }
    : page;
}
chrome.action.onClicked.addListener((tab) => {
  if (!tab.id) return;
  void chrome.sidePanel.open({ tabId: tab.id }); // Invoke while Chrome's user gesture is still active.
  if (supportedUrl(tab.url || ""))
    void chrome.scripting
      .executeScript({ target: { tabId: tab.id }, files: ["content.js"] })
      .catch(() => {});
});
chrome.tabs.onRemoved.addListener((id) => {
  void chrome.storage.session.remove(`page:${id}`);
});
chrome.tabs.onUpdated.addListener((id, change) => {
  if (change.status === "loading" || change.url)
    void chrome.storage.session.remove(`page:${id}`);
});
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  const run = async () => {
    await ready;
    if (sender.id !== chrome.runtime.id) throw new Error("Untrusted sender");
    if (sender.tab && !trustedPage(sender, chrome.runtime.id)) {
      if (
        sender.frameId !== 0 ||
        !sender.documentId ||
        !sender.tab.id ||
        !supportedUrl(sender.url || "")
      )
        throw new Error("Unsupported frame");
      if (message.type === "snapshot") {
        const p = message.page as Page;
        if (
          !p ||
          !Array.isArray(p.fields) ||
          p.fields.length > 200 ||
          typeof p.documentToken !== "string" ||
          p.fields.some(
            (f) =>
              typeof f.question !== "string" ||
              f.question.length > 2000 ||
              typeof f.id !== "string",
          )
        )
          throw new Error("Invalid field report");
        const u = new URL(sender.url!);
        const page: Page = {
          documentToken: p.documentToken,
          url: u.origin + u.pathname,
          title: String(p.title).slice(0, 300),
          fields: p.fields,
          activeId: p.activeId,
          tabId: sender.tab.id,
          documentId: sender.documentId,
        };
        await chrome.storage.session.set({ [`page:${sender.tab.id}`]: page });
        return null;
      }
      if (message.type === "open") {
        await chrome.sidePanel.open({ tabId: sender.tab.id });
        await chrome.storage.session.set({
          [`intent:${sender.tab.id}`]: {
            id: crypto.randomUUID(),
            documentId: sender.documentId,
            fieldId: message.activeId,
            mode: message.mode === "ai" ? "ai" : "saved",
          },
        });
        return null;
      }
      throw new Error(
        "Webpage adapters cannot read local data or authorize operations",
      );
    }
    if (!trustedPage(sender, chrome.runtime.id))
      throw new Error("Open the trusted panel or settings page");
    if (message.type === "page") return getPage();
    if (message.type === "activate") {
      const tab = await activeTab();
      if (!tab?.id || !supportedUrl(tab.url || ""))
        throw new Error(
          "Activate on an ordinary HTTP or HTTPS page. Chrome internal pages are unsupported.",
        );
      await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        files: ["content.js"],
      });
      const reply = await chrome.tabs.sendMessage(
        tab.id,
        { type: "inspect" },
        { frameId: 0 },
      );
      if (!reply.ok) throw new Error(reply.error);
      return getPage();
    }
    if (message.type === "pending") {
      const all = await chrome.storage.session.get(null);
      return Object.entries(all)
        .filter(([k]) => k.startsWith("pending:"))
        .map(([, v]) => v);
    }
    if (message.type === "stop") {
      const key = `pending:${message.id}`,
        old = (await chrome.storage.session.get(key))[key];
      if (old)
        await chrome.storage.session.set({ [key]: { ...old, stopped: true } });
      return native("stop", { requestId: message.id }, crypto.randomUUID());
    }
    if (message.type === "host") {
      const { operation, data, id } = message;
      if (
        typeof id !== "string" ||
        ![
          "hello",
          "event",
          "render",
          "search",
          "ingest",
          "variables",
          "binding",
          "settings",
          "configure",
          "diagnostics",
        ].includes(operation)
      )
        throw new Error("Unknown local operation");
      const key = `pending:${id}`;
      if (operation === "event") {
        const old = (await chrome.storage.session.get(key))[key] as
          | Pending
          | undefined;
        if (old && JSON.stringify(old.data) !== JSON.stringify(data))
          throw new Error("A retry must use the original event unchanged");
        await chrome.storage.session.set({
          [key]: { id, operation, data, stopped: old?.stopped || false },
        });
      }
      const result = await native(operation, data, id);
      if (operation === "event") await chrome.storage.session.remove(key);
      return result;
    }
    if (["insert", "undo", "capture", "hide"].includes(message.type)) {
      const page = await getPage(),
        t = message.target as Target;
      if (
        !page ||
        !t ||
        t.tabId !== page.tabId ||
        t.documentId !== page.documentId ||
        t.documentToken !== page.documentToken
      )
        throw new Error("The active page changed. Select the field again.");
      const reply = await chrome.tabs.sendMessage(
        t.tabId,
        {
          type: message.type,
          target: t,
          text: message.text,
          replace: message.replace,
        },
        { documentId: t.documentId },
      );
      if (!reply?.ok) throw new Error(reply?.error || "Field unavailable");
      return reply.data;
    }
    if (message.type === "state.get")
      return (
        (await chrome.storage.session.get(`form:${message.key}`))[
          `form:${message.key}`
        ] || null
      );
    if (message.type === "state.set") {
      await chrome.storage.session.set({
        [`form:${message.key}`]: message.state,
      });
      return null;
    }
    throw new Error("Unknown extension operation");
  };
  void run()
    .then((data) => respond({ ok: true, data }))
    .catch((error) =>
      respond({
        ok: false,
        error: String(error.message || "Operation failed"),
      }),
    );
  return true;
});
