const $ = (id) => document.getElementById(id);
const STATES = {
  idle: "Pronto. Nada sendo lido.",
  loading: "Preparando a voz…",
  playing: "Lendo…",
  paused: "Pausado.",
  error: "Erro",
};
let host = null;

const send = (msg) => browser.runtime.sendMessage(msg);

async function refresh() {
  const st = await send({ type: "status" });
  const online = st && !st.offline;
  $("dot").className = `dot ${online ? "on" : "off"}`;
  $("offline").style.display = online ? "none" : "block";
  if (!online) {
    $("state").textContent = "";
    return;
  }
  $("state").textContent = st.state === "error" ? `Erro: ${st.error}` : STATES[st.state] || st.state;
  if (!$("voice").options.length) {
    for (const v of st.voices) $("voice").add(new Option(v, v));
  }
  if (document.activeElement !== $("voice")) $("voice").value = st.voice;
  if (document.activeElement !== $("speed")) {
    const match = [...$("speed").options].find((o) => Number(o.value) === st.speed);
    if (!match) $("speed").add(new Option(`${st.speed}×`, String(st.speed)));
    $("speed").value = String(match ? match.value : st.speed);
  }
}

async function init() {
  const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
  try {
    host = new URL(tab.url).hostname;
  } catch {
    host = null;
  }
  const s = await browser.storage.local.get(["disabledSites", "showBubble"]);
  $("site").checked = !host || !(s.disabledSites || []).includes(host);
  $("site").disabled = !host;
  $("bubble").checked = s.showBubble !== false;

  $("toggle").onclick = () => send({ type: "control", action: "toggle" }).then(refresh);
  $("stop").onclick = () => send({ type: "control", action: "stop" }).then(refresh);
  $("voice").onchange = () => send({ type: "settings", data: { voice: $("voice").value } });
  $("speed").onchange = () => send({ type: "settings", data: { speed: Number($("speed").value) } });
  $("bubble").onchange = () => browser.storage.local.set({ showBubble: $("bubble").checked });
  $("site").onchange = async () => {
    const { disabledSites = [] } = await browser.storage.local.get("disabledSites");
    const rest = disabledSites.filter((h) => h !== host);
    await browser.storage.local.set({ disabledSites: $("site").checked ? rest : [...rest, host] });
  };

  refresh();
  setInterval(refresh, 1000);
}

init();
