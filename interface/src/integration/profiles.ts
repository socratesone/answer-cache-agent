export type Profile = { id: string; label: string; dimension: string; value: string };
export type Profiles = { items: Profile[]; defaultId: string };
const DEFAULT: Profile = { id: "default", label: "Default", dimension: "", value: "" };
export async function profiles(): Promise<Profiles> {
  const saved = (await chrome.storage.local.get("answerProfiles")).answerProfiles as Profiles | undefined;
  const items = [DEFAULT, ...(saved?.items || []).filter((p) =>
    p.id !== "default" && /^[a-zA-Z0-9_-]{1,80}$/.test(p.id) &&
    typeof p.label === "string" && typeof p.dimension === "string" && typeof p.value === "string")];
  const defaultId = items.some((p) => p.id === saved?.defaultId) ? saved!.defaultId : "default";
  return { items, defaultId };
}
export async function saveProfiles(value: Profiles) {
  await chrome.storage.local.set({ answerProfiles: value });
}
export function categoryHints(profile: Profile) {
  return profile.dimension && profile.value
    ? [{ dimension: profile.dimension, value: profile.value, source: "user" as const }]
    : [];
}
