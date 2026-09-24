export function trustedPage(
  sender: chrome.runtime.MessageSender,
  extensionId: string,
) {
  if (sender.id !== extensionId) return false;
  return ["popup.html", "manage.html", "demo.html"].some(
    (path) => sender.url === `chrome-extension://${extensionId}/${path}`,
  );
}
export function supportedUrl(raw: string) {
  try {
    return ["https:", "http:"].includes(new URL(raw).protocol);
  } catch {
    return false;
  }
}
