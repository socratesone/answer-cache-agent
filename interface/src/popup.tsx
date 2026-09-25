import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { rpc } from "./integration/client";
import type { Profiles } from "./integration/profiles";

type Status = { active: boolean; categoryId: string; contextTitle?: string; profiles: Profiles };
function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const refresh = () => rpc<Status>("session.status").then(setStatus).catch((e) => setMessage(e.message));
  useEffect(() => { void refresh(); }, []);
  async function act(task: () => Promise<unknown>) {
    setBusy(true); setMessage("");
    try { await task(); await refresh(); }
    catch (e) { setMessage((e as Error).message); }
    finally { setBusy(false); }
  }
  async function start() {
    const granted = await chrome.permissions.request({ origins: ["http://*/*", "https://*/*"] });
    if (!granted) throw Error("Allow site access to keep this session active across form pages.");
    await rpc("session.start");
  }
  return <main style={{font:"14px system-ui",width:260,padding:14,color:"#173f32"}}>
    <strong>Questionnaire Assistant</strong>
    <p>{status?.active ? "Active on this form workflow" : "Ready to help on this tab"}</p>
    <button disabled={busy} onClick={() => void act(status?.active ? () => rpc("session.rescan") : start)}>
      {status?.active ? "Rescan this page" : "Start"}
    </button>
    <label style={{display:"block",marginTop:12}}>Category
      <select style={{display:"block",width:"100%"}} value={status?.categoryId || "default"}
        onChange={(e) => void act(() => rpc("session.category", { id: e.target.value }))}>
        {(status?.profiles.items || [{id:"default",label:"Default"}]).map((p) =>
          <option key={p.id} value={p.id}>{p.label}</option>)}
      </select>
    </label>
    {status?.active && <>
      <button disabled={busy} style={{marginTop:12}} onClick={() => void act(() => rpc("session.captureContext"))}>Use this page as job context</button>
      {status.contextTitle && <p>Saved context: {status.contextTitle}</p>}
      <button disabled={busy} style={{marginTop:12}} onClick={() => void act(() => rpc("session.stop"))}>Stop session</button>
    </>}
    <p><a href="manage.html" target="_blank">Settings / saved answers</a></p>
    {message && <p role="alert">{message}</p>}
  </main>;
}
createRoot(document.getElementById("root")!).render(<App />);
