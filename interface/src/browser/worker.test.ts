import { it, expect, vi } from "vitest";
const storage: Record<string, any> = {};
const local: Record<string, any> = {};
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
    local: { get: vi.fn(async (key:string) => ({[key]:local[key]})), set: vi.fn(async (values:any) => Object.assign(local,values)) },
    session: {
      setAccessLevel: vi.fn(async () => {}),
      get: vi.fn(async (key: string | null) =>
        key ? { [key]: storage[key] } : storage,
      ),
      set: vi.fn(async (values: any) => Object.assign(storage, values)),
      remove: vi.fn(async (keys: string | string[]) => {
        for (const key of Array.isArray(keys) ? keys : [keys]) delete storage[key];
      }),
    },
  },
  tabs: {
    query: vi.fn(async () => [{ id: 1, url: "https://example.test/form" }]),
    onRemoved: { addListener: vi.fn() },
    onUpdated: { addListener: vi.fn() },
    onCreated: { addListener: vi.fn() },
    get: vi.fn(async () => ({ id:1, url:"https://example.test/form" })),
    sendMessage: vi.fn(async () => ({ok:true})),
  },
  action: { onClicked: { addListener: vi.fn() } },
  webNavigation: { onHistoryStateUpdated: { addListener: vi.fn() } },
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
        { id: "other", url: "chrome-extension://test/popup.html" },
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
    { id: "test", url: "chrome-extension://test/popup.html" },
  );
  expect(reply.ok).toBe(false);
  expect(chromeMock.tabs.sendMessage).not.toHaveBeenCalled();
});
it("keeps a session across navigation and reinjects on the next page", async () => {
  const page = { id:"test", url:"chrome-extension://test/popup.html" };
  expect((await send({type:"session.start"},page)).ok).toBe(true);
  expect(storage["session:1"].categoryId).toBe("default");
  const updated = chromeMock.tabs.onUpdated.addListener.mock.calls[0][0];
  updated(1,{status:"loading",url:"https://example.test/apply"});
  expect(storage["session:1"]).toBeTruthy();
  updated(1,{status:"complete"});
  await new Promise((resolve)=>setTimeout(resolve,0));
  expect(chromeMock.scripting.executeScript).toHaveBeenCalledWith({target:{tabId:1},files:["content.js"]});
  expect((await send({type:"session.stop"},page)).ok).toBe(true);
  expect(storage["session:1"]).toBeUndefined();
});
it("accepts saved-answer lookup after a field version changes", async () => {
  storage["session:1"]={id:"session",categoryId:"default"};
  storage["page:1"]={tabId:1,documentId:"doc",documentToken:"token",fields:[{id:"q",formId:"form",question:"Salary range",version:2,signature:"new"}]};
  port.postMessage.mockImplementation((request:any)=>queueMicrotask(()=>{
    port.onMessage.addListener.mock.calls[0][0]({id:request.id,ok:true,data:{matches:[]}});
  }));
  const reply=await send({type:"field.matches",target:{id:"q",tabId:1,documentId:"doc",documentToken:"token",version:1,signature:"old"}},
    {id:"test",tab:{id:1},frameId:0,documentId:"doc",url:"https://example.test/form"});
  expect(reply.ok).toBe(true);
  expect(reply.data.matches).toEqual([]);
});
it("updates the mapped answer record as the user revises field text", async () => {
  storage["session:1"]={id:"session",categoryId:"default"};
  storage["page:1"]={tabId:1,documentId:"doc",documentToken:"token",fields:[{id:"q",formId:"form",question:"Salary range",kind:"text",version:2,signature:"sig"}]};
  local.questionAliases={"default:salary range":{id:"T_salary",intent:"Salary range"}};
  let body="125k/year",version=1;
  port.postMessage.mockClear();
  port.postMessage.mockImplementation((request:any)=>queueMicrotask(()=>{
    const data=request.operation==="template_get"?{id:"T_salary",intent:"Salary range",body,version}:
      request.operation==="template_update"?(body=request.data.body,version++,{id:"T_salary",intent:"Salary range",version}):{};
    port.onMessage.addListener.mock.calls[0][0]({id:request.id,ok:true,data});
  }));
  const sender={id:"test",tab:{id:1},frameId:0,documentId:"doc",url:"https://example.test/form"};
  const target={id:"q",formId:"form",tabId:1,documentId:"doc",documentToken:"token",version:2,signature:"sig"};
  expect((await send({type:"field.autosave",target,body:"130k/year"},sender)).data.id).toBe("T_salary");
  expect((await send({type:"field.autosave",target,body:"135k/year"},sender)).data.id).toBe("T_salary");
  expect(port.postMessage.mock.calls.filter(([r])=>r.operation==="template_update")).toHaveLength(2);
  expect(port.postMessage.mock.calls.filter(([r])=>r.operation==="ingest")).toHaveLength(0);
});
it("does not replace a private template variable with its rendered value", async () => {
  storage["session:1"]={id:"session",categoryId:"default"};
  storage["page:1"]={tabId:1,documentId:"doc",documentToken:"token",fields:[{id:"private",formId:"form",question:"Email",kind:"text",version:0,signature:"sig"}]};
  local.questionAliases={"default:email":{id:"T_email",intent:"Email"}};
  port.postMessage.mockClear();
  port.postMessage.mockImplementation((request:any)=>queueMicrotask(()=>{
    port.onMessage.addListener.mock.calls[0][0]({id:request.id,ok:true,data:{id:"T_email",body:"{{email_address}}",version:1}});
  }));
  const reply=await send({type:"field.autosave",target:{id:"private",formId:"form",tabId:1,documentId:"doc",documentToken:"token",version:0,signature:"sig"},body:"private@example.test"},
    {id:"test",tab:{id:1},frameId:0,documentId:"doc",url:"https://example.test/form"});
  expect(reply.ok).toBe(false);
  expect(reply.error).toContain("private variable");
  expect(port.postMessage.mock.calls.some(([r])=>r.operation==="template_update")).toBe(false);
});
it("fills an empty field from an explicitly learned question mapping", async () => {
  storage["session:1"]={id:"session",categoryId:"default"};
  local.questionAliases={"default:salary range":{id:"T_salary",intent:"Salary range"}};
  chromeMock.tabs.sendMessage.mockClear();
  port.postMessage.mockImplementation((request:any)=>queueMicrotask(()=>{
    const data=request.operation==="template_get"?{id:"T_salary",body:"125k/year",intent:"Salary range",version:1}:
      request.operation==="render"?{text:"125k/year",problems:[]}:{};
    port.onMessage.addListener.mock.calls[0][0]({id:request.id,ok:true,data});
  }));
  const sender={id:"test",tab:{id:1},frameId:0,documentId:"doc",url:"https://example.test/form"};
  const field={id:"salary",formId:"form",question:"Salary range",kind:"text",constraints:{},prefilled:false,version:0,signature:"sig"};
  expect((await send({type:"snapshot",page:{documentToken:"fresh",scanSeq:1,title:"Form",fields:[field]}},sender)).ok).toBe(true);
  await new Promise(resolve=>setTimeout(resolve,0));
  expect(chromeMock.tabs.sendMessage).toHaveBeenCalledWith(1,expect.objectContaining({type:"insert",text:"125k/year",replace:false}),{documentId:"doc"});
});
