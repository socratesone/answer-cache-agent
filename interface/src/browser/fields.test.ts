// @vitest-environment jsdom
import { describe, it, expect, beforeEach } from "vitest";
import { eligible, questionFor, assignText, valueOf, mayUndo } from "./fields";
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
  it.each(["password", "hidden", "checkbox", "radio", "file", "number"])(
    "excludes %s",
    (type) => {
      const el = document.createElement("input");
      el.type = type;
      el.setAttribute("aria-label", "Question");
      expect(eligible(el, false)).toBe(false);
    },
  );
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
      trustedPage({ id: "x", url: "https://evil.test/panel.html" }, "x"),
    ).toBe(false);
    expect(
      trustedPage({ id: "x", url: "chrome-extension://x/panel.html" }, "x"),
    ).toBe(true);
    expect(supportedUrl("chrome://settings")).toBe(false);
  });
});
