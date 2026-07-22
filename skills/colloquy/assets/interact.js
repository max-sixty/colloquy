/* Comment/status layer for colloquy pages, loaded via <script src="/interact.js" defer>.
 * Talks to interact.py's server: polls GET /api/state, posts events to POST /api/event.
 * Everything it injects is namespaced .ih-* and marked .ih-ui so anchoring skips it. */
(() => {
  "use strict";

  const VERSION_MATCH = location.pathname.match(/\/versions\/v(\d+)\.html$/);
  const VNUM = VERSION_MATCH ? parseInt(VERSION_MATCH[1], 10) : null;
  const POLL_MS = 2000;

  // ---------- styles ----------
  const style = document.createElement("style");
  style.textContent = `
    .ih-ui { font-family: system-ui, -apple-system, sans-serif; font-size: 13.5px; line-height: 1.45; color: #1f2328; box-sizing: border-box; }
    .ih-ui *, .ih-ui *::before, .ih-ui *::after { box-sizing: inherit; }
    .ih-banner { position: fixed; top: 0; left: 0; right: 0; z-index: 9000; height: 42px;
      display: flex; align-items: center; gap: 10px; padding: 0 14px;
      background: #ffffffee; backdrop-filter: blur(6px); border-bottom: 1px solid #e4e7eb; }
    .ih-dot { width: 9px; height: 9px; border-radius: 50%; background: #9ca3af; flex: none; }
    .ih-dot.working { background: #2563eb; animation: ih-pulse 1.4s ease-in-out infinite; }
    .ih-dot.listening { background: #16a34a; }
    .ih-dot.away { background: #d97706; }
    .ih-dot.offline { background: #dc2626; }
    @keyframes ih-pulse { 50% { opacity: .35; } }
    .ih-status-text { color: #374151; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .ih-status-text .ih-age { color: #9ca3af; }
    .ih-spacer { flex: 1; }
    .ih-banner select { font: inherit; padding: 3px 6px; border: 1px solid #d1d5db; border-radius: 6px; background: #fff; max-width: 260px; }
    .ih-btn { font: inherit; padding: 4px 10px; border: 1px solid #d1d5db; border-radius: 6px; background: #fff; cursor: pointer; white-space: nowrap; }
    .ih-btn:hover { background: #f3f4f6; }
    .ih-btn.primary { background: #2563eb; border-color: #2563eb; color: #fff; }
    .ih-btn.primary:hover { background: #1d4ed8; }
    .ih-btn:disabled { opacity: .55; cursor: default; }
    .ih-latest-chip { background: #fef3c7; border: 1px solid #f59e0b; border-radius: 6px; padding: 3px 8px; }
    .ih-panel { position: fixed; top: 42px; right: 0; bottom: 0; width: 360px; z-index: 8900;
      background: #fff; border-left: 1px solid #e4e7eb; display: none; flex-direction: column; }
    .ih-panel.open { display: flex; }
    .ih-panel-head { display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; border-bottom: 1px solid #eef0f2; font-weight: 600; }
    .ih-threads { flex: 1; overflow-y: auto; padding: 10px 14px; }
    .ih-empty { color: #6b7280; padding: 18px 4px; }
    .ih-thread { border: 1px solid #e4e7eb; border-radius: 8px; padding: 10px; margin-bottom: 12px; }
    .ih-thread.flash { animation: ih-flash 1.2s ease-out; }
    @keyframes ih-flash { 0% { background: #fef9c3; } 100% { background: #fff; } }
    .ih-quote { margin: 0 0 8px; padding: 2px 8px; border-left: 3px solid #f59e0b; color: #6b7280; font-style: italic; cursor: pointer; overflow-wrap: anywhere; }
    .ih-quote:hover { color: #374151; }
    .ih-msg { margin: 8px 0; }
    .ih-msg-head { display: flex; gap: 6px; align-items: baseline; }
    .ih-msg-head b { font-size: 12.5px; }
    .ih-msg.claude .ih-msg-head b { color: #2563eb; }
    .ih-msg time { color: #9ca3af; font-size: 11.5px; }
    .ih-msg p { margin: 2px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; }
    .ih-thread form, .ih-general { display: flex; gap: 6px; margin-top: 8px; }
    .ih-thread textarea, .ih-general textarea { flex: 1; font: inherit; padding: 5px 8px; border: 1px solid #d1d5db; border-radius: 6px; resize: vertical; min-height: 32px; }
    .ih-thread-actions { display: flex; justify-content: space-between; margin-top: 8px; }
    .ih-resolve { border: none; background: none; color: #6b7280; cursor: pointer; font: inherit; }
    .ih-resolve:hover { color: #16a34a; }
    .ih-general { padding: 10px 14px; border-top: 1px solid #eef0f2; }
    .ih-details { margin-top: 6px; color: #6b7280; }
    .ih-system { color: #16a34a; margin: 8px 0; }
    .ih-fab { position: fixed; z-index: 9100; display: none; }
    .ih-composer { position: fixed; z-index: 9100; display: none; width: 320px; background: #fff;
      border: 1px solid #d1d5db; border-radius: 8px; box-shadow: 0 8px 24px rgba(0,0,0,.12); padding: 10px; }
    .ih-composer textarea { width: 100%; font: inherit; padding: 5px 8px; border: 1px solid #d1d5db; border-radius: 6px; min-height: 56px; resize: vertical; }
    .ih-composer-row { display: flex; justify-content: flex-end; gap: 6px; margin-top: 6px; }
    .ih-mark { background: #fde68a80; border-bottom: 2px solid #f59e0b; cursor: pointer; }
    .ih-mark:hover { background: #fde68a; }
    .ih-toast { position: fixed; bottom: 18px; right: 18px; z-index: 9200; background: #1f2328; color: #fff;
      padding: 9px 14px; border-radius: 8px; opacity: 0; transition: opacity .25s; pointer-events: none; }
    .ih-toast.show { opacity: .95; }
    .ih-badge { background: #dc2626; color: #fff; border-radius: 8px; padding: 0 5px; font-size: 11px; margin-left: 4px; }
    @media print { .ih-ui { display: none !important; } }
  `;
  document.head.appendChild(style);

  // ---------- scaffold ----------
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  const banner = el("div", "ih-ui ih-banner");
  const dot = el("span", "ih-dot");
  const statusText = el("span", "ih-status-text", "Connecting…");
  const latestChip = el("button", "ih-ui ih-btn ih-latest-chip", "");
  latestChip.style.display = "none";
  const versionSelect = document.createElement("select");
  const toggleBtn = el("button", "ih-btn", "Comments");
  const approveBtn = el("button", "ih-btn primary", "✓ Looks good");
  banner.append(
    dot,
    statusText,
    el("span", "ih-spacer"),
    latestChip,
    versionSelect,
    toggleBtn,
    approveBtn,
  );

  const panel = el("aside", "ih-ui ih-panel");
  const panelHead = el("div", "ih-panel-head");
  panelHead.append(
    el("span", "", "Comments"),
    Object.assign(el("button", "ih-btn", "×"), { onclick: () => setPanel(false) }),
  );
  const threadsBox = el("div", "ih-threads");
  const generalForm = el("form", "ih-general");
  const generalInput = document.createElement("textarea");
  generalInput.placeholder = "Comment on the whole page…";
  generalForm.append(generalInput, el("button", "ih-btn primary", "Send"));
  panel.append(panelHead, threadsBox, generalForm);

  const fab = el("button", "ih-ui ih-btn primary ih-fab", "💬 Comment");
  const composer = el("div", "ih-ui ih-composer");
  const composerInput = document.createElement("textarea");
  composerInput.placeholder = "Your comment…";
  const composerRow = el("div", "ih-composer-row");
  const composerCancel = el("button", "ih-btn", "Cancel");
  const composerSend = el("button", "ih-btn primary", "Comment");
  composerRow.append(composerCancel, composerSend);
  composer.append(composerInput, composerRow);
  const toast = el("div", "ih-ui ih-toast");

  document.body.append(banner, panel, fab, composer, toast);
  const basePaddingTop = parseFloat(getComputedStyle(document.body).paddingTop) || 0;
  document.body.style.paddingTop = basePaddingTop + 42 + "px";

  // ---------- state ----------
  let events = [];
  let lastEventsKey = "";
  let lastVersionsKey = "";
  let claudeMsgCount = -1;
  let panelOpen = false;
  let pendingAnchor = null;
  const rid = () => crypto.randomUUID().replaceAll("-", "").slice(0, 8);

  function setPanel(open) {
    panelOpen = open;
    panel.classList.toggle("open", open);
    document.body.style.paddingRight = open ? "360px" : "";
    if (open) renderThreads();
  }
  toggleBtn.onclick = () => setPanel(!panelOpen);

  function showToast(msg) {
    toast.textContent = msg;
    toast.classList.add("show");
    setTimeout(() => toast.classList.remove("show"), 3500);
  }

  async function post(event) {
    try {
      const res = await fetch("/api/event", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(event),
      });
      if (!res.ok) throw new Error(await res.text());
      await poll();
      return true;
    } catch {
      showToast("Couldn't send — server offline?");
      return false;
    }
  }

  // ---------- time ----------
  const ago = (ts) => {
    if (!ts) return "";
    const secs = Math.max(0, (Date.now() - new Date(ts).getTime()) / 1000);
    if (secs < 45) return "just now";
    if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
    if (secs < 86400) return `${Math.round(secs / 3600)}h ago`;
    return `${Math.round(secs / 86400)}d ago`;
  };

  // ---------- threads ----------
  const byId = () => new Map(events.map((e) => [e.id, e]));
  function rootOf(event, index) {
    let cur = event;
    for (let hops = 0; cur && cur.kind !== "comment" && hops < 50; hops++)
      cur = index.get(cur.parent);
    return cur && cur.kind === "comment" ? cur.id : null;
  }
  function buildThreads() {
    const index = byId();
    const threads = new Map();
    for (const e of events) {
      if (e.kind === "comment")
        threads.set(e.id, { root: e, msgs: [e], resolved: false });
    }
    for (const e of events) {
      const rootId =
        e.kind === "reply" || e.kind === "resolve" ? rootOf(e, index) : null;
      const thread = rootId && threads.get(rootId);
      if (!thread) continue;
      if (e.kind === "reply") thread.msgs.push(e);
      if (e.kind === "resolve") thread.resolved = true;
    }
    return [...threads.values()];
  }

  function msgNode(m) {
    const div = el("div", `ih-msg ${m.author}`);
    const head = el("div", "ih-msg-head");
    head.append(
      el("b", "", m.author === "claude" ? "Claude" : "You"),
      el("time", "", ago(m.ts)),
    );
    div.append(head, el("p", "", m.text || ""));
    return div;
  }

  function threadNode(t) {
    const div = el("div", "ih-thread");
    div.dataset.id = t.root.id;
    if (t.root.anchor?.quote) {
      const quote = el("blockquote", "ih-quote", `“${t.root.anchor.quote}”`);
      quote.onclick = () => {
        const mark = document.querySelector(`.ih-mark[data-ih="${t.root.id}"]`);
        if (mark) mark.scrollIntoView({ behavior: "smooth", block: "center" });
      };
      div.append(quote);
    }
    t.msgs.forEach((m) => div.append(msgNode(m)));
    if (!t.resolved) {
      const form = document.createElement("form");
      const input = document.createElement("textarea");
      input.placeholder = "Reply…";
      input.dataset.draftFor = t.root.id;
      const send = el("button", "ih-btn", "Reply");
      form.append(input, send);
      form.onsubmit = (ev) => {
        ev.preventDefault();
        const text = input.value.trim();
        if (text)
          post({
            kind: "reply",
            id: rid(),
            parent: t.root.id,
            version: VNUM,
            text,
          }).then((ok) => ok && (input.value = ""));
      };
      const actions = el("div", "ih-thread-actions");
      const resolve = el("button", "ih-resolve", "✓ Resolve");
      resolve.onclick = () => post({ kind: "resolve", id: rid(), parent: t.root.id });
      actions.append(el("span"), resolve);
      div.append(form, actions);
    }
    return div;
  }

  function renderThreads() {
    const drafts = {};
    threadsBox
      .querySelectorAll("[data-draft-for]")
      .forEach((t) => t.value && (drafts[t.dataset.draftFor] = t.value));
    threadsBox.textContent = "";
    const threads = buildThreads();
    const open = threads.filter((t) => !t.resolved);
    const resolved = threads.filter((t) => t.resolved);
    if (!threads.length)
      threadsBox.append(
        el(
          "div",
          "ih-empty",
          "No comments yet. Select any text on the page to comment on it, or use the box below.",
        ),
      );
    open.forEach((t) => threadsBox.append(threadNode(t)));
    for (const e of events)
      if (e.kind === "done")
        threadsBox.append(el("div", "ih-system", `✓ Approved ${ago(e.ts)}`));
    if (resolved.length) {
      const details = el("details", "ih-details");
      details.append(el("summary", "", `Resolved (${resolved.length})`));
      resolved.forEach((t) => details.append(threadNode(t)));
      threadsBox.append(details);
    }
    threadsBox
      .querySelectorAll("[data-draft-for]")
      .forEach(
        (t) => drafts[t.dataset.draftFor] && (t.value = drafts[t.dataset.draftFor]),
      );
    const openCount = open.length;
    toggleBtn.textContent = "";
    toggleBtn.append(document.createTextNode(`Comments (${openCount})`));
  }

  // ---------- anchors ----------
  const markedParents = new Set();
  function clearMarks() {
    document.querySelectorAll(".ih-mark").forEach((mark) => {
      const parent = mark.parentNode;
      while (mark.firstChild) parent.insertBefore(mark.firstChild, mark);
      mark.remove();
    });
    markedParents.forEach((p) => p.isConnected && p.normalize());
    markedParents.clear();
  }

  function textNodesUnder(rootEl) {
    const walker = document.createTreeWalker(rootEl, NodeFilter.SHOW_TEXT, {
      acceptNode: (n) =>
        n.parentElement?.closest(".ih-ui, script, style")
          ? NodeFilter.FILTER_REJECT
          : NodeFilter.FILTER_ACCEPT,
    });
    const nodes = [];
    for (let n = walker.nextNode(); n; n = walker.nextNode()) nodes.push(n);
    return nodes;
  }

  // Find `quote` in rootEl's text, whitespace-insensitively; returns [{node, start, end}] segments.
  function findQuote(rootEl, quote) {
    const nodes = textNodesUnder(rootEl);
    let raw = "";
    const origin = []; // origin[i] = {node, offset} for raw[i]
    for (const node of nodes)
      for (let i = 0; i < node.data.length; i++) {
        origin.push({ node, offset: i });
        raw += node.data[i];
      }
    let norm = "";
    const rawIdx = []; // rawIdx[j] = index into raw for norm[j]
    for (let i = 0; i < raw.length; i++) {
      if (/\s/.test(raw[i])) {
        if (norm.endsWith(" ") || !norm) continue;
        norm += " ";
      } else norm += raw[i];
      rawIdx.push(i);
    }
    const needle = quote.replace(/\s+/g, " ").trim();
    if (!needle) return null;
    const at = norm.indexOf(needle);
    if (at === -1) return null;
    const from = origin[rawIdx[at]];
    const to = origin[rawIdx[at + needle.length - 1]];
    const segments = [];
    let started = false;
    for (const node of nodes) {
      const start = node === from.node ? from.offset : started ? 0 : null;
      if (start === null) continue;
      started = true;
      const end = node === to.node ? to.offset + 1 : node.data.length;
      if (end > start) segments.push({ node, start, end });
      if (node === to.node) break;
    }
    return segments;
  }

  function applyAnchors() {
    clearMarks();
    for (const t of buildThreads()) {
      if (t.resolved || !t.root.anchor?.quote) continue;
      const rootEl =
        (t.root.anchor.section && document.getElementById(t.root.anchor.section)) ||
        document.body;
      const segments = findQuote(rootEl, t.root.anchor.quote);
      if (!segments) continue;
      for (const { node, start, end } of segments) {
        const target = node.splitText ? node : null;
        if (!target) continue;
        const middle = start > 0 ? target.splitText(start) : target;
        if (end - start < middle.data.length) middle.splitText(end - start);
        const mark = el("mark", "ih-mark");
        mark.dataset.ih = t.root.id;
        middle.parentNode.replaceChild(mark, middle);
        mark.append(middle);
        markedParents.add(mark.parentNode);
      }
    }
  }
  document.addEventListener("click", (ev) => {
    const mark = ev.target.closest?.(".ih-mark");
    if (!mark) return;
    setPanel(true);
    const thread = threadsBox.querySelector(`.ih-thread[data-id="${mark.dataset.ih}"]`);
    if (thread) {
      thread.scrollIntoView({ behavior: "smooth", block: "center" });
      thread.classList.add("flash");
      setTimeout(() => thread.classList.remove("flash"), 1300);
    }
  });

  // ---------- selection → comment ----------
  document.addEventListener("mouseup", (ev) => {
    if (ev.target.closest?.(".ih-ui")) return;
    setTimeout(() => {
      const sel = getSelection();
      if (!sel || sel.isCollapsed || sel.toString().trim().length < 3) {
        fab.style.display = "none";
        return;
      }
      const rect = sel.getRangeAt(0).getBoundingClientRect();
      fab.style.display = "block";
      fab.style.left = Math.min(rect.right + 6, innerWidth - 130) + "px";
      fab.style.top = Math.max(48, rect.top - 6) + "px";
    });
  });
  document.addEventListener("mousedown", (ev) => {
    if (!ev.target.closest?.(".ih-fab, .ih-composer")) {
      fab.style.display = "none";
      composer.style.display = "none";
    }
  });

  fab.onclick = () => {
    const sel = getSelection();
    if (!sel || sel.isCollapsed) return;
    const range = sel.getRangeAt(0);
    let node = range.commonAncestorContainer;
    if (node.nodeType !== Node.ELEMENT_NODE) node = node.parentElement;
    const section = node.closest("[id]:not(.ih-ui)")?.id || null;
    pendingAnchor = { section, quote: sel.toString().trim().slice(0, 400) };
    composer.style.left = fab.style.left;
    composer.style.top = fab.style.top;
    composer.style.display = "block";
    fab.style.display = "none";
    composerInput.value = "";
    composerInput.focus();
  };
  composerCancel.onclick = () => (composer.style.display = "none");
  composerSend.onclick = async () => {
    const text = composerInput.value.trim();
    if (!text || !pendingAnchor) return;
    if (
      await post({
        kind: "comment",
        id: rid(),
        version: VNUM,
        anchor: pendingAnchor,
        text,
      })
    ) {
      composer.style.display = "none";
      setPanel(true);
    }
  };
  composerInput.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && (ev.metaKey || ev.ctrlKey)) composerSend.onclick();
    if (ev.key === "Escape") composer.style.display = "none";
  });

  generalForm.onsubmit = (ev) => {
    ev.preventDefault();
    const text = generalInput.value.trim();
    if (text)
      post({ kind: "comment", id: rid(), version: VNUM, text }).then(
        (ok) => ok && (generalInput.value = ""),
      );
  };

  approveBtn.onclick = async () => {
    if (await post({ kind: "done", id: rid(), version: VNUM, text: "Looks good" })) {
      approveBtn.textContent = "✓ Sent";
      approveBtn.disabled = true;
    }
  };

  // ---------- banner ----------
  function renderStatus(state) {
    const { status, listening } = state;
    let cls = "",
      text = "";
    if (status.state === "working") {
      cls = "working";
      text = `Claude is working${status.detail ? " — " + status.detail : ""}`;
    } else if (status.state === "waiting" && listening) {
      cls = "listening";
      text = "Claude is listening — select text to comment";
    } else if (status.state === "waiting") {
      cls = "away";
      text = "Claude isn't watching — nudge it in the terminal";
    } else {
      text = "Review closed";
    }
    dot.className = "ih-dot " + cls;
    statusText.textContent = "";
    statusText.append(document.createTextNode(text));
    if (status.ts && status.state === "working")
      statusText.append(
        " ",
        Object.assign(el("span", "ih-age"), { textContent: `(${ago(status.ts)})` }),
      );
  }

  function renderVersions(state) {
    const notes = {};
    for (const e of events) if (e.kind === "note") notes[e.version] = e.text;
    const key = JSON.stringify([state.versions, notes]);
    if (key !== lastVersionsKey) {
      lastVersionsKey = key;
      versionSelect.textContent = "";
      for (const name of state.versions) {
        const n = parseInt(name.match(/v(\d+)/)[1], 10);
        const opt = document.createElement("option");
        opt.value = name;
        const isLatest = name === state.versions.at(-1);
        opt.textContent = `v${n}${isLatest ? " (latest)" : ""}${notes[n] ? " · " + notes[n] : ""}`;
        versionSelect.append(opt);
      }
      versionSelect.value = `v${String(VNUM).padStart(3, "0")}.html`;
    }
    const latest = state.versions.at(-1);
    const behind =
      latest && VNUM !== null && latest !== `v${String(VNUM).padStart(3, "0")}.html`;
    latestChip.style.display = behind ? "" : "none";
    if (behind)
      latestChip.textContent = `New version available → open ${latest.replace(".html", "")}`;
  }
  versionSelect.onchange = () => (location.href = `/versions/${versionSelect.value}`);
  latestChip.onclick = () => (location.href = "/");

  // ---------- polling ----------
  async function poll() {
    let state;
    try {
      state = await (await fetch("/api/state")).json();
    } catch {
      dot.className = "ih-dot offline";
      statusText.textContent = "Server offline — comments won't send";
      return;
    }
    events = state.events;
    renderStatus(state);
    renderVersions(state);
    const key = JSON.stringify(events);
    if (key !== lastEventsKey) {
      lastEventsKey = key;
      renderThreads();
      applyAnchors();
      const claudeMsgs = events.filter(
        (e) => e.author === "claude" && e.kind === "reply",
      ).length;
      if (claudeMsgCount >= 0 && claudeMsgs > claudeMsgCount && !panelOpen)
        showToast("Claude replied — open Comments");
      claudeMsgCount = claudeMsgs;
    }
  }
  poll();
  setInterval(poll, POLL_MS);
})();
