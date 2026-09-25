import contract from "../generated/contract.json";
import { trustedPage, supportedUrl } from "./security";
import type { Page, Pending, Target } from "../integration/types";
import { categoryHints, profiles } from "../integration/profiles";
import { normalize } from "./fields";
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
  const reply = new Promise<any>((resolve, reject) => {
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
  // Any local-data mutation advances the host epoch, which rejects every prepared engine session;
  // drop the cached ai:* sessions so the next AI action re-prepares instead of failing.
  if (INVALIDATING.has(operation)) await reply.then(dropAiSessions, () => {});
  return reply;
}
const INVALIDATING = new Set(["ingest", "template_update", "binding", "configure"]);
async function dropAiSessions() {
  const keys = Object.keys(await chrome.storage.session.get(null)).filter((k) => k.startsWith("ai:"));
  if (keys.length) await chrome.storage.session.remove(keys);
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
type Session = { id: string; categoryId: string; context?: string; contextTitle?: string };
const sessionKey = (tabId: number) => `session:${tabId}`;
async function session(tabId: number): Promise<Session | null> {
  return (await chrome.storage.session.get(sessionKey(tabId)))[sessionKey(tabId)] || null;
}
async function inject(tabId: number, url?: string) {
  if (!supportedUrl(url || "") || !await session(tabId)) return;
  try {
    await chrome.scripting.executeScript({ target: { tabId }, files: ["content.js"] });
    await chrome.tabs.sendMessage(tabId, { type: "inspect" }, { frameId: 0 });
  } catch { /* Unsupported or transitional document; the next navigation retries. */ }
}
async function selectedProfile(tabId: number) {
  const s = await session(tabId);
  const all = await profiles();
  return all.items.find((p) => p.id === s?.categoryId) || all.items[0];
}
async function matches(tabId: number, question: string) {
  const selected = await selectedProfile(tabId);
  const hints = categoryHints(selected);
  const aliases = (await chrome.storage.local.get("questionAliases")).questionAliases as Record<string, {id:string;intent:string}> | undefined;
  const alias = aliases?.[`${(await session(tabId))?.categoryId || "default"}:${normalize(question)}`];
  const result = await native("search", { query: question, hints }, crypto.randomUUID());
  const eligible = (m:{applies:Record<string,string[]>}) => Object.entries(m.applies || {}).every(([dimension,values]) =>
    dimension === selected.dimension && values.includes(selected.value));
  const found = ((result.matches || []) as Array<{ id: string; body: string; intent: string; similarity: number; applies: Record<string, string[]> }>).filter(eligible);
  if (alias?.intent && !found.some((m) => m.id === alias.id)) {
    const byIntent = await native("search", { query: alias.intent, hints }, crypto.randomUUID());
    const mapped = (byIntent.matches || []).find((m:{id:string;applies:Record<string,string[]>})=>m.id===alias.id && eligible(m));
    if (mapped) found.unshift(mapped);
  }
  return { matches: found, mappedId: alias?.id || null, incomplete: true };
}
const aliasKey = (categoryId:string, question:string) => `${categoryId}:${normalize(question)}`;
async function aliasRecord(tabId:number, question:string) {
  const s=await session(tabId);
  const all=(await chrome.storage.local.get("questionAliases")).questionAliases as Record<string,{id:string;intent:string}>|undefined;
  return all?.[aliasKey(s?.categoryId || "default",question)] || null;
}
function storeAlias(tabId:number,question:string,id:string,intent:string) {
  // Whole-map read/modify/write: serialize so concurrent autosaves for two fields cannot drop each other's mapping.
  return queued("questionAliases",async()=>{
    const s=await session(tabId);
    const current=(await chrome.storage.local.get("questionAliases")).questionAliases || {};
    current[aliasKey(s?.categoryId||"default",question)]={id,intent};
    await chrome.storage.local.set({questionAliases:current});
  });
}
async function visible(tabId:number,fieldId:string):Promise<Array<{id:string;intent:string;body:string;version:number}>> {
  return (await chrome.storage.session.get(`visible:${tabId}:${fieldId}`))[`visible:${tabId}:${fieldId}`] || [];
}
async function remember(tabId:number,question:string,match:{id:string;intent:string;version?:number}) {
  const current=await native("template_get",{id:match.id},crypto.randomUUID());
  await native("template_update",{id:match.id,alias:question,expected_version:current.version},crypto.randomUUID());
  await storeAlias(tabId,question,match.id,current.intent);
}
const saves=new Map<string,Promise<unknown>>();
function queued<T>(key:string,task:()=>Promise<T>):Promise<T> {
  const next=(saves.get(key)||Promise.resolve()).catch(()=>{}).then(task);
  saves.set(key,next);
  void next.finally(()=>{if(saves.get(key)===next)saves.delete(key);}).catch(()=>{});
  return next;
}
async function targetFor(sender: chrome.runtime.MessageSender, target: Target): Promise<Page> {
  const tabId = sender.tab?.id;
  if (!tabId || target.tabId !== tabId || target.documentId !== sender.documentId) throw Error("Field is no longer on this page");
  const page = (await chrome.storage.session.get(`page:${tabId}`))[`page:${tabId}`] as Page;
  const field = page?.fields.find((f) => f.id === target.id && f.formId === target.formId && f.signature === target.signature && f.version === target.version);
  if (!field || page.documentToken !== target.documentToken || page.documentId !== target.documentId) throw Error("Field changed. Select it again.");
  return page;
}
const filling=new Set<string>();
function fillMapped(page:Page) {
  if(!page.tabId||!page.documentId)return;
  for(const field of page.fields) {
    if(field.prefilled||field.kind==="file")continue;
    const key=`${page.tabId}:${page.documentToken}:${field.id}`;
    if(filling.has(key))continue;
    filling.add(key);
    void (async()=>{
      const alias=await aliasRecord(page.tabId!,field.question);
      if(!alias)return;
      const template=await native("template_get",{id:alias.id},crypto.randomUUID());
      const rendered=await native("render",{body:template.body,constraints:field.constraints},crypto.randomUUID());
      if(!rendered.text||rendered.problems?.length)return;
      const target:Target={id:field.id,formId:field.formId,version:field.version,signature:field.signature,
        documentToken:page.documentToken,tabId:page.tabId!,documentId:page.documentId!};
      await chrome.tabs.sendMessage(page.tabId!,{type:"insert",target,text:rendered.text,replace:false},{documentId:page.documentId});
    })().catch(()=>{}).finally(()=>filling.delete(key));
  }
}
async function feedback(tabId:number,page:Page,formId:string,outcome:string,candidateIds:string[]) {
  const key=`ai:${tabId}:${page.documentToken}:${formId}`;
  const state=(await chrome.storage.session.get(key))[key] as {id:string;revision:string|null}|undefined;
  if(!state)return;
  const id=crypto.randomUUID();
  const payload=outcome==="shown"?{outcome,shown:candidateIds.slice(0,1),alternatives:candidateIds.slice(1)}:{outcome,candidate_id:candidateIds[0]};
  const r=await native("event",{event:{event_id:id,session_id:state.id,scope_id:"user-default",type:"record_feedback",expected_revision:state.revision,payload},authorized:false},id);
  state.revision=r.revision;await chrome.storage.session.set({[key]:state});
}
chrome.tabs.onRemoved.addListener((id) => {
  void chrome.storage.session.remove([`page:${id}`, sessionKey(id)]);
});
chrome.tabs.onUpdated.addListener((id, change) => {
  if (change.status === "loading" || change.url) void chrome.storage.session.remove(`page:${id}`);
  if (change.status === "complete") void chrome.tabs.get(id).then((tab) => inject(id, tab.url));
});
chrome.webNavigation.onHistoryStateUpdated.addListener((details) => {
  if (details.frameId === 0) void inject(details.tabId, details.url);
});
chrome.tabs.onCreated.addListener((tab) => {
  if (!tab.id || !tab.openerTabId) return;
  void session(tab.openerTabId).then(async (s) => {
    if (s) await chrome.storage.session.set({ [sessionKey(tab.id!)]: s });
  });
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
        if (!await session(sender.tab.id)) throw Error("No active session");
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
              typeof f.id !== "string" ||
              (f.options && (!Array.isArray(f.options) || f.options.length > 100)),
          )
        )
          throw new Error("Invalid field report");
        const u = new URL(sender.url!);
        const page: Page = {
          documentToken: p.documentToken,
          scanSeq: p.scanSeq,
          url: u.origin + u.pathname,
          title: String(p.title).slice(0, 300),
          fields: p.fields,
          activeId: p.activeId,
          tabId: sender.tab.id,
          documentId: sender.documentId,
        };
        const pageKey=`page:${sender.tab.id}`;
        const previous=(await chrome.storage.session.get(pageKey))[pageKey] as Page|undefined;
        if(!previous||previous.documentToken!==page.documentToken||(page.scanSeq||0)>=(previous.scanSeq||0))
          {await chrome.storage.session.set({ [pageKey]: page });fillMapped(page);}
        return { tabId: sender.tab.id, documentId: sender.documentId };
      }
      if (message.type === "field.matches") {
        if (!await session(sender.tab.id)) throw Error("Start Questionnaire Assistant from the toolbar");
        const page=(await chrome.storage.session.get(`page:${sender.tab.id}`))[`page:${sender.tab.id}`] as Page;
        const field=page?.fields.find((f)=>f.id===message.target?.id);
        if(!field||page.documentId!==sender.documentId||page.documentToken!==message.target?.documentToken)throw Error("Field changed. Click it again.");
        const query=typeof message.query==="string"&&message.query.trim()?message.query.trim().slice(0,2000):field.question;
        const result=await matches(sender.tab.id, query);
        await chrome.storage.session.set({[`visible:${sender.tab.id}:${field.id}`]:result.matches});
        return result;
      }
      if (message.type === "field.use") {
        const page = await targetFor(sender, message.target);
        const field = page.fields.find((f) => f.id === message.target.id)!;
        const chosen = (await visible(sender.tab.id,field.id)).find((m) => m.id === message.id);
        if (!chosen) throw Error("This answer is no longer in search results. Search again.");
        const current=await native("template_get",{id:chosen.id},crypto.randomUUID());
        const rendered = await native("render", { body: current.body, constraints: field.constraints }, crypto.randomUUID());
        if (!rendered.text || rendered.problems?.length) throw Error((rendered.problems || ["Answer unavailable"]).join("; "));
        const reply = await chrome.tabs.sendMessage(sender.tab.id, { type: "insert", target: message.target, text: rendered.text, replace: true }, { documentId: sender.documentId });
        if (!reply?.ok) throw Error(reply?.error || "Field unavailable");
        try { await remember(sender.tab.id,field.question,chosen);return {inserted:true,mapped:true}; }
        catch(e) {return {inserted:true,mapped:false,mappingError:(e as Error).message};}
      }
      if (message.type === "field.map") {
        const page=await targetFor(sender,message.target);
        const field=page.fields.find(f=>f.id===message.target.id)!;
        const selected=(await visible(sender.tab.id,field.id)).find((m)=>m.id===message.id);
        if(!selected)throw Error("Select a visible saved answer");
        await remember(sender.tab.id,field.question,selected);
        return { saved: true };
      }
      if (message.type === "field.editTemplate") {
        const page=await targetFor(sender,message.target);
        const field=page.fields.find(f=>f.id===message.target.id)!;
        if(!(await visible(sender.tab.id,field.id)).some((m)=>m.id===message.id))throw Error("Select a visible saved answer");
        const updated=await native("template_update",{id:message.id,intent:message.intent,body:message.body,
          alias:field.question,expected_version:message.version},crypto.randomUUID());
        await storeAlias(sender.tab.id,field.question,updated.id,updated.intent);
        return updated;
      }
      if (message.type === "field.autosave") {
        const page=await targetFor(sender,message.target);
        const field=page.fields.find(f=>f.id===message.target.id)!;
        if(field.kind==="file")throw Error("File selections are not stored as answers");
        const body=String(message.body||"");
        if(!body.trim()||body.length>100000)throw Error("Answer must contain at most 100,000 characters");
        return queued(`${sender.tab.id}:${field.id}`,async()=>{
          const selected=await selectedProfile(sender.tab!.id!);
          const known=await aliasRecord(sender.tab!.id!,field.question);
          if(known?.id){
            const existing=await native("template_get",{id:known.id},crypto.randomUUID());
            if(existing.body===body)return {id:existing.id,version:existing.version,unchanged:true};
            if(/\{\{[a-zA-Z_][a-zA-Z0-9_]*\}\}/.test(existing.body))
              throw Error("This answer uses a private variable. Edit its template in Settings to keep the value protected.");
            const updated=await native("template_update",{id:existing.id,body,expected_version:existing.version},crypto.randomUUID());
            return {id:updated.id,version:updated.version};
          }
          const id=`T_${crypto.randomUUID().replaceAll("-","")}`;
          await native("ingest",{record:{kind:"template",id,intent:field.question,aliases:[field.question],body,
            variables:[],evidence:[],context:selected.dimension?[{dimension:selected.dimension,value:selected.value,mode:"applies"}]:[],
            disclosure:"local_only",approved_by:"user",approved_at:new Date().toISOString()}},crypto.randomUUID());
          await storeAlias(sender.tab!.id!,field.question,id,field.question);
          return {id,version:1,created:true};
        });
      }
      if (message.type === "field.save") {
        const page = await targetFor(sender,message.target);
        const field = page.fields.find((f)=>f.id===message.target.id)!;
        const body = String(message.body || "").trim();
        if (!body || body.length > 10000) throw Error("Enter an answer of at most 10,000 characters");
        const selected = await selectedProfile(sender.tab.id);
        const id = `T_${crypto.randomUUID().replaceAll("-","")}`;
        await native("ingest",{record:{kind:"template",id,intent:field.question,aliases:[field.question],body,variables:[],evidence:[],
          context:selected.dimension ? [{dimension:selected.dimension,value:selected.value,mode:"applies"}] : [],
          disclosure:"local_only",approved_by:"user",approved_at:new Date().toISOString()}},crypto.randomUUID());
        await storeAlias(sender.tab.id,field.question,id,field.question);
        return {saved:true};
      }
      if (message.type === "field.ai") {
        const page = await targetFor(sender, message.target);
        const s = await session(sender.tab.id);
        if (!s) throw Error("Start a session first");
        const info = await native("hello", {}, crypto.randomUUID());
        if (!info.generationReady) throw Error("AI help needs a model credential in Settings. Saved answers remain available.");
        const field = page.fields.find((f) => f.id === message.target.id)!;
        const key = `ai:${sender.tab.id}:${page.documentToken}:${field.formId}`;
        let state = (await chrome.storage.session.get(key))[key] as { id:string; revision:string|null; prepared:boolean; prepareKey?:string } | undefined;
        if (!state) state = { id:crypto.randomUUID(), revision:null, prepared:false };
        const prepare = { questions: page.fields.filter((f) => f.formId === field.formId).map((f) => ({ id:f.id, text:f.question, constraints:f.constraints, prefilled:f.prefilled })),
          page_url:page.url, page_title:page.title, hints:categoryHints(await selectedProfile(sender.tab.id)), ...(s.context ? { page_context:s.context } : {}) };
        const prepareKey = JSON.stringify(prepare);
        async function event(type:string,payload:Record<string,unknown>,authorized=false) {
          const id=crypto.randomUUID();
          const r=await native("event",{event:{event_id:id,session_id:state!.id,scope_id:"user-default",type,expected_revision:state!.revision,payload},authorized},id);
          state!.revision=r.revision;
          await chrome.storage.session.set({[key]:state});
          return r;
        }
        if (!state.prepared || state.prepareKey !== prepareKey) {
          const r=await event(state.prepared?"update_form":"prepare_form",prepare);
          if(r.status!=="ready")throw Error("Could not prepare this form");
          state.prepared=true;state.prepareKey=prepareKey;await chrome.storage.session.set({[key]:state});
        }
        const r=await event("generate_initial",{target_question_ids:[field.id],authorized_question_ids:[field.id]},true);
        const candidates=(r.candidates||[]).filter((c:{question_id:string})=>c.question_id===field.id);
        await chrome.storage.session.set({[`generated:${sender.tab.id}:${field.id}`]:candidates});
        return {candidates:candidates.map((c:{id:string;body:string})=>({id:c.id,body:c.body})),message:r.unresolved?.map((u:{needed?:string;reason:string})=>u.needed||u.reason).join("; ")};
      }
      if (message.type === "field.useGenerated") {
        const page=await targetFor(sender,message.target);
        const field=page.fields.find((f)=>f.id===message.target.id)!;
        const candidates=(await chrome.storage.session.get(`generated:${sender.tab.id}:${field.id}`))[`generated:${sender.tab.id}:${field.id}`] || [];
        const chosen=candidates.find((c:{id:string})=>c.id===message.id);
        if(!chosen)throw Error("Generate an answer for this field first");
        const rendered=await native("render",{body:chosen.body,constraints:field.constraints},crypto.randomUUID());
        if(!rendered.text||rendered.problems?.length)throw Error((rendered.problems||["Answer unavailable"]).join("; "));
        const reply=await chrome.tabs.sendMessage(sender.tab.id,{type:"insert",target:message.target,text:rendered.text,replace:true},{documentId:sender.documentId});
        if(!reply?.ok)throw Error(reply?.error||"Field unavailable");
        try {
          await feedback(sender.tab.id,page,field.formId,"selected",[chosen.id]);
          const key=`ai:${sender.tab.id}:${page.documentToken}:${field.formId}`;
          const state=(await chrome.storage.session.get(key))[key] as {id:string;revision:string|null};
          const templateId=`T_${crypto.randomUUID().replaceAll("-","")}`;
          const eventId=crypto.randomUUID();
          const approved=await native("event",{event:{event_id:eventId,session_id:state.id,scope_id:"user-default",type:"record_feedback",
            expected_revision:state.revision,payload:{outcome:"approved",candidate_id:chosen.id,approve_as_template_id:templateId}},authorized:false},eventId);
          state.revision=approved.revision;await chrome.storage.session.set({[key]:state});
          await native("template_update",{id:templateId,intent:field.question,alias:field.question,expected_version:1},crypto.randomUUID());
          await storeAlias(sender.tab.id,field.question,templateId,field.question);
          return {inserted:true,mapped:true};
        } catch(e) { return {inserted:true,mapped:false,mappingError:(e as Error).message}; }
      }
      if (message.type === "field.shown") {
        const page=await targetFor(sender,message.target);
        const field=page.fields.find((f)=>f.id===message.target.id)!;
        const candidates=(await chrome.storage.session.get(`generated:${sender.tab.id}:${field.id}`))[`generated:${sender.tab.id}:${field.id}`] || [];
        const ids=(message.ids as string[]).filter((id)=>candidates.some((c:{id:string})=>c.id===id));
        if(ids.length)await feedback(sender.tab.id,page,field.formId,"shown",ids);
        return null;
      }
      if (message.type === "context.get") {
        if (!await session(sender.tab.id)) throw Error("No active session");
        return null;
      }
      throw new Error(
        "Webpage adapters cannot read local data or authorize operations",
      );
    }
    if (!trustedPage(sender, chrome.runtime.id))
      throw new Error("Open the trusted popup or settings page");
    if (message.type?.startsWith("session.")) {
      const tab = await activeTab();
      if (!tab?.id) throw Error("Open a tab first");
      const existing = await session(tab.id);
      const all = await profiles();
      if (message.type === "session.status") return { active: !!existing, categoryId: existing?.categoryId || all.defaultId, contextTitle: existing?.contextTitle, profiles: all };
      if (message.type === "session.stop") {
        await chrome.storage.session.remove([sessionKey(tab.id), `page:${tab.id}`]);
        await chrome.tabs.sendMessage(tab.id, { type: "hide" }).catch(() => {});
        return null;
      }
      if (!supportedUrl(tab.url || "")) throw Error("Open a regular HTTP or HTTPS page first");
      if (message.type === "session.start") {
        if (!existing) await chrome.storage.session.set({ [sessionKey(tab.id)]: { id: crypto.randomUUID(), categoryId: all.defaultId } });
        await inject(tab.id, tab.url);
        return null;
      }
      if (!existing) throw Error("Start a session first");
      if (message.type === "session.rescan") { await inject(tab.id, tab.url); return null; }
      if (message.type === "session.category") {
        if (!all.items.some((p) => p.id === message.id)) throw Error("Unknown category");
        await chrome.storage.session.set({ [sessionKey(tab.id)]: { ...existing, categoryId: message.id } });
        await inject(tab.id, tab.url);
        return null;
      }
      if (message.type === "session.captureContext") {
        const reply = await chrome.tabs.sendMessage(tab.id, { type: "captureContext" }, { frameId: 0 });
        if (!reply?.ok) throw Error(reply?.error || "Page context unavailable");
        await chrome.storage.session.set({ [sessionKey(tab.id)]: { ...existing, context: reply.data.text, contextTitle: reply.data.title } });
        return null;
      }
    }
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
