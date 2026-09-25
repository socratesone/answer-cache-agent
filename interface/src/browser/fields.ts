const sensitive = /(password|passcode|\botp\b|one.?time|verification.?code|security.?code|credit.?card|card.?number|\bcvv\b|\bcvc\b|auth.?code)/i;
export type ControlKind = "text" | "select" | "radio" | "checkbox" | "combobox" | "file";
// Keys mappings and option matching; must keep non-Latin letters or every CJK question collides on "".
export const normalize = (text: string) => text.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();
function labelled(el: HTMLElement) {
  const ids = el.getAttribute("aria-labelledby")?.split(/\s+/) || [];
  const explicit = ids.map((id) => document.getElementById(id)?.textContent || "").join(" ").trim();
  const labels = "labels" in el
    ? Array.from((el as HTMLInputElement).labels || []).map((l) => l.textContent?.trim()).join(" ")
    : "";
  return explicit || el.getAttribute("aria-label") || labels || "";
}
function nearbyPrompt(el: HTMLElement): string {
  const candidates: Element[] = [];
  if (el.previousElementSibling) candidates.push(el.previousElementSibling);
  if (el.parentElement?.previousElementSibling) candidates.push(el.parentElement.previousElementSibling);
  for (const parent of [el.parentElement, el.parentElement?.parentElement]) {
    if (!parent || parent.matches("form,body")) continue;
    for (const child of parent.children) {
      if (child === el || child.contains(el)) break;
      if (child.matches('label,legend,h1,h2,h3,h4,p,[class*="question"],[class*="label"]')) candidates.push(child);
    }
  }
  for (const candidate of candidates.reverse()) {
    if (candidate.querySelector("input,textarea,select")) continue;
    const text = candidate.textContent?.replace(/\s+/g, " ").trim() || "";
    if (text.length >= 3 && text.length <= 500) return text;
  }
  return "";
}
export function groupFor(el: HTMLElement): HTMLElement | null {
  if (!(el instanceof HTMLInputElement) || !["radio", "checkbox"].includes(el.type)) return null;
  const group = el.closest<HTMLElement>('fieldset,[role="radiogroup"],[role="group"]');
  if (group) return group;
  const parent = el.parentElement?.parentElement;
  if (!parent) return null;
  const choices = Array.from(parent.querySelectorAll<HTMLInputElement>('input[type="radio"],input[type="checkbox"]'));
  if (choices.length < 2 || choices.length > 8) return null;
  if (el.type === "radio" && el.name && choices.every((c) => c.name === el.name)) return parent;
  if (el.type === "checkbox" && choices.length === 2 &&
      choices.every((c) => ["yes", "no"].includes(normalize(labelled(c))))) return parent;
  return null;
}
export function groupChoices(el: HTMLElement): HTMLInputElement[] {
  const group = groupFor(el);
  if (!group || !(el instanceof HTMLInputElement)) return [el as HTMLInputElement];
  const selector = el.type === "radio" ? 'input[type="radio"]' : 'input[type="checkbox"]';
  return Array.from(group.querySelectorAll<HTMLInputElement>(selector))
    .filter((c) => !el.name || c.name === el.name || el.type === "checkbox");
}
export function questionFor(el: HTMLElement): string {
  const group = groupFor(el);
  const groupLabel = group && (group.querySelector("legend")?.textContent ||
    group.getAttribute("aria-label") ||
    group.getAttribute("aria-labelledby")?.split(/\s+/).map((id) => document.getElementById(id)?.textContent).join(" ") ||
    group.querySelector("h1,h2,h3,h4,p")?.textContent || "");
  const label = labelled(el);
  const name = el.getAttribute("name") || "";
  const fallback = el.getAttribute("placeholder") ||
    (/\[\d+\]|^(answers?|fields?|questions?)\W/i.test(name) ? "" : name.replace(/[_-]/g, " "));
  return String(groupLabel || label || nearbyPrompt(el) || fallback).trim().slice(0, 2000);
}
export function kindOf(el: HTMLElement): ControlKind {
  if (el instanceof HTMLInputElement && el.type === "file") return "file";
  if (el instanceof HTMLSelectElement) return "select";
  if (el instanceof HTMLInputElement && el.type === "radio") return "radio";
  if (el instanceof HTMLInputElement && el.type === "checkbox") return "checkbox";
  if (el.getAttribute("role") === "combobox") return "combobox";
  return "text";
}
export function canOfferAi(el: HTMLElement): boolean {
  return kindOf(el) === "text" && (el instanceof HTMLTextAreaElement || el.isContentEditable ||
    (el instanceof HTMLInputElement && el.type === "text" && el.maxLength > 180));
}
export function eligible(el: HTMLElement, checkLayout = true): boolean {
  if (el.closest("[data-questionnaire-controls]") || el.closest('[hidden],[inert],[aria-hidden="true"]')) return false;
  if (el instanceof HTMLInputElement &&
    !["text", "search", "url", "email", "tel", "number", "radio", "checkbox", "file"].includes(el.type)) return false;
  if (!(el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement || el instanceof HTMLSelectElement ||
    el.getAttribute("contenteditable") === "true" || el.getAttribute("contenteditable") === "plaintext-only" ||
    el.getAttribute("role") === "combobox")) return false;
  if (el.matches(":disabled,[readonly],[aria-disabled=true]") || sensitive.test([
    el.id, el.getAttribute("name"), el.getAttribute("autocomplete"), questionFor(el),
  ].join(" "))) return false;
  if (/cc-|current-password|new-password|one-time-code/.test(el.getAttribute("autocomplete") || "")) return false;
  if (el.isContentEditable && el.querySelector("*")) return false;
  if (checkLayout && (!el.getClientRects().length || getComputedStyle(el).visibility === "hidden")) return false;
  return !!questionFor(el);
}
export function optionsFor(el: HTMLElement): string[] {
  if (el instanceof HTMLSelectElement)
    return Array.from(el.options).filter((o) => !o.disabled && o.value).map((o) => o.textContent?.trim() || o.value);
  if (el instanceof HTMLInputElement && ["radio", "checkbox"].includes(el.type))
    return groupChoices(el).map((c) => labelled(c) || c.value || "Yes");
  if (el.getAttribute("role") === "combobox") {
    const list = el.getAttribute("aria-controls") || el.getAttribute("aria-owns");
    return list ? Array.from(document.getElementById(list)?.querySelectorAll('[role="option"]') || [])
      .map((o) => o.textContent?.trim() || "").filter(Boolean) : [];
  }
  return [];
}
export function valueOf(el: HTMLElement): string {
  if (el instanceof HTMLInputElement && el.type === "file") return Array.from(el.files || []).map((f) => f.name).join(", ");
  if (el instanceof HTMLSelectElement) return el.value ? el.selectedOptions[0]?.textContent?.trim() || el.value : "";
  if (el instanceof HTMLInputElement && ["radio", "checkbox"].includes(el.type)) {
    const selected = groupChoices(el).find((c) => c.checked);
    return selected ? labelled(selected) || selected.value || "Yes" : "";
  }
  if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) return el.value;
  return el.getAttribute("aria-valuetext") || el.textContent?.trim() || "";
}
export function assignText(el: HTMLElement, text: string) {
  if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
    const prototype = el instanceof HTMLInputElement ? HTMLInputElement.prototype : HTMLTextAreaElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, "value")!.set!.call(el, text);
  } else el.textContent = text;
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
}
export async function assignChoice(el: HTMLElement, text: string): Promise<boolean> {
  const wanted = normalize(text);
  if (!wanted) return false;
  if (el instanceof HTMLSelectElement) {
    const option = Array.from(el.options).find((o) => !o.disabled && [o.textContent, o.value].some((s) => normalize(s || "") === wanted));
    if (!option) return false;
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")!.set!.call(el, option.value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    return normalize(valueOf(el)) === normalize(option.textContent || option.value);
  }
  if (el instanceof HTMLInputElement && ["radio", "checkbox"].includes(el.type)) {
    const options = groupChoices(el);
    const choice = options.find((c) => [labelled(c), c.value].some((s) => normalize(s || "") === wanted));
    if (!choice) return false;
    choice.click();
    return choice.checked;
  }
  if (el.getAttribute("role") === "combobox") {
    el.click();
    const listId = el.getAttribute("aria-controls") || el.getAttribute("aria-owns");
    const find = () => Array.from((listId ? document.getElementById(listId) : document)?.querySelectorAll('[role="option"]') || [])
      .find((o) => normalize(o.textContent || "") === wanted) as HTMLElement | undefined;
    let option = find();
    if (!option && el instanceof HTMLInputElement) {
      assignText(el, text);
      await new Promise((resolve) => setTimeout(resolve, 180));
      option = find();
    }
    if (!option) return false;
    option.click();
    await new Promise((resolve) => setTimeout(resolve, 60));
    return normalize(valueOf(el)) === wanted || option.getAttribute("aria-selected") === "true";
  }
  return false;
}
export function mayUndo(current: string, inserted: string) { return current === inserted; }
