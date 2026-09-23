import type { Page, Pending } from "./types";
export const extensionAvailable =
  typeof chrome !== "undefined" && !!chrome.runtime?.id;
export async function rpc<T = any>(
  type: string,
  data: Record<string, unknown> = {},
): Promise<T> {
  if (!extensionAvailable)
    throw new Error(
      "Open the installed extension to connect to your local companion. This browser preview contains no personal data.",
    );
  const result = await chrome.runtime.sendMessage({ type, ...data });
  if (!result?.ok)
    throw new Error(
      result?.error || "The extension did not respond. Reopen the panel.",
    );
  return result.data as T;
}
export const host = <T = any>(
  operation: string,
  data: Record<string, unknown> = {},
  id: string = crypto.randomUUID(),
) => rpc<T>("host", { operation, data, id });
export const getPage = () => rpc<Page | null>("page");
export const pending = () => rpc<Pending[]>("pending");
