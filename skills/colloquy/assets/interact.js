/* Comment/status layer for colloquy pages, loaded via <script src="/interact.js" defer>.
 * Talks to interact.py's server: polls GET /api/state, posts events to POST /api/event.
 * Everything it injects is namespaced .ih-* and marked .ih-ui so anchoring skips it.
 *
 * Central tenet: never lose user text. Every draft the user has typed but not sent — the
 * general box, each per-thread reply, and the selection composer (text + its anchor) —
 * persists to localStorage on input, so navigation, reload, version switches, and server
 * death all recover it. Only a successful send clears a draft. localStorage is partitioned
 * by origin and each page directory gets its own port, so the keys are implicitly per-page.
 *
 * Versions: an unpinned page follows the newest version, navigating to each revision as
 * Claude ships it. Picking an older version pins the view (?pin in the URL); a pinned
 * page stays put and offers the newest version as a chip instead.
 *
 * Composing: every textarea behaves identically — grows with its content, saves its
 * draft on each keystroke, sends on ⌘/Ctrl+Enter — because they are all wired through
 * wireInput. A poll that re-renders the thread list restores scroll offset and the
 * caret, so an arriving reply never interrupts one being typed. */
(() => {
  "use strict";

  const VERSION_MATCH = location.pathname.match(/\/versions\/v(\d+)\.html$/);
  const VNUM = VERSION_MATCH ? parseInt(VERSION_MATCH[1], 10) : null;
  const PINNED = new URLSearchParams(location.search).has("pin");
  const POLL_MS = 2000;

  // ---------- styles ----------
  const style = document.createElement("style");
  style.textContent = `
    html { scroll-padding-top: 54px; }
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
    .ih-status-text { color: #374151; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
    .ih-status-text .ih-age { color: #9ca3af; }
    .ih-spacer { flex: 1; min-width: 0; }
    .ih-banner select { font: inherit; padding: 3px 6px; border: 1px solid #d1d5db; border-radius: 6px; background: #fff; max-width: 260px; min-width: 0; }
    .ih-btn { font: inherit; padding: 4px 10px; border: 1px solid #d1d5db; border-radius: 6px; background: #fff; cursor: pointer; white-space: nowrap; }
    .ih-btn:hover { background: #f3f4f6; }
    .ih-btn.primary { background: #2563eb; border-color: #2563eb; color: #fff; }
    .ih-btn.primary:hover { background: #1d4ed8; }
    .ih-btn:disabled { opacity: .55; cursor: default; }
    .ih-latest-chip { background: #fef3c7; border: 1px solid #f59e0b; border-radius: 6px; padding: 3px 8px; }
    .ih-panel { position: fixed; top: 42px; right: 0; bottom: 0; width: min(360px, 100vw); z-index: 8900;
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
    .ih-quote.detached { border-left-style: dashed; border-left-color: #d1d5db; color: #9ca3af; cursor: default; }
    .ih-msg { margin: 8px 0; }
    .ih-msg-head { display: flex; gap: 6px; align-items: baseline; }
    .ih-msg-head b { font-size: 12.5px; }
    .ih-msg.claude .ih-msg-head b { color: #2563eb; }
    .ih-msg time { color: #9ca3af; font-size: 11.5px; }
    .ih-msg p { margin: 2px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; }
    /* Send buttons sit at the bottom so a growing textarea doesn't stretch them. */
    .ih-compose, .ih-general { display: flex; gap: 6px; margin-top: 8px; align-items: flex-end; }
    .ih-ui textarea { font: inherit; padding: 5px 8px; border: 1px solid #d1d5db; border-radius: 6px; resize: none; overflow-y: hidden; }
    .ih-ui textarea:focus { outline: none; border-color: #93c5fd; box-shadow: 0 0 0 2px #bfdbfe80; }
    .ih-compose textarea, .ih-general textarea { flex: 1; min-width: 0; }
    .ih-thread-actions { display: flex; justify-content: space-between; margin-top: 8px; }
    .ih-resolve { border: none; background: none; color: #6b7280; cursor: pointer; font: inherit; }
    .ih-resolve:hover { color: #16a34a; }
    .ih-general { padding: 10px 14px; border-top: 1px solid #eef0f2; }
    .ih-details { margin-top: 6px; color: #6b7280; }
    .ih-system { color: #16a34a; margin: 8px 0; }
    .ih-fab { position: fixed; z-index: 9100; display: none; }
    .ih-composer { position: fixed; z-index: 9100; display: none; width: 320px; background: #fff;
      border: 1px solid #d1d5db; border-radius: 8px; box-shadow: 0 8px 24px rgba(0,0,0,.12); padding: 10px; }
    .ih-composer-quote { margin: 0 0 8px; padding: 2px 8px; border-left: 3px solid #f59e0b; color: #6b7280; font-style: italic; overflow-wrap: anywhere; max-height: 4.2em; overflow-y: auto; display: none; }
    .ih-composer textarea { width: 100%; min-height: 56px; }
    .ih-composer-row { display: flex; justify-content: flex-end; gap: 6px; margin-top: 6px; }
    .ih-mark { background: #fde68a80; border-bottom: 2px solid #f59e0b; cursor: pointer; }
    .ih-mark:hover { background: #fde68a; }
    .ih-toast { position: fixed; bottom: 18px; right: 18px; z-index: 9200; background: #1f2328; color: #fff;
      padding: 9px 14px; border-radius: 8px; opacity: 0; transition: opacity .25s; pointer-events: none; }
    .ih-toast.show { opacity: .95; }
    .ih-toast.clickable { pointer-events: auto; cursor: pointer; }
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
  versionSelect.title = "Version";
  versionSelect.setAttribute("aria-label", "Version");
  const toggleBtn = el("button", "ih-btn", "Comments");
  toggleBtn.title = "Show or hide the comment panel (Esc closes)";
  const approveBtn = el("button", "ih-btn primary", "✓ Looks good");
  approveBtn.title = "Sign off — Claude stops watching this page";
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
  const closeBtn = Object.assign(el("button", "ih-btn", "×"), {
    title: "Close (Esc)",
    onclick: () => setPanel(false),
  });
  closeBtn.setAttribute("aria-label", "Close comments");
  panelHead.append(el("span", "", "Comments"), closeBtn);
  const threadsBox = el("div", "ih-threads");
  const generalRow = el("div", "ih-general");
  const generalInput = document.createElement("textarea");
  const generalSend = el("button", "ih-btn primary", "Send");
  generalRow.append(generalInput, generalSend);
  panel.append(panelHead, threadsBox, generalRow);

  const fab = el("button", "ih-ui ih-btn primary ih-fab", "💬 Comment");
  const composer = el("div", "ih-ui ih-composer");
  const composerQuote = el("blockquote", "ih-composer-quote");
  const composerInput = document.createElement("textarea");
  const composerRow = el("div", "ih-composer-row");
  const composerCancel = el("button", "ih-btn", "Cancel");
  const composerSend = el("button", "ih-btn primary", "Comment");
  composerRow.append(composerCancel, composerSend);
  composer.append(composerQuote, composerInput, composerRow);
  const toast = el("div", "ih-ui ih-toast");

  document.body.append(banner, panel, fab, composer, toast);
  const basePaddingTop = parseFloat(getComputedStyle(document.body).paddingTop) || 0;
  document.body.style.paddingTop = basePaddingTop + 42 + "px";

  // ---------- state ----------
  let events = [];
  let lastEventsKey = "";
  let lastVersionsKey = "";
  let latestName = "";
  let claudeMsgCount = -1;
  let panelOpen = false;
  let pendingAnchor = null;
  const rid = () => crypto.randomUUID().replaceAll("-", "").slice(0, 8);

  // ---------- draft persistence ----------
  // Text the user typed but hasn't sent must survive navigation, reload, version switches,
  // and server death; only a successful send clears it. Storage failures never break typing.
  const DRAFT = "ih-draft:";
  const saveDraft = (ctx, val) => {
    try {
      if (val) localStorage.setItem(DRAFT + ctx, val);
      else localStorage.removeItem(DRAFT + ctx);
    } catch {}
  };
  const loadDraft = (ctx) => {
    try {
      return localStorage.getItem(DRAFT + ctx) || "";
    } catch {
      return "";
    }
  };
  const pruneReplyDrafts = (liveIds) => {
    const rp = DRAFT + "reply:";
    try {
      for (let i = localStorage.length - 1; i >= 0; i--) {
        const k = localStorage.key(i);
        if (k && k.startsWith(rp) && !liveIds.has(k.slice(rp.length)))
          localStorage.removeItem(k);
      }
    } catch {}
  };

  // Panel open/closed is remembered too: a version switch reloads the document, and
  // reopening the panel by hand after every revision gets old fast.
  const PANEL_KEY = "ih-panel-open";
  function syncLayout() {
    // Below the breakpoint the panel covers the page rather than squeezing it, so
    // there's nothing to reserve room for.
    document.body.style.paddingRight =
      panelOpen && innerWidth > 720 ? panel.offsetWidth + "px" : "";
    // The toast lives in the same corner as the panel's Send button; step it aside so a
    // "couldn't send" message never covers the button it's talking about.
    toast.style.right = (panelOpen ? panel.offsetWidth + 18 : 18) + "px";
  }
  function setPanel(open) {
    panelOpen = open;
    panel.classList.toggle("open", open);
    syncLayout();
    try {
      localStorage.setItem(PANEL_KEY, open ? "1" : "0");
    } catch {}
    if (open) {
      renderPanel();
      syncGeneral(); // textareas only measure once the panel is visible
    }
  }
  toggleBtn.onclick = () => setPanel(!panelOpen);
  addEventListener("resize", syncLayout);

  let toastTimer = 0;
  function showToast(msg, onClick) {
    toast.textContent = msg;
    toast.onclick = onClick || null;
    toast.classList.add("show");
    toast.classList.toggle("clickable", Boolean(onClick));
    clearTimeout(toastTimer);
    // Drop `clickable` on the way out too: a faded-but-clickable toast is an invisible
    // target sitting over the corner of the page.
    toastTimer = setTimeout(() => {
      toast.classList.remove("show", "clickable");
      toast.onclick = null;
    }, 4000);
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

  // ---------- text inputs ----------
  // One helper wires every composer: the general box, each per-thread reply, and the
  // selection composer. They grow with their content, persist a draft on each keystroke,
  // send on ⌘/Ctrl+Enter, and can't be double-sent by an impatient second click.
  // Returns a sync() the caller runs after setting .value programmatically, and after
  // inserting the element (a detached textarea measures as zero-height).
  const GROW_MAX = 200;
  const SEND_KEYS = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent)
    ? "⌘⏎"
    : "Ctrl+⏎";
  function grow(ta) {
    if (!ta.offsetParent) return; // hidden — measuring now would collapse it to zero
    ta.style.height = "auto";
    const border = ta.offsetHeight - ta.clientHeight; // border-box: scrollHeight omits it
    const wanted = ta.scrollHeight + border;
    ta.style.height = Math.min(wanted, GROW_MAX) + "px";
    ta.style.overflowY = wanted > GROW_MAX ? "auto" : "hidden";
  }
  function wireInput(ta, { hint, save, send, sendBtn }) {
    // The shortcut goes in the placeholder, where it's visible exactly while the box is
    // empty and can't be found any other way; the button's tooltip spells it out.
    ta.placeholder = `${hint} · ${SEND_KEYS}`;
    ta.rows = 1; // grow() measures against this, and the default of 2 never shrinks back
    sendBtn.title = `Send (${SEND_KEYS})`;
    let sending = false;
    const sync = () => {
      grow(ta);
      sendBtn.disabled = sending || !ta.value.trim();
    };
    const submit = async () => {
      if (sending || !ta.value.trim()) return;
      sending = true;
      sync();
      try {
        await send(ta.value.trim());
      } finally {
        sending = false;
        sync();
      }
    };
    ta.addEventListener("input", () => {
      save(ta.value);
      sync();
    });
    ta.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" && (ev.metaKey || ev.ctrlKey)) {
        ev.preventDefault();
        submit();
      }
    });
    sendBtn.addEventListener("click", submit);
    return sync;
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

  function threadNode(t, syncs) {
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
      const row = el("div", "ih-compose");
      const input = document.createElement("textarea");
      const draftCtx = "reply:" + t.root.id;
      input.value = loadDraft(draftCtx);
      const send = el("button", "ih-btn", "Reply");
      row.append(input, send);
      syncs.push(
        wireInput(input, {
          hint: "Reply",
          sendBtn: send,
          save: (v) => saveDraft(draftCtx, v),
          send: async (text) => {
            if (await post({ kind: "reply", id: rid(), parent: t.root.id, version: VNUM, text })) {
              // post() polls, which has already rebuilt this thread — `input` is detached
              // and its replacement was seeded from the draft. Clear it and render again.
              saveDraft(draftCtx, "");
              renderPanel();
            }
          },
        }),
      );
      const actions = el("div", "ih-thread-actions");
      const resolve = el("button", "ih-resolve", "✓ Resolve");
      resolve.onclick = () => post({ kind: "resolve", id: rid(), parent: t.root.id });
      actions.append(el("span"), resolve);
      div.append(row, actions);
    }
    return div;
  }

  function renderThreads() {
    // Every node is rebuilt, so remember where the reader was: the panel's scroll
    // offset, and the reply they were mid-way through typing with its caret. Otherwise
    // a reply arriving mid-sentence yanks the panel to the top and drops the cursor.
    const scrollTop = threadsBox.scrollTop;
    const active = document.activeElement;
    const focusedId =
      active?.tagName === "TEXTAREA" ? active.closest(".ih-thread")?.dataset.id : null;
    const caret = focusedId ? [active.selectionStart, active.selectionEnd] : null;

    threadsBox.textContent = "";
    const syncs = [];
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
    open.forEach((t) => threadsBox.append(threadNode(t, syncs)));
    for (const e of events)
      if (e.kind === "done")
        threadsBox.append(el("div", "ih-system", `✓ Approved ${ago(e.ts)}`));
    if (resolved.length) {
      const details = el("details", "ih-details");
      details.append(el("summary", "", `Resolved (${resolved.length})`));
      resolved.forEach((t) => details.append(threadNode(t, syncs)));
      threadsBox.append(details);
    }
    syncs.forEach((sync) => sync()); // sizes only measure once the nodes are in the document
    toggleBtn.textContent = `Comments (${open.length})`;

    if (focusedId) {
      const ta = threadsBox.querySelector(`.ih-thread[data-id="${focusedId}"] textarea`);
      if (ta) {
        ta.focus();
        ta.setSelectionRange(caret[0], caret[1]);
      }
    }
    threadsBox.scrollTop = scrollTop; // after focus(), which scrolls the panel itself
  }

  // The panel and the page highlights are two views of the same threads, and
  // applyAnchors styles nodes renderThreads just built — always render them as a pair.
  function renderPanel() {
    renderThreads();
    applyAnchors();
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

  // ---------- view continuity ----------
  // Following a new version is a navigation, so without help the reader lands at the top
  // of a fresh document mid-review. The passage they were reading rides across in
  // sessionStorage — per-tab, unlike the drafts, because a reading position belongs to a
  // tab and shouldn't outlive it. It travels as a landmark rather than a pixel offset,
  // since content moves between versions: re-find the passage by its text within its
  // section, then the section alone, and only fall back to the raw offset when neither
  // survived the revision. The panel's own open state is restored separately (PANEL_KEY);
  // because that runs first, the column is already reflowed by the time we scroll.
  const VIEW_KEY = "ih-view";
  const TEXT_BLOCK = "p,li,h1,h2,h3,h4,h5,h6,td,th,pre,blockquote,dd,dt,figcaption,summary";

  // The first text block still on screen below the banner: what the reader is reading. A
  // block's landmark is the top of its first line (a range), not its border box; restore
  // measures the matched text the same way, so the line box's leading cancels out.
  function captureView() {
    const view = { v: VNUM, y: scrollY };
    for (const block of document.querySelectorAll(TEXT_BLOCK)) {
      if (block.closest(".ih-ui")) continue;
      const range = document.createRange();
      range.selectNodeContents(block);
      const rect = range.getBoundingClientRect();
      if (!rect.height || rect.bottom <= 42) continue; // 42 = banner height
      if (!view.section) {
        const section = block.closest("[id]:not(.ih-ui)");
        if (section) {
          view.section = section.id;
          view.sectionTop = section.getBoundingClientRect().top;
        }
      }
      const text = block.textContent.replace(/\s+/g, " ").trim();
      // A short line ("Risks") would match anywhere; keep scanning for a quotable block.
      if (text.length >= 24) {
        view.quote = text.slice(0, 160);
        view.quoteTop = rect.top;
        break;
      }
    }
    return view;
  }

  // "instant" because a page is free to set scroll-behavior: smooth, and a restore that
  // animates from the top of the document is worse than the jump it replaces.
  const jumpBy = (dy) => scrollBy({ top: dy, behavior: "instant" });
  function restoreView(view) {
    if (view.quote) {
      const root =
        (view.section && document.getElementById(view.section)) || document.body;
      const segments = findQuote(root, view.quote);
      if (segments?.length) {
        const range = document.createRange();
        range.setStart(segments[0].node, segments[0].start);
        range.setEnd(segments.at(-1).node, segments.at(-1).end);
        jumpBy(range.getBoundingClientRect().top - view.quoteTop);
        return;
      }
    }
    const section = view.section && document.getElementById(view.section);
    if (section) jumpBy(section.getBoundingClientRect().top - view.sectionTop);
    else scrollTo({ top: view.y, behavior: "instant" });
  }

  // Highlights each open thread's quote in the page, then tells the panel which quotes
  // it couldn't place — a passage rewritten in a later version has no home to jump to,
  // and a dead-looking link is worse than one that says so.
  function applyAnchors() {
    clearMarks();
    const anchored = new Set();
    for (const t of buildThreads()) {
      if (t.resolved || !t.root.anchor?.quote) continue;
      const rootEl =
        (t.root.anchor.section && document.getElementById(t.root.anchor.section)) ||
        document.body;
      const segments = findQuote(rootEl, t.root.anchor.quote);
      if (!segments) continue;
      anchored.add(t.root.id);
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
    for (const div of threadsBox.querySelectorAll(":scope > .ih-thread")) {
      const quote = div.querySelector(".ih-quote");
      if (!quote) continue;
      const found = anchored.has(div.dataset.id);
      quote.classList.toggle("detached", !found);
      quote.title = found
        ? "Jump to this passage"
        : "This passage isn't in the version you're viewing";
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
  // Floating UI has to stay clear of both the banner and the comment panel, which
  // covers the right of the viewport whenever it's open.
  const rightEdge = () => innerWidth - (panelOpen ? panel.offsetWidth : 0) - 8;
  function place(node, left, top) {
    node.style.left = Math.max(8, Math.min(left, rightEdge() - node.offsetWidth)) + "px";
    node.style.top = Math.max(48, Math.min(top, innerHeight - node.offsetHeight - 8)) + "px";
  }
  const inUi = (node) =>
    Boolean((node?.nodeType === 1 ? node : node?.parentElement)?.closest(".ih-ui"));
  function updateFab() {
    const sel = getSelection();
    if (!sel || sel.isCollapsed || sel.toString().trim().length < 3 || inUi(sel.anchorNode)) {
      fab.style.display = "none";
      return;
    }
    const rect = sel.getRangeAt(0).getBoundingClientRect();
    fab.style.display = "block";
    place(fab, rect.right + 6, rect.top - 6);
  }
  document.addEventListener("mouseup", (ev) => {
    if (ev.target.closest?.(".ih-ui")) return;
    setTimeout(updateFab);
  });
  // Selections made from the keyboard (shift-arrows, ⌘A) deserve the same button.
  document.addEventListener("keyup", (ev) => {
    if (ev.target.closest?.(".ih-ui, input, textarea, [contenteditable]")) return;
    setTimeout(updateFab);
  });
  document.addEventListener("mousedown", (ev) => {
    if (!ev.target.closest?.(".ih-fab, .ih-composer")) {
      fab.style.display = "none";
      // Keep a composer that holds unsent text open so a stray click can't drop it;
      // Cancel discards explicitly, and the draft is persisted regardless.
      if (!composerInput.value) composer.style.display = "none";
    }
  });

  const syncComposer = wireInput(composerInput, {
    hint: "Your comment",
    sendBtn: composerSend,
    save: (v) =>
      saveDraft("composer", v ? JSON.stringify({ text: v, anchor: pendingAnchor }) : ""),
    send: async (text) => {
      if (await post({ kind: "comment", id: rid(), version: VNUM, anchor: pendingAnchor, text })) {
        closeComposer();
        setPanel(true);
      }
    },
  });

  function openComposer(anchor, text, left, top) {
    pendingAnchor = anchor || null;
    composerInput.value = text || "";
    // "" would fall back to the stylesheet's display:none, hiding what's being quoted.
    composerQuote.style.display = anchor?.quote ? "block" : "none";
    if (anchor?.quote) composerQuote.textContent = `“${anchor.quote}”`;
    composer.style.display = "block";
    syncComposer(); // before place(): the height decides where it fits
    place(composer, left, top);
    composerInput.focus();
  }
  function closeComposer() {
    composer.style.display = "none";
    composerInput.value = "";
    pendingAnchor = null;
    saveDraft("composer", "");
  }

  fab.onclick = () => {
    const sel = getSelection();
    if (!sel || sel.isCollapsed) return;
    const range = sel.getRangeAt(0);
    let node = range.commonAncestorContainer;
    if (node.nodeType !== Node.ELEMENT_NODE) node = node.parentElement;
    const section = node.closest("[id]:not(.ih-ui)")?.id || null;
    openComposer(
      { section, quote: sel.toString().trim().slice(0, 400) },
      "",
      parseFloat(fab.style.left),
      parseFloat(fab.style.top),
    );
    fab.style.display = "none";
  };
  // Cancel discards. Escape and outside clicks only hide, keeping the draft either way.
  composerCancel.onclick = closeComposer;

  const syncGeneral = wireInput(generalInput, {
    hint: "Comment on the page",
    sendBtn: generalSend,
    save: (v) => saveDraft("general", v),
    send: async (text) => {
      if (await post({ kind: "comment", id: rid(), version: VNUM, text })) {
        generalInput.value = "";
        saveDraft("general", "");
      }
    },
  });

  approveBtn.onclick = () =>
    post({ kind: "done", id: rid(), version: VNUM, text: "Looks good" });

  // Escape backs out of whatever is in front: first the composer (its draft is kept),
  // then the panel — but never while a textarea has focus, where it would look like
  // the keystroke ate the text.
  document.addEventListener("keydown", (ev) => {
    if (ev.key !== "Escape") return;
    if (composer.style.display === "block") {
      composer.style.display = "none";
      fab.style.display = "none";
    } else if (panelOpen && document.activeElement?.tagName !== "TEXTAREA") {
      setPanel(false);
    }
  });

  // ---------- banner ----------
  const STALE_MS = 10 * 60 * 1000;
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
      // No watcher, but comments still land in the append-only log and are delivered
      // the next time Claude waits — so say that. Only a status this stale suggests
      // the session itself is gone, which is the one case worth a nudge.
      cls = "away";
      const stale = status.ts && Date.now() - new Date(status.ts).getTime() > STALE_MS;
      text = stale
        ? "Claude has been quiet a while — comments are saved; nudge it in the terminal"
        : "Claude isn't watching right now — comments are saved and delivered next turn";
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
    latestName = state.versions.at(-1) || "";
    const behind =
      latestName && VNUM !== null && latestName !== `v${String(VNUM).padStart(3, "0")}.html`;
    // Follow the newest version unless pinned or the user is mid-composition:
    // drafts survive navigation, but an open composer or a live selection
    // doesn't. While deferred, the chip shows instead.
    if (behind && !PINNED && !midComposition()) {
      location.replace(`/versions/${latestName}`);
      return;
    }
    latestChip.style.display = behind ? "" : "none";
    if (behind)
      latestChip.textContent = `New version available → open ${latestName.replace(".html", "")}`;
  }
  const midComposition = () =>
    composer.style.display === "block" ||
    fab.style.display === "block" ||
    (document.activeElement?.tagName === "TEXTAREA" && document.activeElement.value !== "");
  versionSelect.onchange = () => {
    const name = versionSelect.value;
    location.href = name === latestName ? `/versions/${name}` : `/versions/${name}?pin`;
  };
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
      // prune only here, where events is the server's truth — never from renderThreads,
      // which also runs with an empty events array (pre-first-poll, server offline)
      pruneReplyDrafts(
        new Set(
          buildThreads()
            .filter((t) => !t.resolved)
            .map((t) => t.root.id),
        ),
      );
      renderPanel();
      // Sign-off is a fact in the log, not a click this tab happens to remember, so a
      // reload (or the other tab) shows it too.
      const approved = events.some((e) => e.kind === "done");
      approveBtn.disabled = approved;
      approveBtn.textContent = approved ? "✓ Approved" : "✓ Looks good";
      const claudeMsgs = events.filter(
        (e) => e.author === "claude" && e.kind === "reply",
      ).length;
      if (claudeMsgCount >= 0 && claudeMsgs > claudeMsgCount && !panelOpen)
        showToast("Claude replied — open Comments", () => setPanel(true));
      claudeMsgCount = claudeMsgs;
    }
  }
  // ---------- restore ----------
  // The general box and reply textareas repopulate as they render; a saved composer draft
  // resurfaces visibly near the top so it isn't stranded in storage after a reload.
  generalInput.value = loadDraft("general");
  try {
    if (localStorage.getItem(PANEL_KEY) === "1") setPanel(true);
  } catch {}
  // Carry the reading position across a version switch (the panel is restored just above,
  // so the column is already reflowed). Only when the loaded version differs from the
  // saved one — a plain reload keeps the browser's own, more faithful, scroll restoration.
  const savedView = (() => {
    try {
      return JSON.parse(sessionStorage.getItem(VIEW_KEY) || "null");
    } catch {
      return null;
    }
  })();
  if (savedView && savedView.v !== VNUM) {
    restoreView(savedView);
    if (savedView.v < VNUM) showToast(`Updated to v${VNUM}`);
  }
  addEventListener("pagehide", () => {
    try {
      sessionStorage.setItem(VIEW_KEY, JSON.stringify(captureView()));
    } catch {}
  });
  const savedComposer = loadDraft("composer");
  if (savedComposer)
    try {
      const { text, anchor } = JSON.parse(savedComposer);
      if (text) openComposer(anchor, text, (innerWidth - 320) / 2, 64);
    } catch {}

  poll();
  setInterval(poll, POLL_MS);
})();
