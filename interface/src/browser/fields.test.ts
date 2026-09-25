// @vitest-environment jsdom
import { describe, it, expect, beforeEach } from "vitest";
import { eligible, questionFor, assignText, assignChoice, valueOf, mayUndo, optionsFor, groupFor, kindOf, canOfferAi, normalize } from "./fields";
import { trustedPage, supportedUrl } from "./security";
beforeEach(() => {
  document.body.innerHTML = "";
});
describe("field safety", () => {
  it("prefers accessible labels to placeholders", () => {
    document.body.innerHTML =
      '<label for="a">Actual question</label><input id="a" placeholder="hint">';
    expect(questionFor(document.querySelector("input")!)).toBe(
      "Actual question",
    );
  });
  it.each(["password", "hidden"])(
    "excludes %s",
    (type) => {
      const el = document.createElement("input");
      el.type = type;
      el.setAttribute("aria-label", "Question");
      expect(eligible(el, false)).toBe(false);
    },
  );
  it("uses the visible question rather than an array-style control name", () => {
    document.body.innerHTML='<div><label>To ensure alignment early, what base salary range would you need to accept this role?</label><textarea name="Answers[5].Body"></textarea></div>';
    expect(questionFor(document.querySelector("textarea")!)).toBe("To ensure alignment early, what base salary range would you need to accept this role?");
  });
  it("discovers file inputs without treating them as text or AI answers", () => {
    document.body.innerHTML='<label>Upload résumé <input type="file" accept=".pdf"></label>';
    const input=document.querySelector("input")!;
    expect(eligible(input,false)).toBe(true);
    expect(kindOf(input)).toBe("file");
    expect(canOfferAi(input)).toBe(false);
  });
  it("offers AI only for free-form text controls", () => {
    document.body.innerHTML='<label><input type="radio">Yes</label><label><input type="checkbox">No</label><textarea aria-label="Cover letter"></textarea><input type="text" aria-label="Name">';
    const controls=document.querySelectorAll<HTMLElement>("input,textarea");
    expect(Array.from(controls,canOfferAi)).toEqual([false,false,true,false]);
  });
  it.each(["checkbox", "radio", "number"])("discovers %s", (type) => {
    const el = document.createElement("input"); el.type=type; el.setAttribute("aria-label","Question");
    document.body.append(el); expect(eligible(el,false)).toBe(true);
  });
  it("discovers and fills a native select", async () => {
    document.body.innerHTML='<label for="s">State</label><select id="s"><option value="">Select</option><option value="CO">Colorado</option></select>';
    const el=document.querySelector("select")!;
    expect(eligible(el,false)).toBe(true);
    expect(optionsFor(el)).toEqual(["Colorado"]);
    expect(await assignChoice(el,"Colorado")).toBe(true);
    expect(el.value).toBe("CO");
  });
  it("keeps non-Latin letters in mapping keys and option matching", async () => {
    expect(normalize("現在の勤務先")).toBe("現在の勤務先");
    expect(normalize("現在の勤務先")).not.toBe(normalize("希望年収"));
    expect(normalize("Zürich, Straße 1!")).toBe("zürich straße 1");
    document.body.innerHTML='<label for="c">都市</label><select id="c"><option value="">選択</option><option value="1">東京</option><option value="2">大阪</option></select>';
    const el=document.querySelector("select")!;
    expect(await assignChoice(el,"大阪")).toBe(true);
    expect(el.value).toBe("2");
  });
  it("collapses a yes/no checkbox question and selects the answer", async () => {
    document.body.innerHTML='<fieldset><legend>Need sponsorship?</legend><label><input type="checkbox" value="yes">Yes</label><label><input type="checkbox" value="no">No</label></fieldset>';
    const boxes=document.querySelectorAll<HTMLInputElement>("input");
    expect(groupFor(boxes[0])).toBe(boxes[0].closest("fieldset"));
    expect(questionFor(boxes[0])).toBe("Need sponsorship?");
    expect(optionsFor(boxes[0])).toEqual(["Yes","No"]);
    expect(await assignChoice(boxes[0],"No")).toBe(true);
    expect(boxes[1].checked).toBe(true);
  });
  it("selects an accessible custom combobox option", async () => {
    document.body.innerHTML='<label for="state">State</label><input id="state" role="combobox" aria-controls="states"><div id="states" role="listbox"><div role="option">Colorado</div></div>';
    const input=document.querySelector("input")!;
    document.querySelector<HTMLElement>('[role="option"]')!.addEventListener("click",()=>{input.value="Colorado";});
    expect(await assignChoice(input,"Colorado")).toBe(true);
  });
  it("discovers a 17-question mixed-control form", () => {
    const form=document.createElement("form");
    for(let n=0;n<10;n++){const label=document.createElement("label");label.textContent=`Question ${n+1}`;
      const input=document.createElement("input");input.type=n===0?"email":n===1?"tel":"text";label.append(input);form.append(label);}
    for(let n=0;n<2;n++){const label=document.createElement("label");label.textContent=`Long question ${n}`;
      label.append(document.createElement("textarea"));form.append(label);}
    for(let n=0;n<2;n++){const label=document.createElement("label");label.textContent=`Select question ${n}`;
      const select=document.createElement("select");select.innerHTML='<option value="">Choose</option><option value="x">Choice</option>';
      label.append(select);form.append(label);}
    const radio=document.createElement("fieldset");radio.innerHTML='<legend>Authorization?</legend><label><input type="radio" name="auth">Yes</label><label><input type="radio" name="auth">No</label>';form.append(radio);
    const checks=document.createElement("fieldset");checks.innerHTML='<legend>Sponsorship?</legend><label><input type="checkbox">Yes</label><label><input type="checkbox">No</label>';form.append(checks);
    const custom=document.createElement("input");custom.setAttribute("role","combobox");custom.setAttribute("aria-label","Current state");form.append(custom);
    document.body.append(form);
    const seen=new Set<Element>();
    const count=Array.from(form.querySelectorAll<HTMLElement>('input,textarea,select,[role="combobox"]')).filter(el=>{
      if(!eligible(el,false))return false;const group=groupFor(el);if(group&&seen.has(group))return false;if(group)seen.add(group);return true;
    }).length;
    expect(count).toBe(17);
  });
  it.each(["cc-number", "one-time-code", "current-password"])(
    "excludes autocomplete %s",
    (autocomplete) => {
      document.body.innerHTML = `<input aria-label="Question" autocomplete="${autocomplete}">`;
      expect(eligible(document.querySelector("input")!, false)).toBe(false);
    },
  );
  it("excludes disabled, read-only and hidden ancestors", () => {
    document.body.innerHTML =
      '<div hidden><input aria-label="Question"></div><textarea readonly aria-label="Question"></textarea><input disabled aria-label="Question">';
    for (const el of document.querySelectorAll<HTMLElement>("input,textarea"))
      expect(eligible(el, false)).toBe(false);
  });
  it("inserts inert plain text and emits input and change", () => {
    const el = document.createElement("textarea");
    document.body.append(el);
    let events = 0;
    el.addEventListener("input", () => events++);
    el.addEventListener("change", () => events++);
    assignText(el, "<script>alert(1)</script>");
    expect(valueOf(el)).toBe("<script>alert(1)</script>");
    expect(document.querySelector("script")).toBeNull();
    expect(events).toBe(2);
  });
  it("undo preserves subsequent edits", () => {
    expect(mayUndo("edited", "inserted")).toBe(false);
    expect(mayUndo("inserted", "inserted")).toBe(true);
  });
  it("trusted operations cannot originate at a webpage", () => {
    expect(
      trustedPage({ id: "x", url: "https://evil.test/popup.html" }, "x"),
    ).toBe(false);
    expect(
      trustedPage({ id: "x", url: "chrome-extension://x/popup.html" }, "x"),
    ).toBe(true);
    expect(supportedUrl("chrome://settings")).toBe(false);
  });
});
