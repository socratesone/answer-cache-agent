import { eligible, questionFor, valueOf, assignText, assignChoice, kindOf, optionsFor, groupFor, canOfferAi } from "./fields";
import type { Page, Field, Target, Match } from "../integration/types";
const global = window as unknown as { __questionnaire?: boolean };
if (!global.__questionnaire) { global.__questionnaire = true; start(); }
function start() {
  const documentToken = crypto.randomUUID();
  const ids = new WeakMap<HTMLElement,string>(), forms = new WeakMap<Element,string>();
  const elements = new Map<string,HTMLElement>(), versions = new Map<string,number>();
  let fields: Field[] = [], activeId: string | undefined, timer = 0, dirty = false, stopped = false, scanSeq = 0;
  const saveTimers=new Map<string,number>(), suppressed=new Map<string,string>(), inserting=new Set<string>();
  let stamp: {tabId:number; documentId:string} | null = null;
  const host = document.createElement("div"); host.dataset.questionnaireControls="true";
  const shadow=host.attachShadow({mode:"closed"});
  const style=document.createElement("style");
  style.textContent=":host{all:initial;position:fixed;z-index:2147483647;font:13px system-ui;color:#173f32}.box{max-width:300px;background:white;border:1px solid #aec8bd;border-radius:8px;box-shadow:0 4px 18px #0003;padding:7px}button{font:inherit;cursor:pointer;margin:2px;padding:5px 7px;border:1px solid #a4c7b5;border-radius:5px;background:#eaf4ee;color:#173f32}button:focus-visible{outline:2px solid #00684c}.msg{margin:5px;max-width:280px}.results{max-height:230px;overflow:auto}.answer{display:block;text-align:left;width:98%}";
  shadow.append(style);
  const box=document.createElement("div"); box.className="box"; shadow.append(box);
  function button(label:string, fn:()=>void) { const b=document.createElement("button"); b.textContent=label; b.addEventListener("click",e=>{if(e.isTrusted)fn();}); box.append(b); return b; }
  function note(text:string) {const p=document.createElement("div");p.className="msg";p.textContent=text;box.append(p);}
  function field(el:HTMLElement):Field {
    let id=ids.get(el); if(!id){id=crypto.randomUUID();ids.set(el,id);elements.set(id,el);versions.set(id,0);}
    const form=el.closest('form,[role="form"]')||document.body;
    let formId=forms.get(form);if(!formId){formId=crypto.randomUUID();forms.set(form,formId);}
    const max="maxLength" in el?(el as HTMLInputElement).maxLength:-1;
    const constraints={...(max>0?{max_length:max}:{}),required:el.hasAttribute("required")};
    const question=questionFor(el),kind=kindOf(el),options=optionsFor(el);
    return {id,formId,question,kind,options,constraints,prefilled:!!valueOf(el),version:versions.get(id)||0,
      signature:JSON.stringify([formId,question,kind,constraints,options])};
  }
  function target(f:Field):Target {return {id:f.id,formId:f.formId,version:f.version,signature:f.signature,documentToken,tabId:stamp?.tabId||0,documentId:stamp?.documentId||""};}
  function snapshot():Page {return {documentToken,scanSeq,url:location.origin+location.pathname,title:document.title.slice(0,300),fields,activeId};}
  async function scan() {
    if (stopped) return;
    scanSeq++;
    const seen=new Set<Element>();
    fields=Array.from(document.querySelectorAll<HTMLElement>('input,textarea,select,[contenteditable="true"],[contenteditable="plaintext-only"],[role="combobox"]'))
      .filter(el=>{if(!eligible(el))return false;const g=groupFor(el);if(g&&seen.has(g))return false;if(g)seen.add(g);return true;})
      .slice(0,200).map(field);
    for(const [id,el] of elements)if(!el.isConnected){elements.delete(id);versions.delete(id);}
    const r=await chrome.runtime.sendMessage({type:"snapshot",page:snapshot()}).catch(()=>null);
    if(r?.ok&&r.data?.tabId)stamp=r.data;
  }
  async function freshTarget(f:Field):Promise<Target> {
    await scan();
    const current=fields.find(x=>x.id===f.id);
    if(!current||!stamp)throw Error("This field is no longer available. Click it again.");
    return target(current);
  }
  function schedule(){if(timer)return;timer=window.setTimeout(()=>{timer=0;void scan();},180);}
  function show(f:Field){
    const el=elements.get(f.id);if(!el)return;
    box.replaceChildren();
    if(f.kind==="file") button("Attach file",()=>attachFile(el as HTMLInputElement));
    else {button("Saved answers",()=>void saved(f));if(canOfferAi(el))
      button("AI help",()=>void ai(f));}
    button("×",()=>host.remove());
    const rect=el.getBoundingClientRect();
    host.style.left=`${Math.max(4,Math.min(rect.right-250,innerWidth-310))}px`;
    host.style.top=`${Math.max(4,Math.min(rect.bottom+4,innerHeight-280))}px`;
    document.documentElement.append(host);
  }
  function attachFile(el:HTMLInputElement) {
    const picker=document.createElement("input");picker.type="file";picker.accept=el.accept;
    picker.multiple=el.multiple;picker.style.display="none";box.append(picker);
    picker.addEventListener("change",()=>{
      if(!picker.files?.length)return;
      try {
        const transfer=new DataTransfer();
        for(const file of picker.files)transfer.items.add(file);
        el.files=transfer.files;
        el.dispatchEvent(new Event("input",{bubbles:true}));
        el.dispatchEvent(new Event("change",{bubbles:true}));
        const selected=Array.from(el.files||[]).map(file=>file.name);
        note(selected.length?`Attached: ${selected.join(", ")}`:"The site did not accept this file.");
        if(selected.length)dirty=true;
      } catch {note("This site did not accept attachment. Use its file picker.");}
      picker.remove();
    },{once:true});
    picker.click();
  }
  async function saved(f:Field,query?:string) {
    box.replaceChildren();note("Searching saved answers…");
    try {
      const current=await freshTarget(f);
      const r=await chrome.runtime.sendMessage({type:"field.matches",target:current,query});
      if(!r?.ok)throw Error(r?.error||"Lookup failed");
      box.replaceChildren();button("Back",()=>show(f));
      const matches=r.data.matches as Match[];
      const search=document.createElement("input");search.value=query||"";search.placeholder="Search label or answer";
      search.setAttribute("aria-label","Search saved answers");search.style.width="96%";box.append(search);
      button("Search",()=>void saved(f,search.value));
      button("Create another answer",()=>saveNew(f));
      if(!matches.length){note("No saved match yet. Typed answers are saved automatically, or create another answer here.");return;}
      note("Choose a saved answer:");
      const list=document.createElement("div");list.className="results";box.append(list);
      for(const m of matches) {
        const use=document.createElement("button");use.className="answer";use.textContent=`${m.intent} — ${m.body.slice(0,90)}`;
        use.addEventListener("click",async e=>{if(!e.isTrusted)return;const el=elements.get(f.id);if(!el)return;
          const reply=await chrome.runtime.sendMessage({type:"field.use",target:await freshTarget(field(el)),id:m.id});
          note(reply?.ok?(reply.data?.mapped?"Answer inserted and mapped for next time.":`Answer inserted. Mapping failed: ${reply.data?.mappingError||"unknown error"}`):reply?.error||"Insertion failed");});list.append(use);
        const edit=document.createElement("button");edit.textContent="Edit answer";
        edit.addEventListener("click",e=>{if(e.isTrusted)editSaved(f,m);});list.append(edit);
        const map=document.createElement("button");map.textContent="Map without inserting";
        map.addEventListener("click",async e=>{if(!e.isTrusted)return;const reply=await chrome.runtime.sendMessage({type:"field.map",target:await freshTarget(f),question:f.question,id:m.id});
          note(reply?.ok?"Mapping saved for this category.":reply?.error||"Mapping failed");});list.append(map);
      }
    } catch(e){box.replaceChildren();note((e as Error).message);}
  }
  function editSaved(f:Field,m:Match) {
    box.replaceChildren();button("Back",()=>void saved(f));note("Edit this saved answer. Changes save automatically.");
    const label=document.createElement("input");label.value=m.intent;label.setAttribute("aria-label","Answer label");label.style.width="96%";box.append(label);
    const body=document.createElement("textarea");body.value=m.body;body.rows=5;body.setAttribute("aria-label","Answer wording");body.style.width="96%";box.append(body);
    let version=m.version||1, saving=false, editTimer=0;
    async function persist() {
      if(saving)return;
      if(label.value===m.intent&&body.value===m.body)return;
      saving=true;const intent=label.value.trim(),text=body.value;let success=false;
      try {
        const reply=await chrome.runtime.sendMessage({type:"field.editTemplate",target:await freshTarget(f),id:m.id,intent,body:text,version});
        if(!reply?.ok)throw Error(reply?.error||"Update failed");
        version=reply.data.version;m.intent=intent;m.body=text;success=true;note("Saved to the same answer record.");
      } catch(e){note((e as Error).message);} finally {
        saving=false;if(success&&(label.value!==m.intent||body.value!==m.body))scheduleEdit();
      }
    }
    function scheduleEdit(){window.clearTimeout(editTimer);editTimer=window.setTimeout(()=>void persist(),700);}
    label.addEventListener("input",scheduleEdit);body.addEventListener("input",scheduleEdit);
    label.addEventListener("blur",()=>{window.clearTimeout(editTimer);void persist();});
    body.addEventListener("blur",()=>{window.clearTimeout(editTimer);void persist();});
  }
  function saveNew(f:Field) {
    box.replaceChildren();button("Back",()=>void saved(f));note(`Save an answer for: ${f.question}`);
    const input=document.createElement("textarea");input.rows=4;input.style.width="96%";box.append(input);
    button("Save locally",()=>void (async()=>{
      const r=await chrome.runtime.sendMessage({type:"field.save",target:await freshTarget(f),body:input.value}).catch(e=>({ok:false,error:e.message}));
      note(r?.ok?"Answer saved. Reopen Saved answers to use it.":r?.error||"Save failed");
    })());
  }
  async function ai(f:Field) {
    box.replaceChildren();button("Back",()=>show(f));note("Generation requires a configured provider. Saved answers do not.");
    button("Generate for this field",()=>void (async()=>{
      note("Generating…");
      const r=await chrome.runtime.sendMessage({type:"field.ai",target:await freshTarget(f)}).catch(e=>({ok:false,error:e.message}));
      if(!r?.ok){note(r?.error||"Generation failed");return;}
      box.replaceChildren();button("Back",()=>show(f));
      const candidates=r.data.candidates as Array<{id:string;body:string}>;
      if(!candidates.length){note(r.data.message||"No answer generated.");return;}
      for(const c of candidates)button(c.body.slice(0,160),()=>void (async()=>{
        const el=elements.get(f.id);if(!el)return;
        const reply=await chrome.runtime.sendMessage({type:"field.useGenerated",target:await freshTarget(field(el)),id:c.id});
        note(reply?.ok?(reply.data?.mapped?"Answer inserted and saved for reuse.":`Answer inserted. Saving failed: ${reply.data?.mappingError||"unknown error"}`):reply?.error||"Insertion failed");
      })());
      void freshTarget(f).then(t=>chrome.runtime.sendMessage({type:"field.shown",target:t,ids:candidates.map(c=>c.id)}));
    })());
  }
  document.addEventListener("focusin",e=>{if(stopped||!(e.target instanceof HTMLElement)||!eligible(e.target))return;
    const f=field(e.target);activeId=f.id;void scan();show(f);},true);
  function tracked(el:HTMLElement):{id:string;el:HTMLElement}|null {
    const id=ids.get(el);if(id)return {id,el};
    const group=groupFor(el);
    if(group)for(const [key,item] of elements)if(group.contains(item))return {id:key,el:item};
    return null;
  }
  function autosave(id:string,el:HTMLElement,delay=700) {
    if(kindOf(el)==="file")return;
    window.clearTimeout(saveTimers.get(id));
    const body=valueOf(el);if(!body.trim()||suppressed.get(id)===body)return;
    saveTimers.set(id,window.setTimeout(()=>void (async()=>{
      try {const reply=await chrome.runtime.sendMessage({type:"field.autosave",target:await freshTarget(field(el)),body});
        if(!reply?.ok)throw Error(reply?.error||"Automatic save failed");}
      catch(e){note(`Answer was not saved: ${(e as Error).message}`);}
      finally {saveTimers.delete(id);}
    })(),delay));
  }
  document.addEventListener("input",e=>{if(!(e.target instanceof HTMLElement))return;const found=tracked(e.target);if(!found)return;
    versions.set(found.id,(versions.get(found.id)||0)+1);dirty=true;schedule();if(!inserting.has(found.id))autosave(found.id,found.el);},true);
  document.addEventListener("change",e=>{if(!(e.target instanceof HTMLElement))return;const found=tracked(e.target);if(!found)return;
    if(!inserting.has(found.id)&&kindOf(found.el)!=="text")autosave(found.id,found.el);},true);
  document.addEventListener("focusout",e=>{if(!(e.target instanceof HTMLElement))return;const found=tracked(e.target);if(!found)return;
    if(saveTimers.has(found.id)){window.clearTimeout(saveTimers.get(found.id));saveTimers.delete(found.id);autosave(found.id,found.el,0);}},true);
  document.addEventListener("submit",()=>{dirty=false;},true);
  window.addEventListener("beforeunload",e=>{if(dirty&&!stopped){e.preventDefault();e.returnValue="";}});
  new MutationObserver(records=>{if(records.some(r=>!(r.target instanceof Element&&r.target.closest("[data-questionnaire-controls]"))))schedule();})
    .observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:["disabled","readonly","hidden","aria-label","aria-labelledby","required","type","role","aria-expanded"]});
  chrome.runtime.onMessage.addListener((message,sender,respond)=>{
    if(sender.id!==chrome.runtime.id)return;
    if(message.type==="inspect"){stopped=false;void scan().then(()=>respond({ok:true,data:snapshot()}));return true;}
    if(message.type==="hide"){stopped=true;host.remove();respond({ok:true});return;}
    if(message.type==="captureContext"){
      const scope=document.querySelector("main,article,[role=main]")||document.body;
      const copy=scope.cloneNode(true) as HTMLElement;
      copy.querySelectorAll("input,textarea,select,script,style,[contenteditable]").forEach(el=>el.remove());
      respond({ok:true,data:{title:document.title.slice(0,200),text:(copy.textContent||"").replace(/\s+/g," ").slice(0,4000)}});return;
    }
    if(message.type!=="insert")return;
    const t=message.target as Target,el=elements.get(t?.id);
    if(!t||t.documentToken!==documentToken||!el?.isConnected||!eligible(el)){respond({ok:false,error:"Field changed"});return;}
    const f=field(el);
    if(f.formId!==t.formId||f.signature!==t.signature||f.version!==t.version){respond({ok:false,error:"Field was edited. Review it again."});return;}
    if(typeof message.text!=="string"||(f.constraints.max_length&&message.text.length>f.constraints.max_length)){respond({ok:false,error:"Answer exceeds field limit"});return;}
    if(f.prefilled&&!message.replace){respond({ok:false,error:"Field already has an answer"});return;}
    void(async()=>{
      suppressed.set(f.id,message.text);inserting.add(f.id);window.clearTimeout(saveTimers.get(f.id));saveTimers.delete(f.id);
      const ok=f.kind==="text"?(assignText(el,message.text),true):await assignChoice(el,message.text);
      if(!ok){inserting.delete(f.id);respond({ok:false,error:"This control could not accept that choice. Select it manually."});return;}
      await new Promise(r=>setTimeout(r,100));
      if(!el.isConnected||(f.kind==="text"&&valueOf(el)!==message.text)){inserting.delete(f.id);respond({ok:false,error:"Insertion could not be verified"});return;}
      suppressed.set(f.id,valueOf(el));inserting.delete(f.id);dirty=true;respond({ok:true,data:{inserted:true}});void scan();
    })();return true;
  });
  void scan();
}
