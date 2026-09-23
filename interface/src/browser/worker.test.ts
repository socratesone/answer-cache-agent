import { it, expect, vi } from "vitest";
const storage: Record<string, any> = {};
let listener: any;
const port = {
  postMessage: vi.fn(),
  onMessage: { addListener: vi.fn() },
  onDisconnect: { addListener: vi.fn() },
};
const chromeMock = {
  runtime: {
    id: "test",
    connectNative: vi.fn(() => port),
    onMessage: { addListener: (fn: any) => (listener = fn) },
  },
  storage: {
    session: {
      setAccessLevel: vi.fn(async () => {}),
      get: vi.fn(async (key: string | null) =>
        key ? { [key]: storage[key] } : storage,
      ),
      set: vi.fn(async (values: any) => Object.assign(storage, values)),
      remove: vi.fn(async () => {}),
    },
  },
  tabs: {
    query: vi.fn(async () => [{ id: 1, url: "https://example.test/form" }]),
    onRemoved: { addListener: vi.fn() },
    onUpdated: { addListener: vi.fn() },
    sendMessage: vi.fn(),
  },
  action: { onClicked: { addListener: vi.fn() } },
  sidePanel: { open: vi.fn() },
  scripting: { executeScript: vi.fn() },
};
vi.stubGlobal("chrome", chromeMock);
await import("./worker");
const send = (message: any, sender: any) =>
  new Promise<any>((resolve) => listener(message, sender, resolve));
it("rejects a content adapter trying to spend money or read the library", async () => {
  const sender = {
    id: "test",
    tab: { id: 1 },
    frameId: 0,
    documentId: "doc",
    url: "https://example.test/form",
  };
  for (const operation of ["event", "search", "configure", "binding"]) {
    const reply = await send(
      { type: "host", operation, id: "attempt", data: {} },
      sender,
    );
    expect(reply.ok).toBe(false);
  }
  expect(chromeMock.runtime.connectNative).not.toHaveBeenCalled();
});
it("rejects an extension lookalike and cross-origin frame", async () => {
  expect(
    (
      await send(
        { type: "host", operation: "hello", id: "x", data: {} },
        { id: "other", url: "chrome-extension://test/panel.html" },
      )
    ).ok,
  ).toBe(false);
  expect(
    (
      await send(
        { type: "snapshot", page: {} },
        {
          id: "test",
          tab: { id: 1 },
          frameId: 3,
          documentId: "frame",
          url: "https://example.test/form",
        },
      )
    ).ok,
  ).toBe(false);
});
it("does not insert into a previous tab or document", async () => {
  storage["page:1"] = {
    tabId: 1,
    documentId: "current",
    documentToken: "token",
    fields: [],
  };
  const reply = await send(
    {
      type: "insert",
      target: { tabId: 2, documentId: "old", documentToken: "old" },
      text: "private selected text",
    },
    { id: "test", url: "chrome-extension://test/panel.html" },
  );
  expect(reply.ok).toBe(false);
  expect(chromeMock.tabs.sendMessage).not.toHaveBeenCalled();
});
