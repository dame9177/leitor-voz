// Leitor de voz — in-page UI: hover 🔊 on paragraphs, bubble on selection,
// highlight of the paragraph being read. Audio is played by the desktop app.
(() => {
  if (window.__leitorVoz) return;
  window.__leitorVoz = true;

  const MIN_CHARS = 20;
  const MAX_CHARS = 4000;
  const MAX_FOLLOWING_CHARS = 40000; // "ler daqui até o fim" safety cap
  const BLOCK_TAGS = new Set([
    "P", "LI", "TD", "TH", "DD", "DT", "BLOCKQUOTE", "H1", "H2", "H3", "H4", "H5", "H6",
    "FIGCAPTION", "PRE", "LABEL", "SUMMARY", "CAPTION", "LEGEND",
  ]);
  const SKIP_TAGS = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEXTAREA", "INPUT", "SELECT", "SVG", "CANVAS", "VIDEO", "AUDIO", "IFRAME"]);
  const BLOCK_DISPLAYS = new Set(["block", "list-item", "table-cell", "flow-root", "flex", "grid"]);

  let enabled = true;
  let showBubble = true;
  let hovered = null;        // block element under the mouse
  let lastContextBlock = null;
  let reading = null;        // { id, elements: Map<segmentId, Element> }
  let pollTimer = null;
  let hideTimer = null;

  // -- settings ----------------------------------------------------------------

  const host = location.hostname;
  browser.storage.local.get(["disabledSites", "showBubble"]).then((s) => {
    enabled = !(s.disabledSites || []).includes(host);
    showBubble = s.showBubble !== false;
  });
  browser.storage.onChanged.addListener((changes) => {
    if (changes.disabledSites) enabled = !(changes.disabledSites.newValue || []).includes(host);
    if (changes.showBubble) showBubble = changes.showBubble.newValue !== false;
    if (!enabled) { hideButton(); hideBubble(); }
  });

  // -- text block detection ------------------------------------------------------

  function isEditable(el) {
    return el.isContentEditable || el.closest("input, textarea, select, [contenteditable=''], [contenteditable='true']");
  }

  function hasDirectText(el) {
    for (const node of el.childNodes) {
      if (node.nodeType === Node.TEXT_NODE && node.textContent.trim().length > 1) return true;
    }
    return false;
  }

  function isTextBlock(el) {
    if (!(el instanceof HTMLElement) || SKIP_TAGS.has(el.tagName)) return false;
    if (BLOCK_TAGS.has(el.tagName)) return true;
    if (!hasDirectText(el)) return false;
    return BLOCK_DISPLAYS.has(getComputedStyle(el).display);
  }

  function blockText(el) {
    return (el.innerText || "").replace(/\s+\n/g, "\n").trim();
  }

  function isVisible(el) {
    if (!el.getClientRects().length) return false;
    const style = getComputedStyle(el);
    return style.visibility !== "hidden" && style.display !== "none";
  }

  // A text that is one item of a horizontal flex/grid row (e.g. "B)" + answer
  // text in a multiple-choice option) should be read together with its row.
  function widenToRow(el) {
    for (let i = 0; i < 2; i++) {
      const parent = el.parentElement;
      if (!parent || parent === document.body || ui.contains(parent)) break;
      const style = getComputedStyle(parent);
      const row = /flex|grid/.test(style.display) && !/column/.test(style.flexDirection);
      // Only small rows (label + text + icon), never page-layout containers.
      if (!row || parent.children.length > 4 || blockText(parent).length > MAX_CHARS) break;
      el = parent;
    }
    return el;
  }

  function findBlock(start) {
    let el = start instanceof Element ? start : start?.parentElement;
    for (let depth = 0; el && el !== document.body && depth < 10; depth++, el = el.parentElement) {
      if (ui.contains(el) || isEditable(el)) return null;
      if (isTextBlock(el)) {
        el = widenToRow(el);
        const len = blockText(el).length;
        return len >= MIN_CHARS && len <= MAX_CHARS ? el : null;
      }
    }
    return null;
  }

  // Outermost text blocks in document order, starting at `first`.
  function blocksFrom(first) {
    const blocks = [first];
    let total = blockText(first).length;
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT, {
      acceptNode(el) {
        if (SKIP_TAGS.has(el.tagName) || el === ui) return NodeFilter.FILTER_REJECT;
        return isTextBlock(el) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP;
      },
    });
    walker.currentNode = deepestLast(first); // continue right after `first`'s subtree
    let el;
    while ((el = walker.nextNode()) && total < MAX_FOLLOWING_CHARS) {
      const row = widenToRow(el);
      if (!row.contains(first) && !row.contains(blocks[blocks.length - 1])) el = row;
      // Skip this block's descendants: its innerText already includes them.
      walker.currentNode = deepestLast(el);
      if (!isVisible(el)) continue;
      const text = blockText(el);
      if (text.length < 2) continue;
      blocks.push(el);
      total += text.length;
    }
    return blocks;
  }

  function deepestLast(el) {
    while (el.lastElementChild) el = el.lastElementChild;
    return el;
  }

  // -- floating UI (shadow DOM, immune to page CSS) --------------------------------

  const ui = document.createElement("leitor-voz-ui");
  const shadow = ui.attachShadow({ mode: "closed" });
  shadow.innerHTML = `
    <style>
      :host { all: initial; }
      .btn {
        position: fixed; z-index: 2147483647; display: none;
        width: 26px; height: 26px; border-radius: 50%; border: none; cursor: pointer;
        background: #2f6f5e; color: #fff; font: 14px/26px system-ui, sans-serif; text-align: center;
        box-shadow: 0 2px 8px rgba(0,0,0,.25); opacity: .85; padding: 0;
        transition: opacity .12s, transform .12s;
      }
      .btn:hover { opacity: 1; transform: scale(1.12); }
      .bubble { width: auto; padding: 0 10px; border-radius: 14px; font-size: 13px; }
      .toast {
        position: fixed; z-index: 2147483647; right: 16px; bottom: 16px; max-width: 320px; display: none;
        background: #1f2a27; color: #f4f1e8; font: 13px/1.4 system-ui, sans-serif;
        padding: 10px 14px; border-radius: 10px; box-shadow: 0 4px 16px rgba(0,0,0,.3);
      }
    </style>
    <button class="btn" id="hover" title="Ler em voz alta (Shift+clique: daqui até o fim)">🔊</button>
    <button class="btn bubble" id="bubble" title="Ler a seleção em voz alta">🔊 Ler</button>
    <div class="toast" id="toast"></div>`;
  const hoverBtn = shadow.getElementById("hover");
  const bubble = shadow.getElementById("bubble");
  const toast = shadow.getElementById("toast");
  document.documentElement.appendChild(ui);

  function placeButton(block) {
    const r = block.getBoundingClientRect();
    let x = r.left - 32;
    if (x < 4) x = Math.max(4, r.left + 2);
    hoverBtn.style.left = `${x}px`;
    hoverBtn.style.top = `${Math.max(4, r.top)}px`;
    hoverBtn.style.display = "block";
  }

  function hideButton() {
    hoverBtn.style.display = "none";
    hovered = null;
  }

  function hideBubble() {
    bubble.style.display = "none";
  }

  let toastTimer = null;
  function showToast(text) {
    toast.textContent = text;
    toast.style.display = "block";
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (toast.style.display = "none"), 5000);
  }

  // -- hover --------------------------------------------------------------------------

  let lastMove = null;
  let moveTimer = null;
  document.addEventListener("mousemove", (e) => {
    if (!enabled) return;
    lastMove = e;
    if (moveTimer) return;
    moveTimer = setTimeout(() => {
      moveTimer = null;
      const e = lastMove;
      const path = e.composedPath ? e.composedPath() : [];
      if (path.includes(ui)) {
        clearTimeout(hideTimer);
        return;
      }
      const block = findBlock(e.target);
      if (block) {
        clearTimeout(hideTimer);
        if (block !== hovered) {
          hovered = block;
          placeButton(block);
        }
      } else if (hovered) {
        clearTimeout(hideTimer);
        hideTimer = setTimeout(hideButton, 700);
      }
    }, 50);
  }, { passive: true });

  window.addEventListener("scroll", () => {
    if (hovered) placeButton(hovered);
    hideBubble();
  }, { passive: true, capture: true });

  hoverBtn.addEventListener("mousedown", (e) => e.preventDefault()); // keep page selection/focus
  hoverBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    if (!hovered) return;
    readBlocks(e.shiftKey ? blocksFrom(hovered) : [hovered]);
  });

  // -- selection bubble ------------------------------------------------------------

  function currentSelection() {
    const sel = window.getSelection();
    const text = sel ? sel.toString().trim() : "";
    return text.length >= 2 ? { sel, text } : null;
  }

  document.addEventListener("mouseup", (e) => {
    if (!enabled || !showBubble || (e.composedPath && e.composedPath().includes(ui))) return;
    setTimeout(() => {
      const s = currentSelection();
      if (!s || isEditable(e.target instanceof Element ? e.target : document.body)) {
        hideBubble();
        return;
      }
      const rects = s.sel.getRangeAt(0).getClientRects();
      const last = rects[rects.length - 1];
      if (!last) return;
      bubble.style.left = `${Math.min(last.right + 6, window.innerWidth - 80)}px`;
      bubble.style.top = `${Math.min(last.bottom + 6, window.innerHeight - 34)}px`;
      bubble.style.display = "block";
    }, 10);
  });

  document.addEventListener("selectionchange", () => {
    if (!currentSelection()) hideBubble();
  });

  bubble.addEventListener("mousedown", (e) => e.preventDefault());
  bubble.addEventListener("click", (e) => {
    e.stopPropagation();
    const s = currentSelection();
    hideBubble();
    if (s) readSelection(s.text);
  });

  // -- reading + highlight ------------------------------------------------------------

  async function send(segments, elements) {
    clearHighlight();
    const resp = await browser.runtime.sendMessage({ type: "read", segments });
    if (resp?.error) {
      showToast(resp.error);
      return;
    }
    reading = { id: resp.reading_id, elements };
    startPolling();
  }

  function readBlocks(blocks) {
    const segments = [];
    const elements = new Map();
    blocks.forEach((el, i) => {
      const text = blockText(el);
      if (!text) return;
      const id = `b${i}`;
      segments.push({ id, text });
      elements.set(id, el);
    });
    if (segments.length) send(segments, elements);
  }

  function readSelection(text) {
    send([{ id: "sel", text }], new Map());
  }

  function clearHighlight() {
    document.querySelectorAll(".leitor-voz-reading").forEach((el) => el.classList.remove("leitor-voz-reading"));
  }

  function startPolling() {
    clearInterval(pollTimer);
    pollTimer = setInterval(async () => {
      if (!reading) return stopPolling();
      const st = await browser.runtime.sendMessage({ type: "status" }).catch(() => null);
      if (!st || st.offline || st.reading_id !== reading.id) {
        // Another reading (maybe from another tab) replaced ours.
        if (st && !st.offline && st.reading_id && st.reading_id !== reading.id) stopPolling();
        return;
      }
      if (st.state === "error") {
        showToast(st.error || "Erro no leitor de voz.");
        return stopPolling();
      }
      if (st.state === "idle") return stopPolling();
      const el = reading.elements.get(st.segment_id);
      if (el && !el.classList.contains("leitor-voz-reading")) {
        clearHighlight();
        el.classList.add("leitor-voz-reading");
        const r = el.getBoundingClientRect();
        if (r.top < 0 || r.bottom > window.innerHeight) el.scrollIntoView({ block: "center", behavior: "smooth" });
      }
    }, 350);
  }

  function stopPolling() {
    clearInterval(pollTimer);
    pollTimer = null;
    reading = null;
    clearHighlight();
  }

  // -- context menu + shortcuts (from background) ----------------------------------

  document.addEventListener("contextmenu", (e) => {
    lastContextBlock = findBlock(e.target);
  }, true);

  browser.runtime.onMessage.addListener((msg) => {
    if (msg.type === "menu-read-selection") {
      const s = currentSelection();
      readSelection(s ? s.text : msg.selectionText || "");
    } else if (msg.type === "menu-read-block" || msg.type === "menu-read-from-here") {
      if (!lastContextBlock) {
        showToast("Não encontrei um parágrafo aqui. Selecione o texto e use “Ler em voz alta”.");
        return;
      }
      readBlocks(msg.type === "menu-read-from-here" ? blocksFrom(lastContextBlock) : [lastContextBlock]);
    } else if (msg.type === "command-read") {
      const s = currentSelection();
      if (s) readSelection(s.text);
      else if (hovered) readBlocks([hovered]);
    }
  });
})();
