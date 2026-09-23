const sensitive =
  /(password|passcode|\botp\b|one.?time|verification.?code|security.?code|credit.?card|card.?number|\bcvv\b|\bcvc\b|auth.?code)/i;
export function questionFor(el: HTMLElement): string {
  const explicit = el
    .getAttribute("aria-labelledby")
    ?.split(/\s+/)
    .map((id) => document.getElementById(id)?.textContent || "")
    .join(" ")
    .trim();
  const labels =
    "labels" in el
      ? Array.from((el as HTMLInputElement).labels || [])
          .map((l) => l.textContent?.trim())
          .join(" ")
      : "";
  return (
    explicit ||
    el.getAttribute("aria-label") ||
    labels ||
    el.getAttribute("placeholder") ||
    ""
  )
    .trim()
    .slice(0, 2000);
}
export function eligible(el: HTMLElement, checkLayout = true): boolean {
  if (
    el.closest("[data-questionnaire-controls]") ||
    el.closest('[hidden],[inert],[aria-hidden="true"]')
  )
    return false;
  if (
    el instanceof HTMLInputElement &&
    !["text", "search", "url", "email", "tel"].includes(el.type)
  )
    return false;
  if (
    !(
      el instanceof HTMLInputElement ||
      el instanceof HTMLTextAreaElement ||
      el.getAttribute("contenteditable") === "true" ||
      el.getAttribute("contenteditable") === "plaintext-only"
    )
  )
    return false;
  if (
    el.matches(":disabled,[readonly]") ||
    sensitive.test(
      [
        el.id,
        el.getAttribute("name"),
        el.getAttribute("autocomplete"),
        questionFor(el),
      ].join(" "),
    )
  )
    return false;
  if (
    /cc-|current-password|new-password|one-time-code/.test(
      el.getAttribute("autocomplete") || "",
    )
  )
    return false;
  if (el.isContentEditable && el.querySelector("*")) return false; // Only tested plain-text surfaces.
  if (
    checkLayout &&
    (!el.getClientRects().length ||
      getComputedStyle(el).visibility === "hidden")
  )
    return false;
  return !!questionFor(el);
}
export function valueOf(el: HTMLElement) {
  return el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement
    ? el.value
    : el.textContent || "";
}
export function assignText(el: HTMLElement, text: string) {
  if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
    const prototype =
      el instanceof HTMLInputElement
        ? HTMLInputElement.prototype
        : HTMLTextAreaElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, "value")!.set!.call(el, text);
  } else el.textContent = text;
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
}
export function mayUndo(current: string, inserted: string) {
  return current === inserted;
}
