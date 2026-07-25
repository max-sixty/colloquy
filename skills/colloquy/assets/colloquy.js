/* Colloquy runtime, loaded via <script type="module" src="/colloquy.js">: one module
 * owning both the widget layer and the comment layer.
 *
 * Widget layer: reads /registry.json (vendored per page) and dynamically imports one
 * module per tag marked x-upgrade — element-widgets need no JS at all; the theme's CSS
 * renders them. Upgrades flush before the first anchor pass, so comment quotes always
 * search the enhanced DOM. Widget modules import the helper surface exported here
 * (`once`, `failSoft`, `settle`, `refUrl`, `sendAction`, `toast`); it stays minimal
 * until a real widget needs more.
 *
 * Actions: an interactive widget (cq-board) reports the user editing the document
 * through it as an `action` event — sendAction posts it, `wait` delivers it, and the
 * next version's markup carries the change. Until then the live view = the version
 * plus its actions: each poll replays unapplied actions recorded against the version
 * on screen, plus undelivered ones from older versions (a version Claude wrote
 * before being handed the edit must not visibly revert it); a widget inside a
 * thread reply replays its actions on every version, because its markup is frozen
 * in the log and no version can carry its state. Widgets opt in via an
 * applyAction(action, detail) method, so a reload keeps the reviewer's drag and a
 * second tab follows along live.
 *
 * Comment layer: talks to interact.py's server — polls GET /api/state, posts events to
 * POST /api/event. Everything it injects is namespaced .cq-* and marked .cq-ui so
 * anchoring skips it, and it styles itself from the theme's tokens so it themes with
 * the page.
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
 * caret, so an arriving reply never interrupts one being typed.
 *
 * Claude's replies may carry widget markup (`reply` validates it against the vendored
 * registry at post time), rendered live in the thread; user comments stay plain text. */

// ---------- widget layer ----------

// One-shot guard for connectedCallback: re-connection (a parent wrapping or moving an
// already-upgraded child) must be harmless, so upgrade order can't matter.
export function once(el) {
  if (el.dataset.cqDone) return false;
  el.dataset.cqDone = "1";
  return true;
}

// A failed upgrade becomes a visible error box rather than a blank page.
export function failSoft(el, err, source) {
  const box = document.createElement("div");
  box.className = "cq-error";
  box.textContent = `<${el.tagName.toLowerCase()}> failed: ${err?.message || err}`;
  if (source) {
    const pre = document.createElement("pre");
    pre.textContent = source;
    box.append(pre);
  }
  el.replaceChildren(box);
}

// An upgrade whose work is async (cq-diagram's mermaid render) registers its
// promise here, so the runtime can hold the view restore and first anchor pass
// until the page's geometry has settled. Rejections are the widget's own
// fail-soft path; settling ignores them.
const settling = [];
export function settle(promise) {
  settling.push(promise);
}

// Reference base, resolved from the page's own declaration:
//   <meta name="cq-base" content="https://host/repo/blob/main/{path}#L{line}">
// Returns null when the page declares none — the reference then renders as plain code.
export function refUrl(path, line) {
  const template = document.querySelector('meta[name="cq-base"]')?.content;
  if (!template) return null;
  let url = template.replaceAll("{path}", path).replaceAll("{line}", line ?? "");
  if (!line) url = url.replace(/#[^#]*$/, ""); // the fragment is line-shaped; lineless refs drop it
  return url;
}

// A widget's report of the user editing the document through it (a card dragged
// between columns). The caller has already applied the edit to its own DOM; the
// poll's replay re-applies it once (see applyActions), which is why applyAction
// implementations must state an absolute placement, never a relative mutation.
export function sendAction(el, action, detail) {
  return post({ kind: "action", version: VNUM, widget: el.id, action, detail });
}

// Transient confirmation ("Moved to Doing — sent to Claude"), styled and placed by
// the comment layer.
export function toast(msg) {
  showToast(msg);
}

async function upgradeWidgets() {
  let registry;
  try {
    registry = await (await fetch("/registry.json")).json();
  } catch {
    return; // no vendored registry — nothing upgrades
  }
  await Promise.all(
    Object.entries(registry)
      .filter(([tag, entry]) => tag.startsWith("cq-") && entry["x-upgrade"])
      .map(([tag]) =>
        import(`/widgets/${tag}.js`).catch((err) =>
          console.error(`colloquy: widget ${tag} failed to load`, err),
        ),
      ),
  );
  // Importing defined the elements and ran their connectedCallbacks; async ones
  // registered their work via settle(). Wait it out so geometry is final.
  await Promise.allSettled(settling);
}

// ---------- comment layer ----------

const VERSION_MATCH = location.pathname.match(/\/versions\/v(\d+)\.html$/);
const VNUM = VERSION_MATCH ? parseInt(VERSION_MATCH[1], 10) : null;
const PINNED = new URLSearchParams(location.search).has("pin");
const POLL_MS = 2000;

// ---------- styles ----------
const style = document.createElement("style");
style.textContent = `
  html { scroll-padding-top: 54px; }
  .cq-ui { font-family: system-ui, -apple-system, sans-serif; font-size: var(--t-5); line-height: 1.45; color: var(--ink); box-sizing: border-box; }
  .cq-ui *, .cq-ui *::before, .cq-ui *::after { box-sizing: inherit; }
  .cq-banner { position: fixed; top: 0; left: 0; right: 0; z-index: 9000; height: 42px;
    display: flex; align-items: center; gap: 10px; padding: 0 14px;
    background: var(--veil); backdrop-filter: blur(6px); border-bottom: 1px solid var(--rule); }
  .cq-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--muted-2); flex: none; }
  .cq-dot.working { background: var(--accent); animation: cq-pulse 1.4s ease-in-out infinite; }
  .cq-dot.listening { background: var(--ok); }
  .cq-dot.away { background: var(--warn); }
  .cq-dot.offline { background: var(--danger); }
  @keyframes cq-pulse { 50% { opacity: .35; } }
  .cq-status-text { color: var(--ink-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
  .cq-status-text .cq-age { color: var(--muted-2); }
  .cq-spacer { flex: 1; min-width: 0; }
  .cq-banner select { font: inherit; padding: 3px 6px; border: 1px solid var(--border-2); border-radius: 6px; background: var(--card); color: inherit; max-width: 260px; min-width: 0; }
  .cq-btn { font: inherit; padding: 4px 10px; border: 1px solid var(--border-2); border-radius: 6px; background: var(--card); cursor: pointer; white-space: nowrap; color: inherit; }
  .cq-btn:hover { background: var(--chip); }
  .cq-btn.primary { background: var(--accent); border-color: var(--accent); color: var(--paper); }
  .cq-btn.primary:hover { filter: brightness(.92); }
  .cq-btn:disabled { opacity: .55; cursor: default; }
  .cq-latest-chip { background: var(--warn-tint); border: 1px solid var(--warn); color: var(--warn-ink); border-radius: 6px; padding: 3px 8px; }
  .cq-panel { position: fixed; top: 42px; right: 0; bottom: 0; width: min(360px, 100vw); z-index: 8900;
    background: var(--card); border-left: 1px solid var(--rule); display: none; flex-direction: column; }
  .cq-panel.open { display: flex; }
  .cq-panel-head { display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; border-bottom: 1px solid var(--rule); font-weight: 600; }
  .cq-threads { flex: 1; overflow-y: auto; padding: 10px 14px; }
  .cq-empty { color: var(--muted); padding: 18px 4px; }
  .cq-thread { border: 1px solid var(--rule); border-radius: var(--r); padding: 10px; margin-bottom: 12px; }
  .cq-thread.flash { animation: cq-flash 1.2s ease-out; }
  @keyframes cq-flash { 0% { background: var(--hi-tint); } 100% { background: var(--card); } }
  .cq-quote { margin: 0 0 8px; padding: 2px 8px; border-left: 3px solid var(--quote-bar); color: var(--muted); font-style: italic; cursor: pointer; overflow-wrap: anywhere; }
  .cq-quote:hover { color: var(--ink-2); }
  .cq-quote.detached { border-left-style: dashed; border-left-color: var(--border-2); color: var(--muted-2); cursor: default; }
  .cq-msg { margin: 8px 0; }
  .cq-msg-head { display: flex; gap: 6px; align-items: baseline; }
  .cq-msg-head b { font-size: 12.5px; }
  .cq-msg.claude .cq-msg-head b { color: var(--accent); }
  .cq-msg time { color: var(--muted-2); font-size: 11.5px; }
  .cq-msg p { margin: 2px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; }
  /* Send buttons sit at the bottom so a growing textarea doesn't stretch them. */
  .cq-compose, .cq-general { display: flex; gap: 6px; margin-top: 8px; align-items: flex-end; }
  .cq-ui textarea { font: inherit; padding: 5px 8px; border: 1px solid var(--border-2); border-radius: 6px; background: var(--card); color: inherit; resize: none; overflow-y: hidden; }
  .cq-ui textarea:focus { outline: none; border-color: color-mix(in srgb, var(--accent) 45%, var(--card)); box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 25%, transparent); }
  .cq-compose textarea, .cq-general textarea { flex: 1; min-width: 0; }
  .cq-thread-actions { display: flex; justify-content: space-between; margin-top: 8px; }
  .cq-resolve { border: none; background: none; color: var(--muted); cursor: pointer; font: inherit; }
  .cq-resolve:hover { color: var(--ok); }
  .cq-general { padding: 10px 14px; border-top: 1px solid var(--rule); }
  .cq-details { margin-top: 6px; color: var(--muted); background: none; border: none; padding: 0; }
  .cq-system { color: var(--ok); margin: 8px 0; }
  .cq-fab { position: fixed; z-index: 9100; display: none; }
  .cq-composer { position: fixed; z-index: 9100; display: none; width: 320px; background: var(--card);
    border: 1px solid var(--border-2); border-radius: var(--r); box-shadow: 0 8px 24px rgba(0,0,0,.12); padding: 10px; }
  .cq-composer-quote { margin: 0 0 8px; padding: 2px 8px; border-left: 3px solid var(--quote-bar); color: var(--muted); font-style: italic; overflow-wrap: anywhere; max-height: 4.2em; overflow-y: auto; display: none; }
  .cq-suggest-row { display: none; align-items: center; gap: 6px; margin: 0 0 6px; color: var(--muted); font-size: 12.5px; cursor: pointer; }
  .cq-suggest-row input { margin: 0; accent-color: var(--accent); }
  .cq-suggest-label { font-size: var(--t-6); letter-spacing: .05em; text-transform: uppercase; color: var(--ok-ink); margin: 4px 0 2px; }
  .cq-msg p.cq-suggest-body { background: var(--add-tint); padding: 4px 8px; border-radius: 6px; }
  .cq-composer textarea { width: 100%; min-height: 56px; }
  .cq-composer-row { display: flex; justify-content: flex-end; gap: 6px; margin-top: 6px; }
  .cq-mark { background: var(--mark); border-bottom: 2px solid var(--quote-bar); cursor: pointer; color: inherit; }
  .cq-mark:hover { background: var(--mark-strong); }
  .cq-mark-el { outline: 2px solid var(--quote-bar); outline-offset: 3px; border-radius: 2px; cursor: pointer; }
  .cq-btn.on { border-color: var(--accent); color: var(--accent); background: var(--chip); }
  .cq-ins-block { background: var(--add-tint); box-shadow: 0 0 0 4px var(--add-tint); border-radius: 2px; }
  .cq-toast { position: fixed; bottom: 18px; right: 18px; z-index: 9200; background: var(--ink); color: var(--paper);
    padding: 9px 14px; border-radius: var(--r); opacity: 0; transition: opacity .25s; pointer-events: none; }
  .cq-toast.show { opacity: .95; }
  .cq-toast.clickable { pointer-events: auto; cursor: pointer; }
  @media print { .cq-ui { display: none !important; } }
`;
document.head.appendChild(style);

// ---------- scaffold ----------
const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
};

const banner = el("div", "cq-ui cq-banner");
const dot = el("span", "cq-dot");
const statusText = el("span", "cq-status-text", "Connecting…");
const latestChip = el("button", "cq-ui cq-btn cq-latest-chip", "");
latestChip.style.display = "none";
const diffBtn = el("button", "cq-btn", "Δ");
diffBtn.style.display = "none";
const versionSelect = document.createElement("select");
versionSelect.title = "Version";
versionSelect.setAttribute("aria-label", "Version");
const toggleBtn = el("button", "cq-btn", "Comments");
toggleBtn.title = "Show or hide the comment panel (Esc closes)";
const approveBtn = el("button", "cq-btn primary", "✓ Looks good");
approveBtn.title = "Sign off — Claude stops watching this page";
banner.append(
  dot,
  statusText,
  el("span", "cq-spacer"),
  latestChip,
  diffBtn,
  versionSelect,
  toggleBtn,
  approveBtn,
);

const panel = el("aside", "cq-ui cq-panel");
const panelHead = el("div", "cq-panel-head");
const closeBtn = Object.assign(el("button", "cq-btn", "×"), {
  title: "Close (Esc)",
  onclick: () => setPanel(false),
});
closeBtn.setAttribute("aria-label", "Close comments");
panelHead.append(el("span", "", "Comments"), closeBtn);
const threadsBox = el("div", "cq-threads");
const generalRow = el("div", "cq-general");
const generalInput = document.createElement("textarea");
const generalSend = el("button", "cq-btn primary", "Send");
generalRow.append(generalInput, generalSend);
panel.append(panelHead, threadsBox, generalRow);

const fab = el("button", "cq-ui cq-btn primary cq-fab", "💬 Comment");
const composer = el("div", "cq-ui cq-composer");
const composerQuote = el("blockquote", "cq-composer-quote");
// Suggestion mode: the box holds replacement text for the quoted passage
// instead of a remark — Claude accepts it verbatim into the next version.
const suggestRow = el("label", "cq-suggest-row");
const suggestCheck = document.createElement("input");
suggestCheck.type = "checkbox";
suggestRow.append(suggestCheck, document.createTextNode("Suggest replacement text"));
const composerInput = document.createElement("textarea");
const composerRow = el("div", "cq-composer-row");
const composerCancel = el("button", "cq-btn", "Cancel");
const composerSend = el("button", "cq-btn primary", "Comment");
composerRow.append(composerCancel, composerSend);
composer.append(composerQuote, suggestRow, composerInput, composerRow);
const toastEl = el("div", "cq-ui cq-toast");

document.body.append(banner, panel, fab, composer, toastEl);
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

// ---------- draft persistence ----------
// Text the user typed but hasn't sent must survive navigation, reload, version switches,
// and server death; only a successful send clears it. Storage failures never break typing.
const DRAFT = "cq-draft:";
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
const PANEL_KEY = "cq-panel-open";
function syncLayout() {
  // Below the breakpoint the panel covers the page rather than squeezing it, so
  // there's nothing to reserve room for.
  document.body.style.paddingRight =
    panelOpen && innerWidth > 720 ? panel.offsetWidth + "px" : "";
  // The toast lives in the same corner as the panel's Send button; step it aside so a
  // "couldn't send" message never covers the button it's talking about.
  toastEl.style.right = (panelOpen ? panel.offsetWidth + 18 : 18) + "px";
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
  toastEl.textContent = msg;
  toastEl.onclick = onClick || null;
  toastEl.classList.add("show");
  toastEl.classList.toggle("clickable", Boolean(onClick));
  clearTimeout(toastTimer);
  // Drop `clickable` on the way out too: a faded-but-clickable toast is an invisible
  // target sitting over the corner of the page.
  toastTimer = setTimeout(() => {
    toastEl.classList.remove("show", "clickable");
    toastEl.onclick = null;
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

// Bodies are cached per event id and re-adopted across thread rebuilds: the log is
// append-only so a body's text never changes, and reusing the node keeps a widget
// in a reply (a rendered diagram) from re-upgrading on every poll.
const msgBodies = new Map();
function msgNode(m) {
  const div = el("div", `cq-msg ${m.author}`);
  const head = el("div", "cq-msg-head");
  head.append(
    el("b", "", m.author === "claude" ? "Claude" : "You"),
    el("time", "", ago(m.ts)),
  );
  let body = msgBodies.get(m.id);
  if (!body) {
    body = el("p", "");
    // Claude's replies may carry widget markup, validated server-side by `reply`
    // against the vendored registry; already-defined widgets upgrade on insertion.
    // User text is always plain.
    if (m.author === "claude" && /<cq-[a-z]/.test(m.text || "")) body.innerHTML = m.text;
    else body.textContent = m.text || "";
    if (m.suggestion) body.classList.add("cq-suggest-body");
    if (m.id) msgBodies.set(m.id, body);
  }
  div.append(head);
  if (m.suggestion) div.append(el("div", "cq-suggest-label", "suggested replacement"));
  div.append(body);
  return div;
}

function threadNode(t, syncs) {
  const div = el("div", "cq-thread");
  div.dataset.id = t.root.id;
  if (t.root.anchor?.quote) {
    const quote = el("blockquote", "cq-quote", `“${t.root.anchor.quote}”`);
    quote.onclick = () => {
      const mark = document.querySelector(`.cq-mark[data-cq="${t.root.id}"]`);
      if (mark) mark.scrollIntoView({ behavior: "smooth", block: "center" });
    };
    div.append(quote);
  } else if (t.root.anchor?.section) {
    // A quote-less anchor points at an element — a diagram or image commented
    // on by click rather than by selection.
    const chip = el("blockquote", "cq-quote", `§ ${t.root.anchor.section}`);
    chip.onclick = () =>
      document
        .getElementById(t.root.anchor.section)
        ?.scrollIntoView({ behavior: "smooth", block: "center" });
    div.append(chip);
  }
  t.msgs.forEach((m) => div.append(msgNode(m)));
  if (!t.resolved) {
    const row = el("div", "cq-compose");
    const input = document.createElement("textarea");
    const draftCtx = "reply:" + t.root.id;
    input.value = loadDraft(draftCtx);
    const send = el("button", "cq-btn", "Reply");
    row.append(input, send);
    syncs.push(
      wireInput(input, {
        hint: "Reply",
        sendBtn: send,
        save: (v) => saveDraft(draftCtx, v),
        send: async (text) => {
          if (await post({ kind: "reply", parent: t.root.id, version: VNUM, text })) {
            // post() polls, which has already rebuilt this thread — `input` is detached
            // and its replacement was seeded from the draft. Clear it and render again.
            saveDraft(draftCtx, "");
            renderPanel();
          }
        },
      }),
    );
    const actions = el("div", "cq-thread-actions");
    const resolve = el("button", "cq-resolve", "✓ Resolve");
    resolve.onclick = () => post({ kind: "resolve", parent: t.root.id });
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
    active?.tagName === "TEXTAREA" ? active.closest(".cq-thread")?.dataset.id : null;
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
        "cq-empty",
        "No comments yet. Select any text on the page to comment on it, or use the box below.",
      ),
    );
  open.forEach((t) => threadsBox.append(threadNode(t, syncs)));
  for (const e of events)
    if (e.kind === "done")
      threadsBox.append(el("div", "cq-system", `✓ Approved ${ago(e.ts)}`));
  if (resolved.length) {
    const details = el("details", "cq-details");
    details.append(el("summary", "", `Resolved (${resolved.length})`));
    resolved.forEach((t) => details.append(threadNode(t, syncs)));
    threadsBox.append(details);
  }
  syncs.forEach((sync) => sync()); // sizes only measure once the nodes are in the document
  toggleBtn.textContent = `Comments (${open.length})`;

  if (focusedId) {
    const ta = threadsBox.querySelector(`.cq-thread[data-id="${focusedId}"] textarea`);
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
  document.querySelectorAll(".cq-mark").forEach((mark) => {
    const parent = mark.parentNode;
    while (mark.firstChild) parent.insertBefore(mark.firstChild, mark);
    mark.remove();
  });
  markedParents.forEach((p) => p.isConnected && p.normalize());
  markedParents.clear();
  document.querySelectorAll(".cq-mark-el").forEach((elm) => {
    elm.classList.remove("cq-mark-el");
    delete elm.dataset.cqThread;
  });
}

function textNodesUnder(rootEl) {
  const walker = document.createTreeWalker(rootEl, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) =>
      n.parentElement?.closest(".cq-ui, script, style")
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
const VIEW_KEY = "cq-view";
const TEXT_BLOCK = "p,li,h1,h2,h3,h4,h5,h6,td,th,pre,blockquote,dd,dt,figcaption,summary";

// The first text block still on screen below the banner: what the reader is reading. A
// block's landmark is the top of its first line (a range), not its border box; restore
// measures the matched text the same way, so the line box's leading cancels out.
function captureView() {
  const view = { v: VNUM, y: scrollY };
  for (const block of document.querySelectorAll(TEXT_BLOCK)) {
    if (block.closest(".cq-ui")) continue;
    const range = document.createRange();
    range.selectNodeContents(block);
    const rect = range.getBoundingClientRect();
    if (!rect.height || rect.bottom <= 42) continue; // 42 = banner height
    if (!view.section) {
      const section = block.closest("[id]:not(.cq-ui)");
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
    if (t.resolved || !t.root.anchor) continue;
    if (!t.root.anchor.quote) {
      // Element anchor: outline the element itself.
      const target =
        t.root.anchor.section && document.getElementById(t.root.anchor.section);
      if (target) {
        target.classList.add("cq-mark-el");
        target.dataset.cqThread = t.root.id;
        anchored.add(t.root.id);
      }
      continue;
    }
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
      const mark = el("mark", "cq-mark");
      mark.dataset.cq = t.root.id;
      middle.parentNode.replaceChild(mark, middle);
      mark.append(middle);
      markedParents.add(mark.parentNode);
    }
  }
  for (const div of threadsBox.querySelectorAll(":scope > .cq-thread")) {
    const quote = div.querySelector(".cq-quote");
    if (!quote) continue;
    const found = anchored.has(div.dataset.id);
    quote.classList.toggle("detached", !found);
    quote.title = found
      ? "Jump to this passage"
      : "This passage isn't in the version you're viewing";
  }
}
document.addEventListener("click", (ev) => {
  const mark = ev.target.closest?.(".cq-mark, .cq-mark-el");
  if (!mark) return;
  const threadId = mark.dataset.cq || mark.dataset.cqThread;
  setPanel(true);
  const thread = threadsBox.querySelector(`.cq-thread[data-id="${threadId}"]`);
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
  Boolean((node?.nodeType === 1 ? node : node?.parentElement)?.closest(".cq-ui"));
function updateFab() {
  const sel = getSelection();
  if (!sel || sel.isCollapsed || sel.toString().trim().length < 3 || inUi(sel.anchorNode)) {
    // A visual-element click may have just raised the button (its handler runs
    // before this queued update); an element anchor keeps it up.
    if (!pendingElement) fab.style.display = "none";
    return;
  }
  pendingElement = null; // a real selection outranks an element anchor
  const rect = sel.getRangeAt(0).getBoundingClientRect();
  fab.style.display = "block";
  place(fab, rect.right + 6, rect.top - 6);
}
document.addEventListener("mouseup", (ev) => {
  if (ev.target.closest?.(".cq-ui")) return;
  setTimeout(updateFab);
});
// Selections made from the keyboard (shift-arrows, ⌘A) deserve the same button.
document.addEventListener("keyup", (ev) => {
  if (ev.target.closest?.(".cq-ui, input, textarea, [contenteditable]")) return;
  setTimeout(updateFab);
});
document.addEventListener("mousedown", (ev) => {
  if (!ev.target.closest?.(".cq-fab, .cq-composer")) {
    fab.style.display = "none";
    // Keep a composer that holds unsent text open so a stray click can't drop it;
    // Cancel discards explicitly, and the draft is persisted regardless.
    if (!composerInput.value) composer.style.display = "none";
  }
});

// Diagrams and images have no text to select, so a click raises the same 💬
// button with an element anchor — the id the visual lives under — instead of a
// quote. An element already carrying a thread opens that thread instead (the
// mark click handler above).
const VISUAL = "cq-diagram, svg, img, figure";
let pendingElement = null;
document.addEventListener("click", (ev) => {
  if (ev.target.closest?.(".cq-ui, a, .cq-mark-el")) return;
  let visual = ev.target.closest?.(VISUAL);
  const sel = getSelection();
  if (!visual || (sel && !sel.isCollapsed)) {
    pendingElement = null;
    return;
  }
  // Outermost visual: a rendered diagram's inner svg carries a generated id;
  // the anchor belongs to the widget (or figure) that holds it.
  while (visual.parentElement?.closest(VISUAL)) visual = visual.parentElement.closest(VISUAL);
  const id = visual.closest("[id]:not(.cq-ui)")?.id;
  if (!id) return;
  pendingElement = { section: id };
  fab.style.display = "block";
  place(fab, ev.clientX + 6, ev.clientY - 40);
});

const saveComposerDraft = () =>
  saveDraft(
    "composer",
    composerInput.value
      ? JSON.stringify({
          text: composerInput.value,
          anchor: pendingAnchor,
          suggest: suggestCheck.checked,
        })
      : "",
  );
const syncComposer = wireInput(composerInput, {
  hint: "Your comment",
  sendBtn: composerSend,
  save: saveComposerDraft,
  send: async (text) => {
    const event = { kind: "comment", version: VNUM, anchor: pendingAnchor, text };
    if (suggestCheck.checked) event.suggestion = true;
    if (await post(event)) {
      closeComposer();
      setPanel(true);
    }
  },
});
suggestCheck.onchange = () => {
  // Entering suggestion mode seeds the box with the passage to edit in place.
  if (suggestCheck.checked && !composerInput.value.trim() && pendingAnchor?.quote) {
    composerInput.value = pendingAnchor.quote;
    syncComposer();
  }
  composerSend.textContent = suggestCheck.checked ? "Suggest" : "Comment";
  composerInput.placeholder = suggestCheck.checked
    ? `Replacement text · ${SEND_KEYS}`
    : `Your comment · ${SEND_KEYS}`;
  saveComposerDraft();
};

function openComposer(anchor, text, left, top, suggest = false) {
  pendingAnchor = anchor || null;
  composerInput.value = text || "";
  suggestCheck.checked = suggest;
  suggestRow.style.display = anchor?.quote ? "flex" : "none";
  composerSend.textContent = suggest ? "Suggest" : "Comment";
  // "" would fall back to the stylesheet's display:none, hiding what's being quoted.
  composerQuote.style.display = anchor?.quote || anchor?.section ? "block" : "none";
  if (anchor?.quote) composerQuote.textContent = `“${anchor.quote}”`;
  else if (anchor?.section) composerQuote.textContent = `§ ${anchor.section}`;
  composer.style.display = "block";
  syncComposer(); // before place(): the height decides where it fits
  place(composer, left, top);
  composerInput.focus();
}
function closeComposer() {
  composer.style.display = "none";
  composerInput.value = "";
  suggestCheck.checked = false;
  composerSend.textContent = "Comment";
  pendingAnchor = null;
  saveDraft("composer", "");
}

fab.onclick = () => {
  const sel = getSelection();
  if (!sel || sel.isCollapsed) {
    if (!pendingElement) return;
    openComposer(pendingElement, "", parseFloat(fab.style.left), parseFloat(fab.style.top));
    pendingElement = null;
    fab.style.display = "none";
    return;
  }
  const range = sel.getRangeAt(0);
  let node = range.commonAncestorContainer;
  if (node.nodeType !== Node.ELEMENT_NODE) node = node.parentElement;
  const section = node.closest("[id]:not(.cq-ui)")?.id || null;
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
    if (await post({ kind: "comment", version: VNUM, text })) {
      generalInput.value = "";
      saveDraft("general", "");
    }
  },
});

approveBtn.onclick = () =>
  post({ kind: "done", version: VNUM, text: "Looks good" });

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

// ---------- version diff ----------
// "Changes since vN": blocks (paragraphs, list items, widget items) whose text
// isn't present in the base version get a tinted marker, so re-reviewing a
// revision is cheap. Block-level and additions-only — deleted text has no home
// to mark — and data-widget bodies (diagram, diff, tree, code) are opaque to
// it. The base is the previous published version.
const DIFF_BLOCK =
  TEXT_BLOCK + ",aside,cq-option,cq-milestone,cq-event,cq-variant,cq-metric,cq-card";
const DIFF_OPAQUE = "cq-diagram,cq-diff,cq-tree,cq-code,svg";
let diffBase = ""; // previous version's file name, set by renderVersions
let diffOn = false;
const diffMarked = [];
// A block's key is its *authored* text: subtrees marked data-cq-gen (content an
// upgrade inserted — chip rows, resolved cq-ref labels) are excluded, because
// the base document parses unupgraded and would never match them.
function keyText(node) {
  if (node.nodeType === Node.TEXT_NODE) return node.data;
  if (node.nodeType !== Node.ELEMENT_NODE || node.dataset.cqGen) return "";
  let text = "";
  for (const child of node.childNodes) text += keyText(child);
  return text;
}
const blockKey = (b) => keyText(b).replace(/\s+/g, " ").trim();
function diffBlocks(root) {
  const pairs = [];
  for (const b of root.querySelectorAll(DIFF_BLOCK)) {
    if (b.closest(".cq-ui") || b.closest(DIFF_OPAQUE)) continue;
    if (b.querySelector(DIFF_BLOCK)) continue; // leaf blocks only, or nesting double-marks
    const key = blockKey(b);
    if (key) pairs.push([b, key]);
  }
  // Opaque widgets key by identity, not body: an upgrade rewrote the live body,
  // so text can't compare — but a widget the base didn't have still marks.
  for (const w of root.querySelectorAll(DIFF_OPAQUE)) {
    // parentElement, not w itself: an svg a widget rendered stays its widget's.
    if (w.closest(".cq-ui") || w.parentElement?.closest(DIFF_OPAQUE)) continue;
    pairs.push([w, ` ${w.tagName}#${w.id}`]);
  }
  return pairs;
}
async function applyDiff(baseName) {
  const res = await fetch(`/versions/${baseName}`);
  if (!res.ok) throw new Error(`couldn't load ${baseName}`);
  const doc = new DOMParser().parseFromString(await res.text(), "text/html");
  // Multiset membership rather than an alignment: an unchanged block that
  // merely moved stays unmarked; a changed or new one has no base twin.
  const base = new Map();
  for (const [, key] of diffBlocks(doc)) base.set(key, (base.get(key) ?? 0) + 1);
  for (const [b, key] of diffBlocks(document.body)) {
    const left = base.get(key) ?? 0;
    if (left > 0) base.set(key, left - 1);
    else {
      b.classList.add("cq-ins-block");
      diffMarked.push(b);
    }
  }
  return diffMarked.length;
}
function clearDiff() {
  for (const b of diffMarked) b.classList.remove("cq-ins-block");
  diffMarked.length = 0;
  diffOn = false;
  diffBtn.classList.remove("on");
}
diffBtn.onclick = async () => {
  if (diffOn) return clearDiff();
  try {
    const n = await applyDiff(diffBase);
    diffOn = true;
    diffBtn.classList.add("on");
    const baseLabel = diffBase.replace(/\.html$/, "").replace(/^v0*/, "v");
    showToast(n ? `${n} changed passage${n === 1 ? "" : "s"} since ${baseLabel}` : `No text changes since ${baseLabel}`);
  } catch {
    showToast("Couldn't load the previous version");
  }
};

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
      : "Claude isn't watching right now — your comments and edits are saved for next turn";
  } else {
    text = "Review closed";
  }
  dot.className = "cq-dot " + cls;
  statusText.textContent = "";
  statusText.append(document.createTextNode(text));
  if (status.ts && status.state === "working")
    statusText.append(
      " ",
      Object.assign(el("span", "cq-age"), { textContent: `(${ago(status.ts)})` }),
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
  const idx = state.versions.indexOf(`v${String(VNUM).padStart(3, "0")}.html`);
  diffBase = idx > 0 ? state.versions[idx - 1] : "";
  diffBtn.style.display = diffBase ? "" : "none";
  if (diffBase) {
    const n = parseInt(diffBase.match(/v(\d+)/)[1], 10);
    diffBtn.textContent = `Δ v${n}`;
    diffBtn.title = `Highlight what changed since v${n}`;
  }
}
// A live widget gesture (.cq-dragging) counts: navigating mid-drag would unload
// the document from under the pointer and lose the move.
const midComposition = () =>
  composer.style.display === "block" ||
  fab.style.display === "block" ||
  Boolean(document.querySelector(".cq-dragging")) ||
  (document.activeElement?.tagName === "TEXTAREA" && document.activeElement.value !== "");
versionSelect.onchange = () => {
  const name = versionSelect.value;
  location.href = name === latestName ? `/versions/${name}` : `/versions/${name}?pin`;
};
latestChip.onclick = () => (location.href = "/");

// ---------- polling ----------
// Rendering version V shows V plus the actions recorded against it, replayed in
// seq order: a reload keeps the reviewer's drag, a second tab follows along
// live, and a pinned older version shows what the reviewer did while on it.
// Widgets opt in by exposing applyAction(action, detail) — an absolute
// placement, so replaying the sender's own action is a no-op. The first poll
// runs after upgrades settle, so the methods exist.
const appliedActions = new Set();
const lastActionByWidget = new Map();
let cursor = 0; // what `wait` has delivered to Claude, from /api/state
function applyActions() {
  // Never mutate the page under a live gesture — a replayed foreign action could
  // move the nodes a drag preview is holding. Retry next poll.
  if (document.querySelector(".cq-dragging")) return;
  for (const e of events) {
    if (e.kind !== "action" || appliedActions.has(e.seq)) continue;
    const el = document.getElementById(e.widget);
    // Marked applied only once a widget takes it: a widget that isn't on the page
    // yet — one inside a thread reply renders after this pass — retries next poll,
    // and per-widget seq order holds because its earlier actions are pending too.
    if (!el?.applyAction) continue;
    // Page widgets replay the on-screen version's own actions, plus undelivered
    // ones from older versions (seq > cursor): Claude can't have declined or
    // honored what it hasn't been handed, so the reviewer's edit carries forward
    // instead of visibly reverting when a concurrently-written version publishes.
    // A widget inside the comment layer (.cq-ui — a reply's inline question) is
    // version-independent: its markup is frozen in the log and no version can
    // ever carry its state, so its actions replay on every version.
    if (
      !el.closest(".cq-ui") &&
      !(e.version === VNUM || (e.version < VNUM && e.seq > cursor))
    ) {
      appliedActions.add(e.seq);
      continue;
    }
    appliedActions.add(e.seq);
    // A foreign action older than one this tab already applied to the widget
    // would yank it backwards — skip it. Two tabs editing one widget in the same
    // poll window can diverge until a reload or the honoring version; the log
    // stays canonical either way.
    if (e.seq < (lastActionByWidget.get(e.widget) ?? 0)) continue;
    lastActionByWidget.set(e.widget, e.seq);
    el.applyAction(e.action, e.detail);
  }
}
async function poll() {
  let state;
  try {
    state = await (await fetch("/api/state")).json();
  } catch {
    dot.className = "cq-dot offline";
    statusText.textContent = "Server offline — comments won't send";
    return;
  }
  events = state.events;
  cursor = state.cursor ?? 0;
  applyActions();
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
addEventListener("pagehide", () => {
  try {
    sessionStorage.setItem(VIEW_KEY, JSON.stringify(captureView()));
  } catch {}
});
const savedComposer = loadDraft("composer");

// ---------- start ----------
// Upgrades flush before the anchor pass and the view restore, so quotes and reading
// positions are re-found in the enhanced DOM, not the pre-upgrade one. A .then chain,
// never a top-level await: widget modules import this module's helpers, and awaiting
// their import at top level would deadlock the cycle (their evaluation waits on this
// module's async evaluation completing).
upgradeWidgets().then(() => {
  if (savedView && savedView.v !== VNUM) {
    restoreView(savedView);
    if (savedView.v < VNUM) showToast(`Updated to v${VNUM}`);
  }
  if (savedComposer)
    try {
      const { text, anchor, suggest } = JSON.parse(savedComposer);
      if (text) openComposer(anchor, text, (innerWidth - 320) / 2, 64, Boolean(suggest));
    } catch {}
  poll();
  setInterval(poll, POLL_MS);
});
