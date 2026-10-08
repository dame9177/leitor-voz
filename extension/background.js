// Bridge between pages and the local desktop app (which holds the OpenAI key).
// Content scripts can't call 127.0.0.1 themselves: their requests carry the
// page's Origin, which the app rejects on purpose.

const DEFAULT_PORT = 47321;

async function apiBase() {
  const { port } = await browser.storage.local.get("port");
  return `http://127.0.0.1:${port || DEFAULT_PORT}`;
}

async function api(path, body) {
  const init = body === undefined
    ? {}
    : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  let resp;
  try {
    resp = await fetch((await apiBase()) + path, init);
  } catch (e) {
    return { offline: true, error: "O app Leitor de voz não está rodando. Abra-o (comando: leitor)." };
  }
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) return { error: data.error || `HTTP ${resp.status}` };
  return data;
}

// -- messages from content scripts and the popup ------------------------------

browser.runtime.onMessage.addListener((msg) => {
  switch (msg.type) {
    case "read":
      return api("/read", { segments: msg.segments });
    case "control":
      return api("/control", { action: msg.action });
    case "status":
      return api("/status");
    case "settings":
      return api("/settings", msg.data);
  }
  return undefined;
});

// -- context menu ----------------------------------------------------------------

browser.runtime.onInstalled.addListener(() => {
  browser.contextMenus.create({ id: "read-selection", title: "Ler em voz alta", contexts: ["selection"] });
  browser.contextMenus.create({ id: "read-block", title: "Ler este parágrafo em voz alta", contexts: ["page", "link"] });
  browser.contextMenus.create({ id: "read-from-here", title: "Ler daqui até o fim", contexts: ["page", "link"] });
});

browser.contextMenus.onClicked.addListener((info, tab) => {
  if (!tab || tab.id < 0) return;
  const target = { frameId: info.frameId ?? 0 };
  const kind = {
    "read-selection": "menu-read-selection",
    "read-block": "menu-read-block",
    "read-from-here": "menu-read-from-here",
  }[info.menuItemId];
  if (!kind) return;
  browser.tabs.sendMessage(tab.id, { type: kind, selectionText: info.selectionText }, target).catch(() => {
    // Page without our content script (e.g. about: pages): read the selection directly.
    if (info.selectionText) api("/read", { segments: [{ id: "0", text: info.selectionText }] });
  });
});

// -- keyboard shortcuts -----------------------------------------------------------

browser.commands.onCommand.addListener(async (command) => {
  if (command === "toggle" || command === "stop") {
    api("/control", { action: command });
    return;
  }
  if (command === "read") {
    const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
    if (tab) browser.tabs.sendMessage(tab.id, { type: "command-read" }).catch(() => {});
  }
});
