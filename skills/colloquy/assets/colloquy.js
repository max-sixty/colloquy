/* Colloquy runtime, loaded via <script type="module" src="/colloquy.js">: one module
 * owning both the widget layer and the comment layer.
 *
 * Widget layer: reads /registry.json (vendored per page) and dynamically imports one
 * module per tag marked x-upgrade — element-widgets need no JS at all; the theme's CSS
 * renders them. It also renders the attributes the registry marks x-says as real text
 * (renderSaid), for every widget alike: a word the page says has to be a word the
 * reviewer can select. Upgrades flush before the first anchor pass, so comment quotes
 * always search the enhanced DOM. Widget modules import the helper surface exported here
 * (`once`, `failSoft`, `settle`, `refUrl`, `sendAction`, `quoted`, `toast`,
 * `announce`, `keyHelp`, `reveal`, `pageScroller`, `REDUCED`, `SCROLL`); it stays
 * minimal until a real widget needs more.
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
 * POST /api/event. Everything it injects is namespaced .cq-* and marked .cq-ui, and it
 * styles itself from the theme's tokens so it themes with the page.
 *
 * .cq-ui marks the runtime's own words: its layer, and the controls a widget injects.
 * Anchoring skips it, print hides it, and it carries the system-ui face that says "this
 * is not the document" — which is why it is not the marker for "chrome". A widget's own
 * label or heading is the page's word in a chrome look, and wears data-cq-gen alone: the
 * diff looks away from it, the anchor pass does not. CLAUDE.md carries why.
 *
 * Passages and anchors: a comment points at an anchor (a section id, a quote, and the
 * neighbouring words where there are any). resolveAnchor is the only place the page is
 * searched and paintAnchors the only place it is marked; CLAUDE.md carries why.
 *
 * Never lose user text (CLAUDE.md): every unsent draft — the general box, each per-thread
 * reply, and the selection composer (text + its anchor) — persists to localStorage on
 * input. localStorage is partitioned by origin and each page directory gets its own port,
 * so the keys are implicitly per-page.
 *
 * Versions: an unpinned page follows the newest version, navigating to each revision as
 * Claude ships it. Picking an older version pins the view (?pin in the URL); a pinned
 * page stays put and offers the newest version as a chip instead.
 *
 * Composing: every textarea behaves identically — saves its draft on each keystroke,
 * sends on ⌘/Ctrl+Enter — because they are all wired through wireInput. Growing with
 * its content is the stylesheet's job: `field-sizing: content` on the one text-box rule,
 * which a widget's own box opts into by wearing `cq-ui`. No script measures a textarea,
 * so none can leave one momentarily too small for its own text — the shape of bug that
 * flashes a scrollbar per keystroke. A poll that re-renders the thread list restores
 * scroll offset, focus, and the caret, so an arriving reply never interrupts one being
 * typed. A composer open on a selection keeps that passage marked in the page until it
 * closes, because focusing the box drops the browser's own selection — and that mark is
 * what says which passage the box is on, so the box only quotes the passage back when
 * this version no longer has one to mark. Whether the box is up is state the stylesheet
 * renders, never state read back off the stylesheet.
 *
 * Scrolling: the document scrolls body, not the viewport, and body's margin keeps its
 * box clear of the open panel. Two scroll regions side by side, each scrollbar drawn
 * inside its own region — a viewport-scrolled document would paint its scrollbar over
 * the panel, stacked on the panel's own. Reading position goes through pageScroller.
 *
 * Keyboard: two scopes, matching the DOM's own. One dispatcher drives a table of
 * global single-key shortcuts (KEYS — also the source of the "?" overlay, so help
 * can't drift from behavior); it skips typing contexts (editable target, ⌘/Ctrl/Alt,
 * IME) and anything a focused control already consumed (defaultPrevented), which is
 * how a widget's own keys shadow the table. Focus-scoped keys belong to the focused
 * control itself — panel threads here, grips and pick buttons in widget modules —
 * with no registration: the only keyboard exports widgets need are announce() (the
 * live region) and keyHelp() (rows for the overlay). Escape alone crosses into typing
 * context, backing out one layer per press without ever eating text.
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

// The theme's reduced-motion guard covers CSS animation and transitions; motion
// driven from JS — smooth scrolls here, Web-Animations moves in widgets — checks
// this instead.
export const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
export const SCROLL = REDUCED ? "instant" : "smooth";

// Mention, not use: a widget inside <cq-specimen> is quoted material. An
// interactive widget consults this before wiring anything that would carry
// input back (cq-options' choose path, cq-board's grips and drags), so an
// exhibit never takes the reader's edits. Presentational upgrades and view
// state run regardless — a quoted diagram still renders, a quoted settled
// group still collapses.
export function quoted(el) {
  return el.closest("cq-specimen") !== null;
}

// The element the document scrolls: body, not the viewport (see the stylesheet below,
// and Scrolling in the module header). Anything that reads a reading position, sets
// one, or hands a scroll container to a library uses this — window.scrollY is always 0
// here, and document.scrollingElement still names the html element, which no longer
// scrolls. Vendored libraries that resolve the scroller themselves are the trap:
// SortableJS walks up from the dragged card and, on reaching body, hands back
// document.scrollingElement, so cq-board passes this in rather than letting it guess.
export const pageScroller = document.body;

// A widget's report of the user editing the document through it (a card dragged
// between columns). The caller has already applied the edit to its own DOM; the
// poll's replay re-applies it once (see applyActions), which is why applyAction
// implementations must state an absolute placement, never a relative mutation.
export function sendAction(el, action, detail) {
  return post({ kind: "action", version: VNUM, widget: el.id, action, detail });
}

// Transient confirmation ("Moved to Doing — sent to Claude"), styled and placed by
// the comment layer. Announced too: toast routes through the live region.
export function toast(msg) {
  showToast(msg);
}

// Announce to assistive tech without a visual: the runtime's polite live region.
// Cleared first so repeating a message (two identical moves) re-announces.
export function announce(msg) {
  liveEl.textContent = "";
  setTimeout(() => (liveEl.textContent = msg), 30);
}

// Rows for the "?" overlay. A widget with focus-scoped keys declares them beside
// the code implementing them: keyHelp("On a card grip", [["Enter", "grab"], …]).
const helpSections = [];
export function keyHelp(title, rows) {
  helpSections.push({ title, rows });
}

// A scroll target can sit inside a collapsed container — a closed <details>, an
// inactive tab. Opening what the platform owns (details) and letting a container
// widget open what it owns (the cq-reveal event; cq-tabs listens) gives the
// target geometry before the scroll. Called before every scroll-to-content.
export function reveal(el) {
  for (let a = el; a; a = a.parentElement) {
    if (a.tagName === "DETAILS" && !a.open) a.open = true;
    if (a.hidden) a.dispatchEvent(new CustomEvent("cq-reveal"));
  }
}

// The vocabulary, vendored per page: which tags a module upgrades, and which of their
// attributes are words the page says (see renderSaid).
let registry = null;

async function upgradeWidgets() {
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
  renderSaid(document.body);
  // Importing defined the elements and ran their connectedCallbacks; async ones
  // registered their work via settle(). Wait it out so geometry is final.
  await Promise.allSettled(settling);
}

// Words a widget says through an attribute — a metric's number, an event's time, an
// option's effort — rendered as text the reviewer can reach. The theme renders the same
// words with `content: attr()`, and a pseudo-element's glyphs are in no text node: no
// selection can cover them, so no comment can be anchored on them, and the page shows
// text you can read and can't point at. Not the widget author's to remember, either: the
// registry names the attributes (x-says) and one pass renders them, so a widget cannot
// render a word the reviewer can't quote.
//
// Each value goes at the edge its pseudo-element occupied (before = first child, after =
// last) — the only placement a pseudo could ever have had, and so the line past which a
// widget writes its own (cq-milestone's chips are a list and sit mid-element;
// cq-column's heading is its list's accessible name, which this pass knows nothing
// about). Those write the same data-cq-said span, and the guard below means the two
// compose rather than race. The pass runs after the upgrades, so a module that rebuilds
// its own body can't wipe a span put there first.
//
// The theme's pseudo rules stay, as the rendering a page carrying no script at all still
// gets (docs/how-it-works.html is one); they stand down where this pass has been, asked
// by :has(), so the two are never both on. The span is data-cq-gen and not .cq-ui: the
// diff parses the base version unupgraded and must not read it as text that version
// lacked, and the reviewer must be able to quote it.
function renderSaid(root) {
  // ?? {}: a reply's widgets reach here on a page with no vendored registry too, where
  // nothing upgrades and the theme's pseudo-elements are doing the rendering.
  for (const [tag, entry] of Object.entries(registry ?? {})) {
    if (!entry["x-says"]) continue;
    for (const el of root.querySelectorAll(tag))
      for (const [attr, edge] of Object.entries(entry["x-says"])) {
        const text = el.getAttribute(attr);
        if (text === null || el.querySelector(`:scope > [data-cq-said="${attr}"]`)) continue;
        const span = document.createElement("span");
        span.dataset.cqSaid = attr;
        span.dataset.cqGen = "1";
        span.textContent = text;
        el[edge === "before" ? "prepend" : "append"](span);
      }
  }
}

// ---------- comment layer ----------

const VERSION_MATCH = location.pathname.match(/\/versions\/v(\d+)\.html$/);
const VNUM = VERSION_MATCH ? parseInt(VERSION_MATCH[1], 10) : null;
const PINNED = new URLSearchParams(location.search).has("pin");
// Sign-off is the page's ask, not standing chrome: the approve button exists only
// when the version declares <meta name="cq-review" content="sign-off"> — a plan or
// proposed change seeking assent. An informational page takes comments only. The
// declaration rides the document, so a pinned older version keeps its own ask.
const SIGNOFF =
  document.querySelector('meta[name="cq-review"]')?.content === "sign-off";
const POLL_MS = 2000;

// ---------- styles ----------
const style = document.createElement("style");
style.textContent = `
  /* The document and the panel are two scroll regions side by side. If the document
     scrolled the viewport, its scrollbar would paint at the viewport's right edge —
     over the panel, in the same few pixels as the panel's own, so the two thumbs
     stack. Body owns the document's scroll instead, and syncLayout keeps its box
     clear of the panel, which puts each region's scrollbar inside that region. */
  html { height: 100%; overflow: hidden; }
  body { box-sizing: border-box; height: 100%; overflow-y: auto; scroll-padding-top: 54px; }
  @media print { html, body { height: auto; overflow: visible; } }
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
  /* contain: reaching the end of the thread list must not start scrolling the page
     behind it — one wheel gesture moves one region. */
  .cq-threads { flex: 1; overflow-y: auto; overscroll-behavior: contain; padding: 10px 14px; }
  .cq-empty { color: var(--muted); padding: 18px 4px; }
  .cq-thread { border: 1px solid var(--rule); border-radius: var(--r); padding: 10px; margin-bottom: 12px; }
  .cq-thread.flash { animation: cq-flash 1.2s ease-out; }
  @keyframes cq-flash { 0% { background: var(--hi-tint); } 100% { background: var(--card); } }
  .cq-quote { margin: 0 0 8px; padding: 2px 8px; border-left: 3px solid var(--quote-bar); color: var(--muted); font-style: italic; cursor: pointer; overflow-wrap: anywhere; }
  .cq-quote:hover { color: var(--ink-2); }
  .cq-quote.detached { border-left-style: dashed; border-left-color: var(--border-2); color: var(--muted-2); cursor: default; }
  /* Out of the picture, still in the accessibility tree — see the composer's quote in
     paintAnchors for the one thing that wears this and why. */
  .cq-unseen { position: absolute; width: 1px; height: 1px; padding: 0; border: 0; overflow: hidden; clip-path: inset(50%); }
  .cq-msg { margin: 8px 0; }
  .cq-msg-head { display: flex; gap: 6px; align-items: baseline; }
  .cq-msg-head b { font-size: 12.5px; }
  .cq-msg.claude .cq-msg-head b { color: var(--accent); }
  .cq-msg time { color: var(--muted-2); font-size: 11.5px; }
  .cq-msg p { margin: 2px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; }
  /* Send buttons sit at the bottom so a growing textarea doesn't stretch them. */
  .cq-compose, .cq-general { display: flex; gap: 6px; margin-top: 8px; align-items: flex-end; }
  /* The colloquy text box, in one rule. field-sizing does the growing, so no script
     measures a textarea: the JS that did had to reset height to auto to re-measure,
     which made the box briefly too small for its own text on every keystroke — and a
     box that overflows, however briefly, flashes a scrollbar. Past max-height the
     scrollbar is real and stays. Both selectors: the panel's boxes sit inside .cq-ui,
     a widget's own box wears the class itself. */
  .cq-ui textarea, textarea.cq-ui { font: inherit; padding: 5px 8px; border: 1px solid var(--border-2); border-radius: 6px; background: var(--card); color: inherit; resize: none; field-sizing: content; max-height: 200px; overflow-y: auto; }
  .cq-ui textarea:focus, textarea.cq-ui:focus { outline: none; border-color: color-mix(in srgb, var(--accent) 45%, var(--card)); box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 25%, transparent); }
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
  /* A stranded quote is the whole passage, and the box is 320px wide. Only while showing:
     on the hidden one this would out-specify .cq-unseen's own overflow. */
  .cq-composer .cq-quote:not(.cq-unseen) { max-height: 4.2em; overflow-y: auto; }
  .cq-suggest-row { display: none; align-items: center; gap: 6px; margin: 0 0 6px; color: var(--muted); font-size: 12.5px; cursor: pointer; }
  .cq-suggest-row input { margin: 0; accent-color: var(--accent); }
  .cq-suggest-label { font-size: var(--t-6); letter-spacing: .05em; text-transform: uppercase; color: var(--ok-ink); margin: 4px 0 2px; }
  .cq-msg p.cq-suggest-body { background: var(--add-tint); padding: 4px 8px; border-radius: 6px; }
  .cq-composer textarea { width: 100%; min-height: 56px; }
  .cq-composer-row { display: flex; justify-content: flex-end; gap: 6px; margin-top: 6px; }
  /* A marked passage is painted, not wrapped (see paintAnchors), so its rules reach it
     through the highlight registry — which styles glyphs, so the underline stands in for
     a border and the pointer's cursor comes from a class the hit-test puts on body. A
     posted thread's mark wears the marker amber; the open composer's draft wears the
     accent, and outranks it where they overlap. Not dashed — dashed means detached. */
  ::highlight(cq-mark) { background-color: var(--mark);
    text-decoration: underline 2px solid var(--quote-bar); text-underline-offset: 3px; }
  ::highlight(cq-mark-hover) { background-color: var(--mark-strong); }
  ::highlight(cq-pending) { background-color: color-mix(in srgb, var(--accent) 20%, transparent);
    text-decoration: underline 2px solid var(--accent); text-underline-offset: 3px; }
  body.cq-over-mark { cursor: pointer; }
  .cq-mark-el { outline: 2px solid var(--quote-bar); outline-offset: 3px; border-radius: 2px; cursor: pointer; }
  .cq-mark-el.cq-pending { outline-color: var(--accent); cursor: auto; }
  .cq-btn.on { border-color: var(--accent); color: var(--accent); background: var(--chip); }
  .cq-ins-block { background: var(--add-tint); box-shadow: 0 0 0 4px var(--add-tint); border-radius: 2px; }
  .cq-toast { position: fixed; bottom: 18px; right: 18px; z-index: 9200; background: var(--ink); color: var(--paper);
    padding: 9px 14px; border-radius: var(--r); opacity: 0; transition: opacity .25s; pointer-events: none; }
  .cq-toast.show { opacity: .95; }
  .cq-toast.clickable { pointer-events: auto; cursor: pointer; }
  .cq-live { position: fixed; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
  .cq-thread:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  .cq-help { position: fixed; z-index: 9300; top: 50%; left: 50%; transform: translate(-50%, -50%);
    width: min(420px, calc(100vw - 32px)); max-height: 80vh; overflow-y: auto; display: none;
    background: var(--card); border: 1px solid var(--border-2); border-radius: var(--r);
    box-shadow: 0 12px 32px rgba(0,0,0,.18); padding: 14px 18px; }
  .cq-help.open { display: block; }
  .cq-help-title { font-weight: 600; margin-bottom: 10px; }
  .cq-help h3 { margin: 12px 0 4px; font-size: var(--t-6); font-weight: 600;
    text-transform: uppercase; letter-spacing: .05em; color: var(--muted); }
  .cq-help table { width: 100%; border-collapse: collapse; }
  .cq-help td { padding: 3px 0; vertical-align: baseline; }
  .cq-help td:first-child { width: 84px; white-space: nowrap; }
  .cq-help kbd { font-family: ui-monospace, monospace; font-size: 12px; background: var(--chip);
    border: 1px solid var(--border-2); border-radius: 4px; padding: 1px 6px; }
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
const acceptAllBtn = el("button", "cq-btn", "");
acceptAllBtn.style.display = "none";
acceptAllBtn.title = "Accept every suggested change still pending";
const versionSelect = document.createElement("select");
versionSelect.title = "Version";
versionSelect.setAttribute("aria-label", "Version");
const toggleBtn = el("button", "cq-btn", "Comments");
toggleBtn.title = "Show or hide the comment panel (c toggles, Esc closes, ? lists all keys)";
toggleBtn.setAttribute("aria-expanded", "false");
const approveBtn = el("button", "cq-btn primary", "✓ Looks good");
approveBtn.title = "Sign off — Claude stops watching this page";
banner.append(
  dot,
  statusText,
  el("span", "cq-spacer"),
  latestChip,
  acceptAllBtn,
  diffBtn,
  versionSelect,
  toggleBtn,
);
if (SIGNOFF) banner.append(approveBtn);

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
// Only ever shown detached — paintAnchors, its one writer, keeps it out of sight while
// the page is marking the passage. cq-ui on the element itself, not just on the composer
// around it: this is the only injected chrome carrying an id, and "which section is this
// in" is asked as `[id]:not(.cq-ui)` of the element rather than of its ancestors, so
// without the class it answers that question with itself.
const composerQuote = el("blockquote", "cq-ui cq-quote detached");
composerQuote.id = "cq-composer-quote";
// Suggestion mode: the box holds replacement text for the quoted passage
// instead of a remark — Claude accepts it verbatim into the next version.
const suggestRow = el("label", "cq-suggest-row");
const suggestCheck = document.createElement("input");
suggestCheck.type = "checkbox";
suggestRow.append(suggestCheck, document.createTextNode("Suggest replacement text"));
const composerInput = document.createElement("textarea");
// The mark is a paint, and a paint is nothing to a screen reader (see "Paint; don't wrap"
// in CLAUDE.md). So what the box is anchored to travels as the box's own description,
// announced on focus — which is more than the visible quote ever said, since nothing
// pointed a reader at it.
composerInput.setAttribute("aria-describedby", composerQuote.id);
const composerRow = el("div", "cq-composer-row");
const composerCancel = el("button", "cq-btn", "Cancel");
const composerSend = el("button", "cq-btn primary", "Comment");
composerRow.append(composerCancel, composerSend);
composer.append(composerQuote, suggestRow, composerInput, composerRow);
const toastEl = el("div", "cq-ui cq-toast");
const liveEl = el("div", "cq-ui cq-live");
liveEl.setAttribute("aria-live", "polite");
const helpEl = el("div", "cq-ui cq-help");
helpEl.setAttribute("role", "dialog");
helpEl.setAttribute("aria-label", "Keyboard reference");
helpEl.tabIndex = -1; // focused on open, so the dialog isn't silent to a screen reader

document.body.append(banner, panel, fab, composer, toastEl, liveEl, helpEl);
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
// Exported: a widget holding user text (cq-draft's in-place edit) keeps it under the
// same discipline, in the same store, rather than growing a second one.
const DRAFT = "cq-draft:";
export const saveDraft = (ctx, val) => {
  try {
    if (val) localStorage.setItem(DRAFT + ctx, val);
    else localStorage.removeItem(DRAFT + ctx);
  } catch {}
};
export const loadDraft = (ctx) => {
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
  // A margin, not padding: body is the document's scroll container, so this is what
  // ends its box — and its scrollbar — at the panel's edge instead of under it.
  // Below the breakpoint the panel covers the page rather than squeezing it, so
  // there's nothing to reserve room for.
  document.body.style.marginRight =
    panelOpen && innerWidth > 720 ? panel.offsetWidth + "px" : "";
  // The toast lives in the same corner as the panel's Send button; step it aside so a
  // "couldn't send" message never covers the button it's talking about.
  toastEl.style.right = (panelOpen ? panel.offsetWidth + 18 : 18) + "px";
}
function setPanel(open) {
  panelOpen = open;
  panel.classList.toggle("open", open);
  toggleBtn.setAttribute("aria-expanded", String(open));
  syncLayout();
  try {
    localStorage.setItem(PANEL_KEY, open ? "1" : "0");
  } catch {}
  if (open) {
    renderPanel();
    syncGeneral(); // a restored draft has to reach the Send button's disabled state
  }
}
toggleBtn.onclick = () => setPanel(!panelOpen);
addEventListener("resize", syncLayout);

let toastTimer = 0;
function showToast(msg, onClick) {
  announce(msg);
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
// selection composer. They persist a draft on each keystroke, send on ⌘/Ctrl+Enter, and
// can't be double-sent by an impatient second click. Growing with their content is the
// stylesheet's job (field-sizing), not this file's.
// Returns a sync() the caller runs after setting .value programmatically, so the send
// button agrees with what's in the box.
const SEND_KEYS = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent)
  ? "⌘⏎"
  : "Ctrl+⏎";
function wireInput(ta, { hint, save, send, sendBtn }) {
  // The shortcut goes in the placeholder, where it's visible exactly while the box is
  // empty and can't be found any other way; the button's tooltip spells it out.
  ta.placeholder = `${hint} · ${SEND_KEYS}`;
  sendBtn.title = `Send (${SEND_KEYS})`;
  let sending = false;
  const sync = () => {
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
    if (m.author === "claude" && /<cq-[a-z]/.test(m.text || "")) {
      body.innerHTML = m.text;
      renderSaid(body); // custom elements upgrade themselves on insertion; this doesn't
    } else body.textContent = m.text || "";
    if (m.suggestion) body.classList.add("cq-suggest-body");
    if (m.id) msgBodies.set(m.id, body);
  }
  div.append(head);
  if (m.suggestion) div.append(el("div", "cq-suggest-label", "suggested replacement"));
  div.append(body);
  return div;
}

// How an anchor reads where it has to be printed rather than pointed at — every thread in
// the panel, and the open composer when the page has no passage left to mark. A quote-less
// anchor points at an element (a diagram or image commented on by click rather than by
// selection) and names its section instead of quoting it. One function, so the two places
// can't come to say it differently.
const anchorLabel = (anchor) =>
  anchor?.quote ? `“${anchor.quote}”` : anchor?.section ? `§ ${anchor.section}` : "";

function threadNode(t, syncs) {
  const div = el("div", "cq-thread");
  div.tabIndex = -1; // j/k focus target; Enter (below) drops into its reply box
  div.dataset.id = t.root.id;
  const label = anchorLabel(t.root.anchor);
  if (label) {
    const quote = el("blockquote", "cq-quote", label);
    quote.onclick = () => scrollToThread(t.root.id);
    div.append(quote);
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
  // offset, and the focused thread — with the caret, when they were mid-way through
  // typing a reply in it. Otherwise a reply arriving mid-sentence yanks the panel to
  // the top and drops the cursor, and a poll steals a j/k walk's place.
  const scrollTop = threadsBox.scrollTop;
  const active = document.activeElement;
  const focusedId = active?.closest?.(".cq-thread")?.dataset.id ?? null;
  const caret =
    focusedId && active.tagName === "TEXTAREA"
      ? [active.selectionStart, active.selectionEnd]
      : null;

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
  syncs.forEach((sync) => sync()); // a restored reply draft enables its Reply button
  toggleBtn.textContent = `Comments (${open.length})`;

  if (focusedId) {
    const div = threadsBox.querySelector(`.cq-thread[data-id="${focusedId}"]`);
    if (caret) {
      const ta = div?.querySelector("textarea");
      if (ta) {
        ta.focus();
        ta.setSelectionRange(caret[0], caret[1]);
      }
    } else div?.focus({ preventScroll: true });
  }
  threadsBox.scrollTop = scrollTop; // after focus(), which scrolls the panel itself
}

// The panel and the page marks are two views of the same threads, and the paint pass
// reports back to the list renderThreads just built — always render them as a pair.
function renderPanel() {
  renderThreads();
  paintAnchors();
}

// ---------- passages ----------
// A passage is a list of {node, start, end} segments, and everything that reads the page's
// text speaks in them: the search for a quote, the capture of one, the landmark a version
// change rides on, the version diff's block keys. One shape means one answer to what the
// page says. The bugs this layer kept having were all a second answer disagreeing with the
// first — what a selection rendered as versus what the document holds — and a second
// answer is what there is now no room for.
//
// Two skip lists, because two jobs genuinely differ, and the difference is the whole
// reason .cq-ui and data-cq-gen are two markers rather than one. Anchoring skips the
// runtime's own words, inline scripts, and the stylesheet a rendered diagram carries
// inside its <svg>: a quote holding text the search skips is a quote nothing can find
// again. The version diff additionally skips content an upgrade generated, because the
// base document parses unupgraded and would never match it. So generated text the page
// authored — a widget's label, an attribute renderSaid rendered — is diff-invisible and
// quotable, which is the pair a reviewer expects: they can point at it, and it doesn't
// read as a change nobody wrote.
//
// A decided suggestion's retired slot goes with them. Its markup is still in the
// document — the honoring version is what finally drops it — but the reviewer has
// removed it, and the live view is the version plus their decisions. Text nobody can
// see is text nobody can mean: without this a comment made on a passage then accepted
// away kept reading as attached in the panel and jumped nowhere, and a quote from
// elsewhere could match inside the invisible half of a replacement.
const RETIRED =
  'cq-suggestion[data-cq-state="accepted"] > cq-old, cq-suggestion[data-cq-state="rejected"] > cq-new';
const UNQUOTABLE = `.cq-ui, script, style, ${RETIRED}`;
const GENERATED = ".cq-ui, [data-cq-gen]";
// The same question one node at a time: is this the runtime's own chrome rather than the
// document? Every affordance asks it before acting on where the pointer or the caret is.
const inUi = (node) =>
  Boolean((node?.nodeType === 1 ? node : node?.parentElement)?.closest(".cq-ui"));
const TEXT_BLOCK = "p,li,h1,h2,h3,h4,h5,h6,td,th,pre,blockquote,dd,dt,figcaption,summary";
// ownerDocument, not document: the diff walks a base version parsed into its own document.
function textNodesUnder(rootEl, skip = UNQUOTABLE) {
  const walker = rootEl.ownerDocument.createTreeWalker(rootEl, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) =>
      n.parentElement?.closest(skip) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
  });
  const segments = [];
  for (let n = walker.nextNode(); n; n = walker.nextNode())
    segments.push({ node: n, start: 0, end: n.data.length });
  return segments;
}

// The segments a selection covers, clipped to where it starts and ends.
function segmentsIn(range) {
  const root = range.commonAncestorContainer;
  const whole = textNodesUnder(
    root.nodeType === Node.ELEMENT_NODE ? root : root.parentElement,
  );
  const segments = [];
  for (const { node, end: length } of whole) {
    if (!range.intersectsNode(node)) continue;
    const start = node === range.startContainer ? range.startOffset : 0;
    const end = node === range.endContainer ? range.endOffset : length;
    if (end > start) segments.push({ node, start, end });
  }
  return segments;
}

// Segments as prose — what a comment stores as its quote, and what a reading position
// remembers. A space goes in wherever a block boundary falls between two segments, so a
// passage crossing two paragraphs doesn't read as one run-on word. Whitespace collapses,
// since the same passage carries the author's line wraps in the source and the rendering's
// on screen. Sliced by code point, because half a surrogate pair is a character no UTF-8
// file can hold. Where the spaces landed is cosmetic to the search: a quote's own
// whitespace is elastic to findQuote, so nothing downstream depends on this.
const blockOf = (node) => node.parentElement.closest(TEXT_BLOCK) ?? node.parentElement;
function quoteFrom(segments) {
  let text = "";
  segments.forEach((seg, i) => {
    if (i && blockOf(seg.node) !== blockOf(segments[i - 1].node)) text += " ";
    text += seg.node.data.slice(seg.start, seg.end);
  });
  return [...text.replace(/\s+/g, " ").trim()].join("");
}
// Cutting one to length is the caller's business and always by code point: half a surrogate
// pair is a character no UTF-8 file can hold, and a quote is written to one.
const cut = (text, from, to) => [...text].slice(from, to).join("");

// A passage as one Range: what paints it, and what measures it for a scroll.
function rangeOf(segments) {
  const range = document.createRange();
  range.setStart(segments[0].node, segments[0].start);
  range.setEnd(segments.at(-1).node, segments.at(-1).end);
  return range;
}

// Find `quote` among `segments`; returns the segments it covers, or none. The quote's own
// whitespace is treated as elastic and the page's is not, which is the asymmetry the
// problem actually has. The same passage gets written down with a break where the source
// wrapped it, with one where the rendering broke a block, and with none where two blocks
// abut, so a gap in the quote has to match any gap in the page or none at all — otherwise
// every producer has to agree on whitespace, and that agreement is the one this file kept
// getting wrong. The converse is not true: where the quote runs two words together the
// page may not, or a short quote starts matching inside longer words — "never" finding the
// tail of "on every", in a different paragraph.
// So a gap has to match *something* that separates words. Whitespace is one; an element
// boundary is the other, and it leaves no character behind, which is why the raw text is
// built with one standing in for it. Between the characters of a single word only a
// boundary may fall — `<strong>bold</strong>text` reads as one word and is quoted as one —
// and without that floor a gap could match nothing at all, so "set up" would find "setup"
// in an earlier sentence and anchor there for good.
const EDGE = "\u0000"; // no document holds one, so it can't collide with page text
// A quote names text, not a place, and a page is free to say the same thing twice. Where it
// does, the words on either side decide which occurrence was meant. A unified diff holds
// the same line on both sides by construction, so without this, commenting on a fixed line
// marked the broken one — the reviewer's objection attached to the code they were objecting
// to, and stored that way. Section scoping cannot reach it, because both sides of a diff
// live under one id. Context rather than an offset: an offset goes stale silently when the
// page is revised, while neighbours can be checked against the page as it now stands — see
// `confirms` for what checking them means, and what it deliberately refuses to do.
// Anchors written before this carry none and resolve as they did.
// The characters of raw[lo..hi) as segments, so a neighbourhood can be read back with the
// same function that wrote it down. Edges hold no character and are simply absent.
function spanOf(origin, lo, hi) {
  const out = [];
  for (let i = Math.max(0, lo); i < Math.min(origin.length, hi); i++) {
    const at = origin[i];
    if (!at) continue;
    const last = out.at(-1);
    if (last && last.node === at.node && last.end === at.offset) last.end = at.offset + 1;
    else out.push({ node: at.node, start: at.offset, end: at.offset + 1 });
  }
  return out;
}
// Context identifies a passage only when its neighbours are still exactly what they were.
// A partial match is not weak evidence for the right copy — it is evidence the page moved
// on, and acting on it is how a comment ends up somewhere it was never made: a version that
// rewrote the sentence beside the anchored copy left an untouched copy elsewhere matching
// better, and the comment followed it there. Demanding the whole stored context is what
// makes that rare: anything short of certainty falls back to the order the search used
// before context existed.
//
// Rare, not impossible. The bar is however much was stored, so a passage at the edge of its
// section has thin context and thin context is a bar another copy can clear — which is why
// the search below refuses one-sided context outright. That still leaves a side of one
// character clearing the gate; TODO.md carries what closing it properly would take.
//
// The bar is what the capture actually produces, not a number picked to fit: across every
// selection in the shipped examples, an unmodified page confirms its stored context in full.
const confirms = (a, b, fromEnd) => {
  let n = 0;
  const len = Math.min(a.length, b.length);
  while (n < len && (fromEnd ? a.at(-1 - n) === b.at(-1 - n) : a[n] === b[n])) n++;
  return n;
};
// As much collapsed text as the stored context is long, however much raw text that takes.
// A fixed raw budget reads less than the capture wrote wherever whitespace runs dense — an
// indented line inside a <pre> — and the right occurrence then confirms none of its own
// neighbours. `want` is the stored string's own length rather than the cap the capture
// spent, because the capture counted code points and this counts code units: an emoji in
// the neighbourhood makes those different numbers, and a window short by even one character
// can never confirm, so the anchor would fall back to first-match on that page forever.
function neighbourhood(origin, at, want, before) {
  for (let raw = want * 2; ; raw *= 2) {
    const lo = before ? at - raw : at;
    const hi = before ? at : at + raw;
    const text = quoteFrom(spanOf(origin, lo, hi));
    // >=, not >, so a caller asking for nothing gets an answer: doubling zero never grows.
    if (text.length >= want || (before ? lo <= 0 : hi >= origin.length)) return text;
  }
}
const escape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
function findQuote(segments, quote, anchor) {
  let raw = "";
  const origin = []; // origin[i] = {node, offset} for raw[i]; null for an edge
  for (const seg of segments) {
    if (raw) {
      origin.push(null);
      raw += EDGE;
    }
    for (let i = seg.start; i < seg.end; i++) {
      origin.push({ node: seg.node, offset: i });
      raw += seg.node.data[i];
    }
  }
  const words = quote.trim().split(/\s+/).filter(Boolean);
  if (!words.length) return [];
  const pattern = new RegExp(
    words
      .map((w) => [...w].map(escape).join(`${EDGE}*`))
      .join(`[\\s${EDGE}]+`),
    "g",
  );
  // The first occurrence whose neighbours are all still there; failing that, the first
  // occurrence at all — which is what a context-less anchor gets, and what every anchor got
  // before context existed. matchAll steps past each hit, so overlapping occurrences of a
  // quote that repeats inside itself are not candidates. The neighbourhood is read back
  // through quoteFrom, the same function that wrote the context down: anything else is a
  // second answer to "what does the page say here", and the two disagree exactly where a
  // diff puts its line breaks.
  const [pre, post] = [anchor.prefix ?? "", anchor.suffix ?? ""];
  let first = null;
  let found = null;
  for (const at of raw.matchAll(pattern)) {
    first ??= at;
    // Both sides or nothing. The bar is however much was stored, so a passage that opens or
    // closes its section offers only one side — a bar another copy can clear, and then a
    // revision hands the comment to a passage it was never made on. That failure is silent
    // and arrives later, when nobody is looking; the failure it costs is the mark painting
    // on the wrong copy while the reviewer is still composing, in front of them. Two of the
    // 197 selections context places across the shipped examples are the price.
    if (!pre || !post) break;
    const stop = at.index + at[0].length;
    const kept =
      confirms(neighbourhood(origin, at.index, pre.length, true), pre, true) +
      confirms(neighbourhood(origin, stop, post.length, false), post, false);
    if (kept === pre.length + post.length) {
      found = at;
      break;
    }
  }
  found ??= first;
  if (!found) return [];
  // Both ends land on a real character: the pattern opens and closes on one, and an edge
  // only ever stands between them.
  const from = origin[found.index];
  const to = origin[found.index + found[0].length - 1];
  const hit = [];
  let started = false;
  for (const seg of segments) {
    const start = seg.node === from.node ? from.offset : started ? seg.start : null;
    if (start === null) continue;
    started = true;
    const end = seg.node === to.node ? to.offset + 1 : seg.end;
    if (end > start) hit.push({ node: seg.node, start, end });
    if (seg.node === to.node) break;
  }
  return hit;
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

// The first text block still on screen below the banner: what the reader is reading. A
// block's landmark is the top of its first line (a range), not its border box; restore
// measures the matched text the same way, so the line box's leading cancels out.
// The quote and the section it's searched in come from the same block, or the search is
// scoped to a subtree the text isn't in and can only ever fail — restore then falls back
// to the section, which doesn't absorb content added above the reader inside it.
function captureView() {
  const view = { v: VNUM, y: pageScroller.scrollTop };
  for (const block of document.querySelectorAll(TEXT_BLOCK)) {
    // [hidden] needs an explicit skip: hidden="until-found" resolves to
    // content-visibility, under which descendants still report real rects —
    // but what's behind an inactive tab isn't what the reader is reading.
    if (block.closest(".cq-ui, [hidden]")) continue;
    const range = document.createRange();
    range.selectNodeContents(block);
    const rect = range.getBoundingClientRect();
    if (!rect.height || rect.bottom <= 42) continue; // 42 = banner height
    const section = block.closest("[id]:not(.cq-ui)");
    if (!view.section && section) {
      // The first on-screen block's section, kept only until a quotable block supplies
      // its own: a page with nothing quotable on screen still has somewhere to land.
      view.section = section.id;
      view.sectionTop = section.getBoundingClientRect().top;
    }
    // Written down the way a comment's quote is, so the search that re-finds it is
    // looking for a string of the same kind.
    const text = cut(quoteFrom(textNodesUnder(block)), 0, LANDMARK_CAP);
    // A short line ("Risks") would match anywhere; keep scanning for a quotable block.
    if (text.length >= 24) {
      // Unconditionally, so a quotable block under no section clears the earlier one
      // rather than sending the search into a subtree its text isn't in.
      view.section = section?.id;
      view.sectionTop = section?.getBoundingClientRect().top;
      view.quote = text;
      view.quoteTop = rect.top;
      break;
    }
  }
  return view;
}

// A restore jumps rather than glides: a page is free to set scroll-behavior: smooth, and
// animating from the top of a fresh document is worse than the jump it replaces. Moving to
// a mark the reader asked for is the other case, and says so.
const jumpBy = (dy, behavior = "instant") => pageScroller.scrollBy({ top: dy, behavior });
function restoreView(view) {
  const found = view.quote && resolveAnchor(view);
  if (found?.segments) {
    reveal(found.segments[0].node.parentElement); // the passage may sit behind a tab
    jumpBy(rangeOf(found.segments).getBoundingClientRect().top - view.quoteTop);
    return;
  }
  const section = resolveAnchor({ section: view.section })?.element;
  if (section) {
    reveal(section);
    jumpBy(section.getBoundingClientRect().top - view.sectionTop);
  } else pageScroller.scrollTo({ top: view.y, behavior: "instant" });
}

// ---------- anchors ----------
// An anchor names a passage: a section id, a quote, or both. Resolving one is the only
// place the page is searched, so the three things that read a passage back — a thread's
// mark, the composer's own, and the reading position a version change rides on — cannot
// disagree about where to look. A quoteless anchor has no text to paint and resolves to
// its element instead.
// The tree a passage is looked for in: the section it names, if the page still has one.
// The capture that writes a passage's neighbours down reads them out of this same tree, so
// there is one answer to "which tree" rather than one per caller.
const searchRoot = (section) =>
  (section ? document.getElementById(section) : null) ?? document.body;
function resolveAnchor(anchor) {
  // An element anchor asks a different question — whether the section exists at all — and
  // the whole page is not an answer to it.
  if (!anchor.quote) {
    const section = anchor.section && document.getElementById(anchor.section);
    return section ? { element: section } : null;
  }
  const segments = findQuote(textNodesUnder(searchRoot(anchor.section)), anchor.quote, anchor);
  return segments.length ? { segments } : null;
}

// Every mark the page wears, drawn by one pass, so ownership of an element both a thread
// and the open composer point at is a branch inside a loop rather than an agreement
// between functions ("One writer per thing" in CLAUDE.md, and why).
//
// One range per segment, never one spanning the passage: a single range would paint back
// over everything the search stepped around on the way — a widget's Choose button, a drag
// grip, a diagram's generated stylesheet.
//
// Keyed by thread, not by mark: a passage is several segments and two comments may land on
// the same element, so mark → thread loses one of them — and losing it told the panel the
// passage wasn't in this version while it sat outlined on screen. Every consumer but the
// hit-test asks "where is thread X", and that is now the direction the map runs.
const MARK = "cq-mark";
const PENDING = "cq-pending";
const marked = new Map(); // thread id -> (Range | Element)[]: the pass's record of what it drew
let pendingMarks = []; // the same record for the open composer's own passage
let pendingOutline = null; // the element the open composer outlines, owned by nobody else
const pointer = { x: -1, y: -1 }; // last seen, so a repaint can re-answer the hover
let hovering = null;
let hoverQueued = false;
const marksOf = (id) => marked.get(id) ?? [];
const allMarks = () => [...marked.values()].flat();
function paintAnchors() {
  for (const where of allMarks())
    if (where instanceof Element) where.classList.remove("cq-mark-el");
  pendingOutline?.classList.remove("cq-mark-el", PENDING);
  marked.clear();
  pendingOutline = null;

  const posted = [];
  for (const t of buildThreads()) {
    if (t.resolved || !t.root.anchor) continue;
    const found = resolveAnchor(t.root.anchor);
    if (!found) continue;
    if (found.element) {
      found.element.classList.add("cq-mark-el");
      marked.set(t.root.id, [found.element]);
    } else {
      const ranges = found.segments.map((seg) => rangeOf([seg]));
      marked.set(t.root.id, ranges);
      posted.push(...ranges);
    }
  }

  // The composer's own passage, in the accent rather than the marker amber, so a draft
  // never reads as a posted comment. An element a thread already outlines keeps the posted
  // colour: there is one outline to give, and the thread's is the clickable one.
  const draft = composerOpen && pendingAnchor && resolveAnchor(pendingAnchor);
  // Where the draft's passage is, recorded the way the threads' is, because placeComposer
  // has to keep the box off it. An element a thread already outlines belongs in the record
  // too — it is marked, just in the posted colour rather than the accent.
  pendingMarks = draft
    ? draft.element
      ? [draft.element]
      : draft.segments.map((seg) => rangeOf([seg]))
    : [];
  const pending = [];
  if (draft?.element && !allMarks().includes(draft.element)) {
    draft.element.classList.add("cq-mark-el", PENDING);
    pendingOutline = draft.element;
  } else if (draft?.segments) pending.push(...pendingMarks);

  // The composer's echo of its own passage, decided here because here is where it is known
  // whether the page is showing that passage. Usually it is — the box opens beside the words
  // it just marked, and printing them inside it says the same sentence twice, side by side.
  // So the quote is the fallback rather than the statement: it shows where the mark can't,
  // which is where this version no longer holds the passage — a draft the reviewer carried
  // onto a newer version, whose text survived the trip when its passage didn't. Dashed and
  // muted, the panel's detached treatment, for the same fact.
  //
  // Scrolled out of view looks like that case and is not: the passage is still there, one
  // scroll back, and the reader put it there seconds ago. A quote coming and going with the
  // scroll position would resize the box under the hands typing in it.
  //
  // Out of sight is not gone: a painted mark has no accessibility exposure at all, so the
  // quote stays in the tree as the box's description whichever way it renders. Written only
  // when it changes, because assigning textContent replaces the node even with the same
  // string, and this pass reruns whenever a comment arrives — a stranded quote is the only
  // copy of that passage left, so it is text a reviewer may be selecting to keep.
  const label = composerOpen ? anchorLabel(pendingAnchor) : "";
  if (composerQuote.textContent !== label) composerQuote.textContent = label;
  composerQuote.classList.toggle("cq-unseen", !label || Boolean(draft));

  // A draft outranks a posted mark where they overlap; the hover outranks both, so the
  // passage under the pointer answers the pointer.
  CSS.highlights.set(MARK, new Highlight(...posted));
  CSS.highlights.set(PENDING, Object.assign(new Highlight(...pending), { priority: 2 }));
  refreshHover(); // the ranges moved; whether one is under the pointer may have too

  // The panel's side of the same fact, read off the pass's own record so the two views
  // can't disagree: a passage rewritten in a later version has no home to jump to, and a
  // dead-looking link is worse than one that says so.
  for (const div of threadsBox.querySelectorAll(":scope > .cq-thread")) {
    const quote = div.querySelector(".cq-quote");
    if (!quote) continue;
    const found = marked.has(div.dataset.id);
    quote.classList.toggle("detached", !found);
    quote.title = found
      ? "Jump to this passage"
      : "This passage isn't in the version you're viewing";
  }
}

// Which thread's mark is under a point. A painted range is not an element, so the pointer
// finds it by the boxes the range occupies rather than by hit-testing the DOM — asking for
// the caret position instead would claim the empty space past the end of a short line.
function markAt(x, y) {
  const over = document.elementFromPoint(x, y);
  if (inUi(over)) return null;
  for (const [id, marks] of marked)
    for (const where of marks) {
      const hit =
        where instanceof Range
          ? [...where.getClientRects()].some(
            (r) => x >= r.left && x <= r.right && y >= r.top && y <= r.bottom,
          )
          : where.contains(over);
      if (hit) return id;
    }
  return null;
}

// Move to where a thread is painted, if it still is — asked of the pass's own record, so the
// panel and the page can't disagree about whether the passage survived. A painted range has
// no element to scroll into view, so its own box does the work; reveal first, since opening
// a tab or a settled group moves everything below it.
function scrollToThread(id) {
  const where = marksOf(id)[0];
  if (!where) return;
  if (!(where instanceof Range)) {
    reveal(where);
    where.scrollIntoView({ behavior: SCROLL, block: "center" });
    return;
  }
  const holder = where.startContainer.parentElement;
  reveal(holder);
  // Sideways first, and only as far as it takes: a passage inside a wide `pre` or a
  // rendered diagram sits in a box with its own horizontal scroll, which the vertical
  // jump below cannot reach — scrolling to it in one axis leaves it off-screen in the other.
  holder.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "instant" });
  const rect = where.getBoundingClientRect();
  jumpBy(rect.top - (innerHeight - rect.height) / 2, SCROLL);
}

// Pointer feedback a wrapped <mark> got from :hover and cursor: pointer, neither of which
// ::highlight() can carry — it styles glyphs, not boxes. Same hit-test as the click, so
// what lights up is what would open. It is a function of where the pointer is and what the
// page's geometry is, so everything that moves either asks again: the pointer moving, the
// page scrolling under a still pointer, and the pass redrawing the ranges themselves.
const HOVER = "cq-mark-hover";
function paintHover(id) {
  hovering = id;
  document.body.classList.toggle("cq-over-mark", Boolean(id));
  const ranges = marksOf(id).filter((where) => where instanceof Range);
  CSS.highlights.set(HOVER, Object.assign(new Highlight(...ranges), { priority: 1 }));
}
// Coalesced to a frame: scroll outruns layout, the hit-test reads layout, and a repaint
// asks from inside a pass that must stay cheap enough to run from a mousedown.
function refreshHover() {
  if (hoverQueued || (!marked.size && !hovering)) return;
  hoverQueued = true;
  requestAnimationFrame(() => {
    hoverQueued = false;
    const id = markAt(pointer.x, pointer.y);
    if (id !== hovering) paintHover(id);
  });
}
document.addEventListener("mousemove", (ev) => {
  pointer.x = ev.clientX;
  pointer.y = ev.clientY;
  refreshHover();
});
pageScroller.addEventListener("scroll", refreshHover, { passive: true });

// ---------- selection → comment ----------
// Floating UI has to stay clear of both the banner and the comment panel, which
// covers the right of the viewport whenever it's open.
const rightEdge = () => innerWidth - (panelOpen ? panel.offsetWidth : 0) - 8;
function place(node, left, top) {
  node.style.left = Math.max(8, Math.min(left, rightEdge() - node.offsetWidth)) + "px";
  node.style.top = Math.max(48, Math.min(top, innerHeight - node.offsetHeight - 8)) + "px";
}
// The composer, which has one more thing to stay clear of: its own mark. That mark is the
// only thing naming the passage the box is about, so a box standing on all of it is a box
// about nothing. Not "no overlap" — the box has always covered the tail of a long passage
// and that reads fine — but every rect hidden is the case to move for, and it is a case
// that happens: a restored draft reappears near the top of the viewport, and the reading
// position puts the passage it was made on back in the same place.
// Below the passage where the viewport has room, above it otherwise; place()'s own clamp
// has the last word, so a passage too tall for either side simply keeps the better spot.
function placeComposer(left, top) {
  place(composer, left, top);
  const rects = pendingMarks.flatMap((where) =>
    where instanceof Range ? [...where.getClientRects()] : [where.getBoundingClientRect()],
  );
  const box = composer.getBoundingClientRect();
  // Vertically only: the document never scrolls sideways and body's margin keeps it clear
  // of the panel, so off-screen means scrolled past, and a mark scrolled past is not one
  // this box is standing on.
  const onScreen = (r) => r.bottom > 48 && r.top < innerHeight;
  const behindBox = (r) =>
    r.left >= box.left && r.right <= box.right && r.top >= box.top && r.bottom <= box.bottom;
  if (!rects.length || rects.some((r) => onScreen(r) && !behindBox(r))) return;
  const below = Math.max(...rects.map((r) => r.bottom)) + 8;
  const above = Math.min(...rects.map((r) => r.top)) - box.height - 8;
  place(composer, left, below + box.height <= innerHeight - 8 ? below : above);
}
// The anchor a selection makes: the enclosing section, and the passage as the document
// holds it. Not the selection's own toString(), which is what the reader sees rendered —
// text-transform uppercases an eyebrow or a table header, and the runtime's own chrome
// inside the passage comes along — and a quote the search can't find is no highlight while
// composing and a comment that posts permanently detached. A selection with nothing
// quotable in it yields no quote, which makes it an element anchor on its section: what
// such a selection meant anyway.
const QUOTE_CAP = 400;
const LANDMARK_CAP = 160;
// How much of a passage's surroundings an anchor writes down. Only the capture decides
// this; the search asks for whatever a given anchor happens to hold.
const CONTEXT = 24;
function selectionAnchor(sel) {
  const range = sel.getRangeAt(0);
  const node = range.commonAncestorContainer;
  const holder = node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
  const section = holder.closest("[id]:not(.cq-ui)")?.id || null;
  // The neighbours, read the same way and out of the same tree the search will read them
  // from — a context captured from anywhere else is a context the search cannot match.
  const root = searchRoot(section);
  const upto = document.createRange();
  upto.selectNodeContents(root);
  upto.setEnd(range.startContainer, range.startOffset);
  const after = document.createRange();
  after.selectNodeContents(root);
  after.setStart(range.endContainer, range.endOffset);
  const whole = quoteFrom(segmentsIn(range));
  const quote = cut(whole, 0, QUOTE_CAP);
  const prefix = cut(quoteFrom(segmentsIn(upto)), -CONTEXT, Infinity);
  const suffix = cut(quoteFrom(segmentsIn(after)), 0, CONTEXT);
  // Only what there is, and only what follows the quote. A passage filling its section has
  // no neighbours, and writing that down as two empty strings puts a field in every event
  // that never says anything. A quote cut to the cap ends inside the selection, so what
  // follows it is the rest of the selection rather than the text after it — read from there,
  // the suffix still names the place the search will look.
  // trimStart because the search reads its side through quoteFrom, which trims, and `whole`
  // is already collapsed so there is at most one space to lose. Without it, a cut landing
  // just before a space stored a suffix beginning with one — a character no occurrence can
  // produce, so every one failed at the first comparison.
  const tail =
    quote === whole ? suffix : cut(cut(whole, QUOTE_CAP, Infinity).trimStart(), 0, CONTEXT);
  return {
    section,
    quote,
    ...(prefix && { prefix }),
    ...(tail && { suffix: tail }),
  };
}

// The 💬 button carries the anchor it would open a composer on, so raising it and acting
// on it can't come to different conclusions about what the reader picked. Visibility is
// derived from that anchor and never read back off the stylesheet.
const beside = (rect) => [rect.right + 6, rect.top - 6];
let fabAnchor = null;
function showFab(anchor, left, top) {
  fabAnchor = anchor;
  fab.style.display = anchor ? "block" : "none";
  if (anchor) place(fab, left, top);
}
// The button follows the selection. What counts as one is measured on the quote it would
// store, not on the selection's own toString(): those are different strings, and gating on
// the one the reader sees while storing the one the document holds lets a two-character
// quote through behind a rendered three-character selection — a quote short enough to match
// almost anywhere.
const MIN_QUOTE = 3;
function updateFab() {
  const sel = getSelection();
  const anchor =
    sel && !sel.isCollapsed && !inUi(sel.anchorNode) ? selectionAnchor(sel) : null;
  if (anchor?.quote.length >= MIN_QUOTE)
    showFab(anchor, ...beside(sel.getRangeAt(0).getBoundingClientRect()));
  // A visual click may have just raised the button on an element anchor (its handler runs
  // before this queued update), and an element anchor has no selection to lose.
  else if (fabAnchor?.quote) showFab(null);
}
document.addEventListener("mouseup", (ev) => {
  if (inUi(ev.target)) return;
  setTimeout(updateFab);
});
// Selections made from the keyboard (shift-arrows, ⌘A) deserve the same button.
document.addEventListener("keyup", (ev) => {
  if (inUi(ev.target) || editable(ev.target)) return;
  setTimeout(updateFab);
});
document.addEventListener("mousedown", (ev) => {
  if (!ev.target.closest?.(".cq-fab, .cq-composer")) {
    showFab(null);
    // Keep a composer that holds unsent text open so a stray click can't drop it;
    // Cancel discards explicitly, and the draft is persisted regardless. Asked only of a
    // composer that is up, so an ordinary press in the page repaints nothing.
    if (composerOpen && !composerInput.value) hideComposer();
  }
  if (!ev.target.closest?.(".cq-help")) helpEl.classList.remove("open");
});

// What a click on the page means, decided once. A mark under the pointer opens its thread;
// otherwise a diagram or image — which has no text to select — raises the same 💬 button on
// an element anchor, the id the visual lives under, instead of a quote.
//
// Once, because the hit-test reads layout and opening the panel rewrites it. Two handlers
// each asking `markAt` looked independent and were not: the first one's setPanel() reflowed
// the document out from under the second, which then missed the very mark it had just
// opened and raised the comment button on top of it — leaving an element anchor set, which
// midComposition() reads, so the page quietly stopped following new versions. The rule this
// file already carries covers it: a guard that reads state another function wrote is a sign
// the two are one function.
const VISUAL = "cq-diagram, svg, img, figure";
document.addEventListener("click", (ev) => {
  if (inUi(ev.target)) return;
  const threadId = markAt(ev.clientX, ev.clientY);
  if (threadId) {
    setPanel(true);
    const thread = threadsBox.querySelector(`.cq-thread[data-id="${threadId}"]`);
    if (thread) {
      thread.scrollIntoView({ behavior: SCROLL, block: "center" });
      thread.classList.add("flash");
      setTimeout(() => thread.classList.remove("flash"), 1300);
    }
    return;
  }
  if (ev.target.closest?.("a")) return;
  let visual = ev.target.closest?.(VISUAL);
  const sel = getSelection();
  if (!visual || (sel && !sel.isCollapsed)) return; // mousedown already took the button down
  // Outermost visual: a rendered diagram's inner svg carries a generated id;
  // the anchor belongs to the widget (or figure) that holds it.
  while (visual.parentElement?.closest(VISUAL)) visual = visual.parentElement.closest(VISUAL);
  const id = visual.closest("[id]:not(.cq-ui)")?.id;
  if (!id) return;
  showFab({ section: id }, ev.clientX + 6, ev.clientY - 40);
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
    composerInput.value = seededQuote = pendingAnchor.quote;
    syncComposer();
  }
  composerSend.textContent = suggestCheck.checked ? "Suggest" : "Comment";
  composerInput.placeholder = suggestCheck.checked
    ? `Replacement text · ${SEND_KEYS}`
    : `Your comment · ${SEND_KEYS}`;
  saveComposerDraft();
};

// Whether the composer is up, and the only thing that decides it. The stylesheet renders
// this state; nothing reads it back, because the rendering has a third value the state
// doesn't — display is "" before the first open, which is neither "block" nor "none", and
// a guard testing for one of them ran on every mousedown in the page and swallowed the
// click. Painting hangs off the same call, so the mark and the box are up together.
let composerOpen = false;
function showComposer(open) {
  composerOpen = open;
  composer.style.display = open ? "block" : "none";
  // The reader's own selection is gone by now — focusing a textarea drops it — so this
  // mark is the only thing left pointing at the passage being quoted.
  paintAnchors();
}

// The quote suggestion mode auto-seeded, so reopening on a new anchor can tell
// machine seed from user text: the seed belongs to its old anchor and is dropped;
// anything the user typed or edited rides forward — never lose user text.
let seededQuote = "";
function openComposer(anchor, text, left, top, suggest = false) {
  pendingAnchor = anchor || null;
  if (composerInput.value === seededQuote) composerInput.value = "";
  seededQuote = "";
  composerInput.value = text || composerInput.value;
  suggestCheck.checked = suggest;
  suggestRow.style.display = anchor?.quote ? "flex" : "none";
  composerSend.textContent = suggest ? "Suggest" : "Comment";
  // before placing: a hidden box has no height to fit, and the pass inside this call is
  // both what decides whether the quote takes up some of that height and what records
  // where the passage is that the box has to stay off.
  showComposer(true);
  syncComposer();
  placeComposer(left, top);
  composerInput.focus();
}
// Hiding keeps the draft and closing discards it, but the mark goes down with the box
// either way: a marked passage with no composer on screen points at nothing.
const hideComposer = () => showComposer(false);
function closeComposer() {
  composerInput.value = "";
  seededQuote = "";
  suggestCheck.checked = false;
  composerSend.textContent = "Comment";
  pendingAnchor = null;
  saveDraft("composer", "");
  hideComposer();
}

// The button opens the composer where it stands, on the anchor it is carrying.
fab.onclick = () => {
  if (!fabAnchor) return;
  const anchor = fabAnchor;
  const [left, top] = [parseFloat(fab.style.left), parseFloat(fab.style.top)];
  showFab(null);
  openComposer(anchor, "", left, top);
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

// ---------- keyboard ----------
// One table drives both the dispatcher and the "?" overlay, so help can't drift
// from behavior. Rows without a key are display-only — focus-scoped (the thread's
// Enter, ⌘⏎) or dispatched before the table (Esc, the one key that crosses typing
// contexts); rows without `does` ride the previous row's label (k under "j / k").
const KEYS = [
  { key: "c", label: "c", does: "Comment on the selection — or toggle the panel", run: commentKey },
  { key: "j", label: "j / k", does: "Next / previous open thread", run: () => stepThread(1) },
  { key: "k", run: () => stepThread(-1) },
  { label: "Enter", does: "On a focused thread: write a reply" },
  { key: "d", label: "d", does: "Highlight changes since the previous version",
    run: () => diffBase && diffBtn.onclick() },
  { key: "[", label: "[ / ]", does: "Older / newer version", run: () => stepVersion(-1) },
  { key: "]", run: () => stepVersion(1) },
  { key: "?", label: "?", does: "This key reference", run: toggleHelp },
  { label: "Esc", does: "Back out one layer: help, composer, reply, panel" },
  { label: SEND_KEYS, does: "Send, in any composer" },
];

// Pages are authored documents where typing can start at any moment, so single
// keys never fire from a typing context — and a focused control that consumed
// the key (a grabbed grip's arrows) shadows the table via defaultPrevented.
// Escape alone crosses into typing context: it backs out, never eats text.
const editable = (node) =>
  Boolean(node) &&
  (node.tagName === "TEXTAREA" ||
    node.tagName === "INPUT" ||
    node.tagName === "SELECT" ||
    node.isContentEditable);
document.addEventListener("keydown", (ev) => {
  if (ev.isComposing || ev.defaultPrevented) return;
  if (ev.key === "Escape") return escapeKey();
  if (ev.metaKey || ev.ctrlKey || ev.altKey || editable(ev.target)) return;
  const bound = KEYS.find((b) => b.key === ev.key);
  if (!bound) return;
  ev.preventDefault();
  bound.run();
});

// Escape's ladder, top layer first. Backing out of a reply returns focus to its
// thread, so Esc then Enter round-trips; drafts are kept at every rung.
function escapeKey() {
  if (helpEl.classList.contains("open")) helpEl.classList.remove("open");
  else if (composerOpen) {
    hideComposer();
    showFab(null);
  } else if (editable(document.activeElement)) {
    if (!panel.contains(document.activeElement)) return; // an authored input keeps its Escape
    const thread = document.activeElement.closest(".cq-thread");
    document.activeElement.blur();
    thread?.focus();
  } else if (panelOpen) setPanel(false);
}

// c goes where commenting happens: a live selection gets the composer (what the
// floating button does), an element click's pending 💬 gets that, and otherwise
// the panel toggles — focusing the general box on open.
function commentKey() {
  updateFab(); // the selection may be newer than the mouseup that last placed the button
  if (fabAnchor) return fab.onclick();
  if (panelOpen) return setPanel(false);
  setPanel(true);
  generalInput.focus();
}

// j/k walk the open threads: panel focus and the page highlight move as a pair —
// they are two views of the same thread. Clamped at the ends, not wrapped.
function stepThread(dir) {
  if (!panelOpen) setPanel(true);
  const threads = [...threadsBox.querySelectorAll(":scope > .cq-thread")];
  if (!threads.length) return;
  const at = threads.indexOf(document.activeElement?.closest?.(".cq-thread"));
  const next =
    threads[
      at === -1
        ? dir > 0
          ? 0
          : threads.length - 1
        : Math.max(0, Math.min(threads.length - 1, at + dir))
    ];
  next.focus({ preventScroll: true });
  next.scrollIntoView({ behavior: SCROLL, block: "nearest" });
  scrollToThread(next.dataset.id);
}
threadsBox.addEventListener("keydown", (ev) => {
  if (ev.key !== "Enter" || !ev.target.classList?.contains("cq-thread")) return;
  const ta = ev.target.querySelector("textarea");
  if (ta) {
    ev.preventDefault();
    ta.focus();
  }
});

// [ and ] step versions with the picker's own pin semantics.
function stepVersion(dir) {
  const names = [...versionSelect.options].map((o) => o.value);
  const at = names.indexOf(vname(VNUM));
  const next = at === -1 ? null : names[at + dir];
  if (next) goVersion(next);
}

function toggleHelp() {
  if (helpEl.classList.contains("open")) return helpEl.classList.remove("open");
  helpEl.textContent = "";
  helpEl.append(el("div", "cq-help-title", "Keyboard reference"));
  const table = (rows) => {
    const t = document.createElement("table");
    for (const [key, does] of rows) {
      const tr = document.createElement("tr");
      const kbd = document.createElement("kbd");
      kbd.textContent = key;
      const keyCell = document.createElement("td");
      keyCell.append(kbd);
      tr.append(keyCell, el("td", "", does));
      t.append(tr);
    }
    return t;
  };
  helpEl.append(table(KEYS.filter((b) => b.does).map((b) => [b.label, b.does])));
  for (const section of helpSections)
    helpEl.append(el("h3", "", section.title), table(section.rows));
  helpEl.classList.add("open");
  helpEl.focus({ preventScroll: true });
}

// ---------- suggestions ----------
// A cq-suggestion is Claude's edit to reviewed content, offered rather than
// shipped. The widget owns one suggestion and marks its own state in the DOM;
// the banner owns the page's total, derived from that and refreshed whenever a
// widget says it changed. Accept all decides each suggestion individually, so
// the log records exactly what was consented to — accepting the rest after
// rejecting one stays honest.
// Quoted ones are exhibits: they carry no controls, so they are not the
// banner's to count nor Accept all's to decide.
const pendingSuggestions = () =>
  [...document.querySelectorAll("cq-suggestion:not([data-cq-state])")].filter(
    (suggestion) => !quoted(suggestion),
  );
function syncSuggestions() {
  const n = pendingSuggestions().length;
  acceptAllBtn.style.display = n ? "" : "none";
  acceptAllBtn.textContent = `✓ Accept all (${n})`;
}
// A decision also changes what text the page has — the retired slot leaves it
// (UNQUOTABLE) — so the marks are repainted from the same signal, and a comment
// on text the reviewer just removed says so at once rather than at the next poll.
document.addEventListener("cq-suggestions", () => {
  syncSuggestions();
  paintAnchors();
});
acceptAllBtn.onclick = async () => {
  acceptAllBtn.disabled = true;
  try {
    for (const suggestion of pendingSuggestions()) await suggestion.accept?.();
  } finally {
    acceptAllBtn.disabled = false;
    syncSuggestions();
  }
};
// Accepting the fix a comment asked for answers that comment, so the same
// gesture closes its thread: the widget names the thread, this layer owns the log.
document.addEventListener("cq-resolve", (ev) =>
  post({ kind: "resolve", parent: ev.detail.comment }),
);

// ---------- version diff ----------
// "Changes since vN": blocks (paragraphs, list items, widget items) whose text
// isn't present in the base version get a tinted marker, so re-reviewing a
// revision is cheap. Block-level and additions-only — deleted text has no home
// to mark — and data-widget bodies (diagram, diff, tree, code) are opaque to
// it. The base is the previous published version.
const DIFF_BLOCK =
  TEXT_BLOCK + ",aside,cq-option,cq-milestone,cq-event,cq-variant,cq-metric,cq-card";
// A suggestion is already its own mark, and its slots hold two versions of the
// same passage — so the diff treats the whole element as one opaque unit.
const DIFF_OPAQUE = "cq-diagram,cq-diff,cq-tree,cq-code,cq-suggestion,svg";
let diffBase = ""; // previous version's file name, set by renderVersions
let diffOn = false;
const diffMarked = [];
// A block's key is its *authored* text, read the same way a quote is (see GENERATED).
const blockKey = (b) => quoteFrom(textNodesUnder(b, GENERATED));
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
  // Container widgets surface marks their panels hide (cq-tabs badges each tab).
  document.dispatchEvent(new CustomEvent("cq-diff"));
  return diffMarked.length;
}
function clearDiff() {
  for (const b of diffMarked) b.classList.remove("cq-ins-block");
  diffMarked.length = 0;
  diffOn = false;
  diffBtn.classList.remove("on");
  document.dispatchEvent(new CustomEvent("cq-diff"));
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
// "Claude is working" is a claim in status.json, and nothing revises a claim once the
// session behind it walks away — so a page nobody is watching reads exactly like a page
// whose reviewer has said nothing yet. The banner asks whether anyone is attending, and
// only two things answer yes: Claude is credibly busy, or a `wait` is live. Everything
// else is absence, where the reason and the remedy are all that vary.
const HANDOFF_GRACE_MS = 2 * 60 * 1000;
const WORKING_GRACE_MS = 15 * 60 * 1000;
function renderStatus(state) {
  const { status, listening, pending, session_alive } = state;
  // The one hard fact here is the owning process. Unknown counts as alive: a page
  // nothing claimed (interact.py run outside Claude Code) isn't an abandoned one.
  const alive = session_alive !== false;
  // How long the claim has gone unrefreshed. The rope is short for the status `wait`
  // writes as it delivers, because Claude's first act on waking is its own `status` —
  // that mark outliving minutes is a dropped pickup, not a long turn.
  const grace = status.handoff ? HANDOFF_GRACE_MS : WORKING_GRACE_MS;
  const quiet = Boolean(status.ts) && Date.now() - new Date(status.ts).getTime() > grace;
  let cls = "away",
    text = "",
    showAge = false;
  if (status.state === "idle") {
    cls = "";
    text = "Review closed";
  } else if (alive && status.state === "working" && !quiet) {
    cls = "working";
    showAge = Boolean(status.ts);
    text = `Claude is working${status.detail ? " — " + status.detail : ""}`;
  } else if (alive && listening) {
    cls = "listening";
    text = "Claude is listening — select text to comment";
  } else {
    // Nobody is attending: say why, what's waiting, and what to do. A dead session is
    // never coming back, a recent check-in means Claude is mid-turn, and a long silence
    // means it lost the thread.
    const [why, how] = !alive
      ? [
          "The Claude session reviewing this page has ended.",
          "Start one in the terminal to pick it up.",
        ]
      : quiet
        ? [`Claude last checked in ${ago(status.ts)}.`, "Nudge it in the terminal."]
        : ["Claude isn't watching right now.", "It picks them up next turn."];
    // Comments land in the append-only log either way; what changes is when they're read.
    const held = pending
      ? `${pending} comment${pending === 1 ? "" : "s"} waiting.`
      : "Your comments are saved.";
    text = `${why} ${held} ${how}`;
  }
  dot.className = "cq-dot " + cls;
  statusText.textContent = "";
  statusText.append(document.createTextNode(text));
  if (showAge)
    statusText.append(
      " ",
      Object.assign(el("span", "cq-age"), { textContent: `(${ago(status.ts)})` }),
    );
}

const vname = (n) => `v${String(n).padStart(3, "0")}.html`;
// Navigate to a version with the pin semantics every chooser shares: an older
// version pins the view, the newest unpins it.
const goVersion = (name) => {
  location.href = name === latestName ? `/versions/${name}` : `/versions/${name}?pin`;
};
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
    versionSelect.value = vname(VNUM);
  }
  latestName = state.versions.at(-1) || "";
  const behind = latestName && VNUM !== null && latestName !== vname(VNUM);
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
  const idx = state.versions.indexOf(vname(VNUM));
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
  composerOpen ||
  Boolean(fabAnchor) ||
  Boolean(document.querySelector(".cq-dragging")) ||
  (document.activeElement?.tagName === "TEXTAREA" && document.activeElement.value !== "");
versionSelect.onchange = () => goVersion(versionSelect.value);
latestChip.onclick = () => (location.href = "/");

// ---------- polling ----------
// Rendering version V shows V plus the actions recorded against it, replayed in
// seq order: a reload keeps the reviewer's drag, a second tab follows along
// live, and a pinned older version shows what the reviewer did while on it.
// Widgets opt in by exposing applyAction(action, detail) — an absolute
// placement, so replaying the sender's own action is a no-op. The first poll
// runs after upgrades settle, so the methods exist, and the pass runs at the end
// of a poll, so the panel's own widgets do too.
const appliedActions = new Set();
const lastActionByWidget = new Map();
let cursor = 0; // what `wait` has delivered to Claude, from /api/state
function applyActions() {
  // Never mutate the page under a live gesture — a replayed foreign action could
  // move the nodes a drag preview is holding. Retry next poll.
  if (document.querySelector(".cq-dragging")) return;
  let applied = false;
  for (const e of events) {
    if (e.kind !== "action" || appliedActions.has(e.seq)) continue;
    // Every action is decided here and never looked at again. This pass runs after
    // the panel has rendered the log, so every widget that will ever exist is on the
    // page: one that isn't is one no version can carry — an honored suggestion, whose
    // markup and id the honoring version replaced. Retrying instead meant looking a
    // vanished element up every two seconds for as long as the page stayed open.
    appliedActions.add(e.seq);
    const el = document.getElementById(e.widget);
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
    )
      continue;
    // A foreign action older than one this tab already applied to the widget
    // would yank it backwards — skip it. Two tabs editing one widget in the same
    // poll window can diverge until a reload or the honoring version; the log
    // stays canonical either way.
    if (e.seq < (lastActionByWidget.get(e.widget) ?? 0)) continue;
    lastActionByWidget.set(e.widget, e.seq);
    el.applyAction(e.action, e.detail);
    applied = true;
  }
  // A replay moves the page's text — a card to another column, a suggestion to its
  // settled slot — so the marks are repainted where they now belong. Said here rather
  // than left to the caller's order: a pass held off by a live drag lands on a poll
  // that has nothing else to re-render.
  if (applied) paintAnchors();
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
  // Last, because the panel has just rendered the log: a widget carried by a reply is
  // on the page by now, so an action naming one that isn't names a widget no version
  // holds, and applyActions can retire it instead of looking for it forever.
  applyActions();
}
// ---------- restore ----------
// The general box and reply textareas repopulate as they render; a saved composer draft
// resurfaces visibly near the top so it isn't stranded in storage after a reload.
generalInput.value = loadDraft("general");
try {
  if (localStorage.getItem(PANEL_KEY) === "1") setPanel(true);
} catch {}
// Carry the reading position across every arrival — version switch, reload, back
// (the panel is restored just above, so the column is already reflowed). The
// browser's own restoration is taken over entirely: upgrades change the page's
// height after it runs (tabs collapse, diagrams render, diff files fold), so its
// offsets go stale; the landmark is re-found once geometry has settled instead.
history.scrollRestoration = "manual";
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
  syncSuggestions();
  if (savedView) {
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
