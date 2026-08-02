/* Colloquy runtime, loaded via <script type="module" src="/colloquy.js">: one module
 * owning both the widget layer and the comment layer.
 *
 * Widget layer: reads /registry.json (vendored per page) and dynamically imports one
 * module per tag marked x-upgrade — element-widgets need no JS at all; the theme's CSS
 * renders them. It also renders the attributes the registry marks x-says as real text
 * (renderSaid), for every widget alike: a word the page says has to be a word the
 * reviewer can select. Upgrades flush before the first anchor pass, so comment quotes
 * always search the enhanced DOM. Widget modules import only the small helper surface
 * they need from here.
 *
 * Actions: an interactive widget (cq-board) reports the user editing the document
 * through it as an `action` event — sendAction posts it, `review wait` prints it, and
 * `review ack` records that the complete wait batch reached model context. The live
 * view is the version plus every action recorded up to it, replayed on each poll:
 * authored markup is what a widget was before anyone touched it, the log is every
 * transition since, and the log wins. A decision therefore outlives the version it
 * was made on, without the page's author having to copy it into the next one by
 * hand. When a version does mean to overrule one — the content the decision was
 * about got rewritten — `version check` makes the author say so (see restatement_errors in
 * interact.py); it is never inferred from the markup's silence. Widgets opt in via an
 * applyAction(action, detail) method stating an absolute value, so a reload keeps the
 * reviewer's drag and a second tab follows along live.
 *
 * Comment layer: talks to interact.py's server — polls GET /api/state, posts events to
 * POST /api/event. Everything it injects is namespaced .cq-* and marked .cq-ui, and it
 * styles itself from the theme's tokens so it themes with the page.
 *
 * .cq-ui is the chrome face — the system-ui look that says "this is not the document" —
 * and it is anchoring's answer only where nothing nearer speaks. A label the widget
 * declares the page's own words (relabel's data-cq-said) is nearer, and wins: a heading
 * in a chrome-looking row and a tab's name inside its own strip button are both passages
 * a reviewer can point at. Reading the class as the whole answer is what left a reviewer
 * able to see a draft's heading and unable to comment on it. A widget's own label, note
 * or badge outside any control declares nothing at all: data-cq-gen alone keeps it out of
 * the diff and in reach of the anchor pass. CLAUDE.md carries why.
 *
 * Paper reads both: a control a widget injected (data-cq-offer) has nothing on paper to
 * be pressed, so it goes, unless its own label is one of the page's words. Keying print
 * on .cq-ui instead cost a printed decision the only words that stated it (see
 * CLAUDE.md), because a pick mark is a control and a statement at once. render_version
 * compares the two media and reports what a page says on screen and not on paper.
 *
 * A control that says one of the page's words is never a <button>: Chrome starts no
 * pointer selection inside a form control, so its label would be unreachable however it is
 * marked. `offer` builds every press as a span wearing role="button" for that reason, and
 * wires the keys the UA would have given it.
 *
 * Passages and anchors: a comment points at an anchor (a section id, a quote, and the
 * neighbouring words where there are any). resolveAnchor is the only place the page is
 * searched and paintAnchors the only place it is marked; CLAUDE.md carries why.
 *
 * Never lose user text (CLAUDE.md): every unsent draft — the general box, each per-thread
 * reply, the selection composer (text + its anchor), and an in-place draft edit —
 * persists to sessionStorage on input. It survives reload and version navigation but is
 * owned by one tab, so a send or Cancel in another tab cannot erase newer unsent words.
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
 * flashes a scrollbar per keystroke. The thread list is reconciled, never rebuilt: a
 * poll adds what arrived and touches nothing the reviewer already holds, so scroll,
 * focus and caret keep themselves because the nodes holding them survive. News moves
 * nothing; a send reveals the message it just landed — the panel scrolls to it and
 * flashes its thread, the same answer a click on a page mark gets — and ends in the
 * composer it was sent from. A composer open on a selection keeps that passage marked
 * in the page until it closes, because focusing the box drops the browser's own
 * selection — and that mark is what says which passage the box is on, so the box only
 * quotes the passage back when this version no longer has one to mark. Whether the box
 * is up is state the stylesheet renders, never state read back off the stylesheet.
 *
 * Scrolling: the document scrolls body, not the viewport, and body's margin keeps its
 * box clear of the open panel. Two scroll regions side by side, each scrollbar drawn
 * inside its own region — a viewport-scrolled document would paint its scrollbar over
 * the panel, stacked on the panel's own. Reading position goes through pageScroller.
 * The browser's own scroll keys are left alone (Space, arrows, Home/End, PageUp/Down);
 * d and u are the runtime's, stepping half a page through whichever of the two regions
 * the reader's own scrolling moves, and carrying a destination so repeats add up.
 *
 * Keyboard: two scopes, matching the DOM's own. One dispatcher drives a table of
 * global single-key shortcuts (KEYS — also the source of the "?" overlay, so help
 * can't drift from behavior); it skips typing contexts (editable target, ⌘/Ctrl/Alt,
 * IME) and anything a focused control already consumed (defaultPrevented), which is
 * how a widget's own keys shadow the table. Focus-scoped keys belong to the focused
 * control itself — panel threads here, grips and pick buttons in widget modules —
 * with no registration: the keyboard exports widgets need are announce() (the live
 * region), keyHelp() (reference rows for the overlay), and keyHint() (what keys mean
 * on a control right now). One sequence exists: g arms a short leader window in
 * which a digit addresses the nth open thread's reply box — the address each box
 * wears as a chip while the window is armed and its placeholder speaks always — and
 * any other key disarms the window and keeps its ordinary meaning. Escape alone
 * crosses into typing context, backing out one layer per press without ever eating
 * text.
 *
 * What a key would do right now is state the reviewer can read, not recall: scene()
 * derives the current scope from the state that already exists (the leader, the
 * overlay, the composer, focus, the panel) and is the one definition of Escape's
 * ladder — escapeKey() runs the rung scene() returns, and the key line (one quiet
 * fixed line, bottom left) renders the same object, so what Esc promises and what it
 * does cannot drift. The line is aria-hidden: it is the eye's copy of facts spoken
 * elsewhere — placeholders speak each box's address, announce() speaks the leader
 * arming, the "?" overlay speaks the whole reference. A control that shows its own
 * esc row in the line must consume Escape (preventDefault), or the line would
 * promise one action over a press that performs two.
 *
 * A message arrives as logged and renders here, in the same vendored layer that owns
 * the panel's styles — the two version together, and no wire vocabulary exists beyond
 * the log's own. Its text is Markdown, rendered with every raw tag escaped to the
 * characters it was written in, so prose that says `Vec<T>` keeps its own words and
 * text cannot inject markup. A widget rides the event's `markup` field instead, whose
 * one door is the CLI gate (`review comment`/`review reply` validate it against the
 * vendored registry; the browser door refuses the field), so what lands here is
 * injected as validated. A suggestion's text renders verbatim: its characters are
 * bound for the page as typed. */

// ---------- widget layer ----------

let agent = "Claude";
export const agentName = () => agent;

// Attributes the runtime itself may paint onto elements the page owns. This is the
// replay signature's one exclusion vocabulary as well as the source each writer uses:
// a new kind of paint therefore has one place to join. The rest of data-cq-* is not
// implicitly ours — a widget can carry real state there, and replay must see it.
const PAGE_PAINT_ATTRIBUTE = Object.freeze({
  class: "class",
  done: "data-cq-done",
  restated: "data-cq-restated",
  replayWrote: "data-cq-replay-wrote",
  applied: "data-cq-applied",
  pending: "data-cq-pending",
  upgraded: "data-cq-upgraded",
});
const PAGE_PAINT_ATTRIBUTES = new Set(Object.values(PAGE_PAINT_ATTRIBUTE));

// One-shot guard for connectedCallback: re-connection (a parent wrapping or moving an
// already-upgraded child) must be harmless, so upgrade order can't matter.
export function once(el) {
  if (el.hasAttribute(PAGE_PAINT_ATTRIBUTE.done)) return false;
  el.setAttribute(PAGE_PAINT_ATTRIBUTE.done, "1");
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

// ---------- syntax ----------
// Code is colored in the browser, at upgrade, and the spans land in the DOM — which is
// what makes one answer serve the served page and the standalone one, where the script
// is gone and only markup and CSS remain. Colouring it in Python instead would put the
// spans in the file, and the file is what Claude writes the next version from.
//
// What a page ends up wearing is colloquy's own vocabulary, not the tokenizer's: six
// roles on one data-cq-syn attribute, styled from --syn-* like every other surface, so
// both color schemes come from the same token block the rest of the theme uses. The
// bundle's ~50 scopes collapse here, at the one place that knows both — a page that
// carried hljs-* classes would have pinned that library into every version ever written.
// Anything unmapped keeps the block's ink, so a scope this table forgets reads plain
// rather than reading wrong.
// Every key is a scope one of the bundled grammars actually emits; operator, punctuation,
// emphasis and strong are left out on purpose, because a block reads calmer with its
// syntax uncoloured and its prose unstyled.
// A line per role rather than per scope, so the collapse is what the table shows.
// prettier-ignore
const SYNTAX_ROLE = {
  comment: "cm", quote: "cm", doctag: "cm",
  keyword: "kw", literal: "kw", built_in: "kw", type: "kw", bullet: "kw",
  string: "st", regexp: "st", "char": "st", subst: "st", "template-variable": "st",
  code: "st", link: "st",
  number: "nu",
  title: "fn", meta: "fn", section: "fn",
  name: "ty", tag: "ty", attr: "ty", attribute: "ty", property: "ty", variable: "ty",
  params: "ty", symbol: "ty", "selector-tag": "ty", "selector-id": "ty",
  "selector-class": "ty", "selector-attr": "ty", "selector-pseudo": "ty",
  addition: "ins", deletion: "del",
};

let hljsReady;
// Lazily, once, and only on a page that has code to color: the bundle is 75 KB and most
// pages have none.
const loadHljs = () =>
  (hljsReady ??= import("/vendor/highlight.esm.js").then((m) => m.default));

// Code as [{text, role}] — a flat run in source order, roles from the table above and
// null where the block's own ink is the answer. A list rather than markup because the two
// callers build different DOM from it: a plain <pre> emits one span per token, cq-code
// interleaves the line spans it numbers. A declared language is validated by `version check` against the
// registry's $languages.names, so an unknown one here means the vendored bundle was built
// from a different list — thrown, caught by the caller's failSoft, and reported by the
// render gate, which fails on a console error.
export async function syntax(source, lang) {
  const hljs = await loadHljs();
  if (!hljs.getLanguage(lang))
    throw new Error(
      `no ${lang} in /vendor/highlight.esm.js — rebuild it from registry.json's $languages.names`,
    );
  const holder = document.createElement("template");
  holder.innerHTML = hljs.highlight(source, {
    language: lang,
    ignoreIllegals: true,
  }).value;
  const tokens = [];
  const walk = (node, role) => {
    for (const child of node.childNodes) {
      if (child.nodeType === Node.TEXT_NODE) tokens.push({ text: child.data, role });
      // Scopes nest (an html tag holds its own name and attrs); the innermost that this
      // table knows wins, and one it doesn't inherits rather than clearing.
      else walk(child, roleOf(child) ?? role);
    }
  };
  walk(holder.content, null);
  // The vendored tokenizer's output is data entering, so it is checked once, here, and
  // indexed everywhere after: that the tokens partition the source exactly. Three things
  // rest on it — cq-code numbers its lines by counting newlines in them, `hi` and each
  // note's `at` address those numbers, and the anchor pass reads the spans as the text
  // the file holds — and a dropped character slides all three with nothing on screen
  // saying so. Failing here fails the block soft to its plain source, and the console
  // error fails the render gate, which is what puts it in front of whoever can drop the
  // language declaration.
  if (tokens.map((t) => t.text).join("") !== source)
    throw new Error(`the ${lang} tokenizer did not return the source unchanged`);
  return tokens;
}

// hljs writes `class="hljs-title function_"`: the scope prefixed, then its sub-scopes bare.
// Only the prefixed one is a scope name, and `char.escape` arrives as `hljs-char escape_`.
const roleOf = (el) => {
  for (const cls of el.classList)
    if (cls.startsWith("hljs-")) return SYNTAX_ROLE[cls.slice(5)];
  return undefined;
};

// Tokens as nodes: one span per role, and the bare text where none applies, so nothing
// lands in the DOM that says nothing. Both callers build from here — a <pre> replacing its
// own children, cq-code appending into the line it is numbering — because a second place
// writing the same span is a second place to forget the attribute.
export const synNodes = (tokens) =>
  tokens.map(({ text, role }) => {
    if (!role) return document.createTextNode(text);
    const span = document.createElement("span");
    span.dataset.cqSyn = role;
    span.textContent = text;
    return span;
  });

// Tokens re-cut so none crosses a newline: one array of {text, role} per line, in source
// order. The tokenizer's runs and a line are two different spans of the same characters,
// and this is where they are reconciled — for cq-code, whose lines are what it numbers,
// and for cq-diff, whose lines are what it tints. Both tokenize a whole run and cut it
// afterwards rather than colouring a line at a time, because a token can span a newline:
// a docstring coloured line by line restarts the tokenizer inside itself and reads its
// second line as code.
export function tokenLines(tokens) {
  const lines = [[]];
  for (const { text, role } of tokens) {
    const parts = text.split("\n");
    parts.forEach((part, i) => {
      if (i) lines.push([]);
      if (part) lines.at(-1).push({ text: part, role });
    });
  }
  return lines;
}

// What a filename says it holds, or undefined where the registry's table has no answer
// and the block stays the colour of its own ink. The only place a language is derived
// rather than declared: a unified diff spans files, so cq-diff has no `language` to read and
// each file's path is the diff's own statement about what it is. Still a declaration —
// the rule that nothing is inferred is about source *text*, which no path is. The table
// is the registry's ($languages), beside the enum it has to agree with, rather than a
// second list here.
export const langForPath = (path) =>
  registry.$languages.paths[
    path.split("/").pop().split(".").slice(1).pop()?.toLowerCase()
  ];

// The page's own code blocks: <pre><code class="language-python">. The class is the
// universal one — what every Markdown renderer emits, and what `version check` validates — so a
// block Claude wrote anywhere else needs no translation to land here. cq-code declares
// `language` instead, because a custom element's vocabulary is the registry's to state.
//
// The spans change no text: a <span> is no text block, so the anchor pass reads exactly
// the run of characters it read before. That is what lets this run over the document
// without the file's reading of the same page needing to know it happened.
const LANGUAGE_CLASS = /(?:^|\s)language-([\w+.#-]+)(?=\s|$)/;
async function highlightBlocks(root) {
  const blocks = [];
  for (const code of root.querySelectorAll("pre > code[class]")) {
    const lang = code.className.match(LANGUAGE_CLASS)?.[1];
    if (lang) blocks.push([code, lang]);
  }
  if (!blocks.length) return;
  for (const [code, lang] of blocks) {
    try {
      code.replaceChildren(...synNodes(await syntax(code.textContent, lang)));
    } catch (err) {
      console.error(
        `colloquy: <pre><code class="language-${lang}"> failed to highlight`,
        err,
      );
    }
  }
}

// The theme's reduced-motion guard covers CSS animation and transitions; motion
// driven from JS — smooth scrolls here, Web-Animations moves in widgets — checks
// this instead.
export const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
export const SCROLL = REDUCED ? "instant" : "smooth";

// Mention, not use: a widget inside one the registry marks x-exhibit is quoted
// material. An interactive widget consults this before wiring anything that would carry
// input back (a choose path, a drag grip), so an exhibit never takes the reader's edits.
// Presentational upgrades and view state run regardless — a quoted diagram still
// renders, a quoted settled group still collapses.
export function quoted(el) {
  const exhibits = tagsDeclaring((entry) => entry["x-exhibit"]);
  return exhibits.length > 0 && el.closest(exhibits.join(",")) !== null;
}

// The chrome a widget injects: a control, or the box that holds controls. Three
// markers, one per question asked of it — `cq-ui` for the runtime's look, which
// anchoring reads where no label speaks nearer; `data-cq-gen` so the diff looks away; `data-cq-offer`
// for a thing to work, which paper drops because there is nothing there to press.
// A widget writes none of the three by hand: they are what make an element chrome,
// and one of them going missing is invisible until something breaks.
//
// "button" names a thing to press, not the element. A real <button> is a wall a
// pointer's selection cannot cross — Chrome starts no selection inside a form
// control and `user-select: text` does not move it — so any word inside one is
// unreachable to a reviewer whatever it is marked, and a control's label turns out
// to be one of the page's own words often enough (a tab's name, the card a settled
// group carries, the mark on a chosen option) that a widget cannot be trusted to
// have picked the element with that in mind. So a press is a span wearing the role,
// and the keys the UA would have supplied are wired once below. Nothing these controls
// do needed the element: no forms, no submit, and no `disabled` — which a widget's press
// therefore cannot have (the .cq-btn:disabled rule is the runtime's own buttons').
export function offer(tag, cls, label) {
  const press = tag === "button";
  const node = document.createElement(press ? "span" : tag);
  if (press) {
    node.setAttribute("role", "button");
    node.tabIndex = 0; // and the tabindex attribute is what says "a press" below
  }
  node.className = cls ? `${cls} cq-ui` : "cq-ui";
  node.dataset.cqGen = "1";
  node.dataset.cqOffer = "";
  if (label !== undefined) node.textContent = label;
  return node;
}

// The keys a <button> came with and a span does not: Enter and Space activate. One
// listener rather than one per press, and on the bubble, so a control that handles the
// key itself has already said so by preventing the default — cq-board's grip grabs on
// Enter, and a press that also clicked would be the runtime overruling the focused
// control, which is the opposite of the rule widgets keep (CLAUDE.md: focus-scoped keys
// belong to the focused control). A held key repeats keydown where a real button fired
// once, and a pick mark toggling per repeat posts a `choose` per repeat.
document.addEventListener("keydown", (ev) => {
  if (ev.key !== "Enter" && ev.key !== " ") return;
  if (ev.defaultPrevented || ev.repeat) return;
  if (!ev.target?.matches?.("[data-cq-offer][tabindex]")) return;
  ev.preventDefault(); // Space would scroll the page out from under the press
  ev.target.click();
});

// A drag that ends on a control is that selection's mouseup, not a press: the
// reviewer was reaching for the words, and a control whose label is one of the
// page's own words is exactly where they reach. Here rather than in each widget,
// because `offer` is what made the thing pressable — the same reason the markers
// live there. A keyboard activation (detail 0) is never a drag.
//
// The question is whether *this* click's mouseup is where the selection stopped, so
// it reads the selection's focus end — the character the pointer was on when the
// button came up. Asking instead whether the selection contains the control is a
// question about the DOM, and it answers yes for any selection running over the
// control: a suggestion's row is the column's own child, in flow between the block
// holding the change and the next one, so a reviewer who read across the change and
// then reached for Accept pressed a control that had gone dead — and stayed dead,
// because a press that refuses a drag (`user-select: none`) never collapses the
// selection that deadened it either.
document.addEventListener(
  "click",
  (ev) => {
    if (ev.detail === 0) return;
    const control = ev.target.closest?.("[data-cq-offer]");
    const sel = getSelection();
    if (control && sel && !sel.isCollapsed && control.contains(sel.focusNode)) {
      ev.stopPropagation();
      ev.preventDefault();
    }
  },
  true,
);

// A control's label, and which kind of word it is. Most are things to do — "Save",
// "choose", a grip — and go with the rest of the UI on paper, out of reach of a
// quote. Some are the page speaking: a pick mark reading "chosen" is the only place
// the page says which option it carries, and a tab's name is the panel's only name
// once the strip exists. One element wears both over its life, so the kind is
// restated on every write rather than settled at birth.
//
// This writes one marker and one only: data-cq-said, the page speaking. Anchoring
// takes it over the `.cq-ui` box around it — that box is a look, the chrome face, and
// it was standing in for a permission the reviewer has no category for — and paper
// reads it beside data-cq-offer to keep a control whose label is one of the page's own
// words. data-cq-gen goes on either way, because the diff parses the base version
// unupgraded and would read any label as text that version lacked.
//
// It leaves data-cq-offer alone, which it used to clear. That attribute is what `offer`
// made: this is a control a widget injected, true for the mark's whole life however it
// is worded, and three passes ask it (print, the drag guard above, the render gate).
// Clearing it here made "paper drops this" the meaning and left the other two unable to
// see a control — a drag across a picked card's mark was a press again, and only
// cq-options' own guard on the card stood between that and clearing the pick.
//
// `says` has no default, because the answer a caller doesn't give is the one that
// costs a printed page its words, and silently. Refusing throws where the widget
// upgrades, which the console reports and the render gate reads back as a finding
// — the loud direction, in front of whoever wrote the label.
export function relabel(node, label, { says } = {}) {
  if (typeof says !== "boolean")
    throw new TypeError(
      `relabel(${label}): say whether this label is the page speaking`,
    );
  node.textContent = label;
  node.dataset.cqGen = "1";
  node.toggleAttribute("data-cq-said", says);
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

// A widget's box for words. A page can ask a question its options don't cover the
// answer to — "none of these", or a pick's why — and the reader needs somewhere to
// put that without going hunting for a passage to select. What they type goes back as
// an ordinary comment anchored on the widget, so it is a thread beside the question:
// replied to in place, resolved like any other, and in the transcript with everything
// else they said. One store, one channel; the placement of the *reply* is the open
// question (TODO.md), and it is a question about where a thread renders, not about
// where the words live.
//
// Built here rather than in each widget, because everything that makes it safe is the
// comment layer's: the draft written on each keystroke and cleared only by a
// successful send, one send per click, ⌘⏎. A widget says where the box goes and what
// it invites; nothing else.
export function sayBox(el, hint) {
  const row = offer("div", "cq-say");
  const ta = offer("textarea");
  const send = offer("button", "cq-btn primary", "Send");
  const ctx = "say:" + el.id;
  ta.value = loadDraft(ctx);
  ta.setAttribute("aria-label", hint);
  row.append(ta, send);
  const sync = wireInput(ta, {
    hint,
    sendBtn: send,
    save: (v) => saveDraft(ctx, v),
    send: async (text) => {
      if (
        !(await post({
          kind: "comment",
          version: VNUM,
          anchor: { section: el.id },
          text,
        }))
      )
        return;
      saveDraft(ctx, "");
      ta.value = "";
      sync();
      showToast(`Sent to ${agent}`);
    },
  });
  sync();
  return row;
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
const helpSections = new Map();
export function keyHelp(title, rows) {
  const key = JSON.stringify([title, rows]);
  helpSections.set(key, { title, rows });
}

// What keys mean on this control right now — the key line renders these rows while
// focus is inside `el` (innermost declaring ancestor wins), instead of the scope's
// own. keyHelp answers "what could I do here"; this answers "what will this press
// do", so a control whose keys change with its state re-declares on each change (a
// grip on grab and on drop) and the call repaints the line itself — a grab is Enter
// on an already-focused grip, so no focus event would. Two rules keep the promise
// honest: a rows entry whose key cell reads "esc" (any case) replaces the ladder's
// esc chip, and a control declaring one must consume Escape (preventDefault) — the
// line would otherwise promise one action over a press that performs two. Pass null
// to withdraw.
const hintRows = new WeakMap();
export function keyHint(el, rows) {
  if (rows) hintRows.set(el, rows);
  else hintRows.delete(el);
  paintLine();
}
function hintFor(node) {
  for (let a = node; a; a = a.parentElement) {
    const rows = hintRows.get(a);
    if (rows) return rows;
  }
  return null;
}
// Whether the focused control has claimed Escape for itself — the declared half of
// keyHint's contract, read wherever the runtime must not promise a second meaning
// for the same press.
const claimsEsc = (node) =>
  Boolean(hintFor(node)?.some(([key]) => key.toLowerCase() === "esc"));

// How a widget collapses content it may need to show again (cq-tabs' inactive
// panels, a settled cq-options' cards): hidden="until-found", so find-in-page
// and fragment navigation still reach it — `beforematch` fires and the widget
// reopens what it owns. It is only a hide where the UA supports it (it rides
// content-visibility, and the theme's display:block outranks the boolean
// [hidden] rule) — without beforematch, fall back to plain boolean hidden,
// which the theme hides itself; the widget still collapses and reopens, ⌘F
// just can't see in.
export const HIDDEN = "onbeforematch" in document.body ? "until-found" : "";

// A scroll target can sit inside a collapsed container — a closed <details>, an
// inactive tab. Opening what the platform owns (details) and letting a container
// widget open what it owns (the cq-reveal event; cq-tabs listens) gives the
// target geometry before the scroll. Called before every scroll-to-content.
function reveal(el) {
  for (let a = el; a; a = a.parentElement) {
    if (a.tagName === "DETAILS" && !a.open) a.open = true;
    if (a.hidden) a.dispatchEvent(new CustomEvent("cq-reveal"));
  }
}

// The vocabulary, vendored per page: which tags a module upgrades, and which of their
// attributes are words the page says (see renderSaid). Empty only during the real
// fetch interval, when the already-wired chrome can legitimately be used; a failed
// fetch still rejects startup rather than becoming an empty vocabulary.
let registry = {};
let anchoringReady = false;
// The file-side passage reader fences an upgraded element and each of its original
// direct children when the registry cannot promise its body is verbatim. Remember
// those parts before custom-element definitions can add or move anything, so the
// browser can stop captured context at the same seams after every upgrade has run.
const opaquePassageRoots = new WeakSet();
const opaquePassageParts = new WeakSet();

// Which widgets answer a question the way the caller means it, read from what they
// declare. Nothing out here names a widget: a behaviour some widgets want is an x- key
// they carry, so the twelfth widget is covered by its entry alone — the alternative
// keeps working perfectly on the widget it was taught and silently does nothing for the
// next one.
const tagsDeclaring = (holds) =>
  Object.entries(registry)
    .filter(([tag, entry]) => tag.startsWith("cq-") && holds(entry))
    .map(([tag]) => tag);

function rememberPassageParts() {
  for (const tag of tagsDeclaring(
    (entry) => entry["x-upgrade"] && !entry["x-verbatim"],
  ))
    for (const root of document.querySelectorAll(tag)) {
      opaquePassageRoots.add(root);
      for (const child of root.children) opaquePassageParts.add(child);
    }
}

async function upgradeWidgets() {
  const response = await fetch("/registry.json");
  if (!response.ok)
    throw new Error(`colloquy: registry failed to load (${response.status})`);
  registry = await response.json();
  if (
    !registry.$events?.kinds ||
    !registry.$languages?.names ||
    !registry.$languages?.paths ||
    !registry.$tones?.names
  )
    throw new Error("colloquy: registry lacks $events, $languages or $tones");
  rememberPassageParts();
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
  // The page's own <pre><code> blocks, alongside the widgets and for the same reason: the
  // tokenizer is vendored, so a page has it exactly when it has a widget layer at all.
  settle(highlightBlocks(document.body));
  // Importing defined the elements and ran their connectedCallbacks; async ones
  // registered their work via settle(). Wait it out so geometry is final.
  await Promise.allSettled(settling);
  // After the wait, because the box a widget scrolls is a box its module built: run this
  // with the rest of the upgrade and a diff's pre and a code block's are half there.
  reachScrollers(document.body);
}

// Words a widget says through an attribute — a metric's number, an event's time, an
// option's chip band — rendered as text the reviewer can reach. The theme renders the same
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
//
// data-cq-said names the attribute here and stands bare on a label relabel wrote, because
// the two are one claim — these words are the page's, whoever rendered them. The anchor
// pass reads the marker alone; the value is for whoever means one attribute in
// particular, which is this pass (so it writes no second span over its own) and the
// theme, whose every rule names the attribute it styles rather than matching the bare
// marker.
function renderSaid(root) {
  for (const [tag, entry] of Object.entries(registry)) {
    if (!entry["x-says"]) continue;
    for (const el of root.querySelectorAll(tag))
      for (const [attr, edge] of Object.entries(entry["x-says"])) {
        const text = el.getAttribute(attr);
        if (text === null || el.querySelector(`:scope > [data-cq-said="${attr}"]`))
          continue;
        const span = document.createElement("span");
        span.dataset.cqSaid = attr;
        span.dataset.cqGen = "1";
        span.textContent = text;
        // At the edge of the element's own words rather than of the element, which are the
        // same place on a page carrying no script and not once a module has injected
        // chrome of its own. These are the page speaking, so they belong beside the page's
        // other words: an option's risk chip landed past the pick mark that ends a compact
        // row — outside the apparatus the row runs to its line's end, and on the far side
        // of it from where the file's reading of that same version has it.
        const own = [...el.childNodes].filter(
          (n) => !(n.nodeType === 1 && n.dataset.cqGen),
        );
        el.insertBefore(
          span,
          (edge === "before" ? own[0] : own.at(-1)?.nextSibling) ?? null,
        );
      }
  }
}

// Anything a mouse can scroll, a keyboard can reach. A `pre` too wide for the column
// scrolls, and a reviewer working from the keyboard had no way at all to the half of the
// line off the right of it — which is a phone's every code block, since the column there
// is 372px and a line of code is not. Asked of the computed overflow rather than of a list
// of tags, so a widget that scrolls is covered by scrolling and the twelfth one needs no
// entry, and it reaches the runtime's own boxes on the same terms as the page's. Asked of
// the content first, because a box holding a control of its own is already reachable
// (cq-board, through its grips) and a tab stop over the whole board would stand between
// the reviewer and the card they were tabbing to.
const FOCUSABLE =
  'a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"])';
function reachScrollers(root) {
  for (const el of root.querySelectorAll("*")) {
    if (el.tabIndex >= 0) continue;
    const style = getComputedStyle(el);
    if (
      !/^(auto|scroll)$/.test(style.overflowX) &&
      !/^(auto|scroll)$/.test(style.overflowY)
    )
      continue;
    if (!el.querySelector(FOCUSABLE)) el.tabIndex = 0;
  }
}

// ---------- comment layer ----------

const VERSION_MATCH = location.pathname.match(/\/versions\/v([1-9]\d*)\.html$/);
const VNUM = VERSION_MATCH ? parseInt(VERSION_MATCH[1], 10) : null;
const PINNED = new URLSearchParams(location.search).has("pin");
// Sign-off is the page's ask, not standing chrome: the approve button exists only
// when the version declares <meta name="cq-review" content="sign-off"> — a plan or
// proposed change seeking assent. An informational page takes comments only. The
// declaration rides the document, so a pinned older version keeps its own ask.
const SIGNOFF =
  document.querySelector('meta[name="cq-review"]')?.content === "sign-off";
const POLL_MS = 2000;
// The panel's width, and so also the strip the page yields to it and the breakpoint
// under which yielding one is worse than being covered by it. One number, written
// into the stylesheet below rather than read back off the panel: the two have to
// agree, and the panel measures zero for as long as it is closed, which is exactly
// when the page most needs to know how wide it will be.
const PANEL_W = 360;

// ---------- styles ----------
const style = document.createElement("style");
style.textContent = `
  /* The document and the panel are two scroll regions side by side. If the document
     scrolled the viewport, its scrollbar would paint at the viewport's right edge —
     over the panel, in the same few pixels as the panel's own, so the two thumbs
     stack. Body owns the document's scroll instead, and syncLayout keeps its box
     clear of the panel, which puts each region's scrollbar inside that region.

     The gutter is stable because the column is measured off it: a page that grows
     past the window mid-session — a suggestion accepted, a panel of tabs opened —
     would otherwise gain a scrollbar, and the column would re-centre in what was
     left. Stated rather than measured, because it can't be measured here: macOS
     draws overlay scrollbars, which take no room and reserve none, so on this
     machine the declaration is a no-op and the shift it prevents cannot be made to
     happen (neither scrollbar-width nor a styled ::-webkit-scrollbar nor
     --disable-features=OverlayScrollbar brings a room-taking one back). It is kept
     on the platforms where scrollbars do take room, which is most of them, and on
     the reasoning that reserving a gutter never costs more than the shift not
     reserving it produces. Nothing in the suite pins it; there is nothing here to
     pin it with. */
  html { height: 100%; overflow: hidden; }
  body { box-sizing: border-box; height: 100%; overflow-y: auto; scroll-padding-top: 54px;
         scrollbar-gutter: stable; }
  /* The strip the panel takes is given up as motion rather than as a jump, so the eye
     can follow the sentence it was reading to where it went. Keyed on the stamp that
     says the document is done becoming itself, because until then every margin the
     page has is one it arrived with: a panel restored open would otherwise slide into
     place on load, and a version switch is a load, so every revision would arrive
     sliding sideways under a reviewer who asked for a revision and not for motion.
     The stamp lands at the end of the start chain, long after the restore. Reduced
     motion is handled globally by the theme's guard. */
  body[${PAGE_PAINT_ATTRIBUTE.upgraded}="1"] { transition: margin-right .18s ease; }
  @media print { html, body { height: auto; overflow: visible; } }
  /* Rules at this level are the shared vocabulary: classes whose whole job is
     elements the page owns — a widget's controls wear cq-ui and cq-btn, and the
     runtime marks the page's own elements (cq-mark-el, cq-ins-block). Adding one
     widens the vocabulary; a rule that styles the runtime's own layer goes in the
     @scope block below instead. */
  .cq-ui { font-family: var(--sans); font-size: var(--t-5); line-height: 1.45; color: var(--ink); box-sizing: border-box; }
  .cq-ui *, .cq-ui *::before, .cq-ui *::after { box-sizing: inherit; }
  /* A press a widget injects is a span wearing role="button" (see offer), so the two
     things a <button> came with are stated here. The box, because an inline span drops
     vertical padding out of the line — only .cq-btn needs it, since every other press
     is a flex item or positioned. And the drag: a real button refused one, which is
     worth keeping wherever the control's words are the runtime's, and is exactly what
     must not happen where one of them is the page's. So the selection goes off only
     where nothing under the press is said: a descendant cannot win it back, since
     user-select none on an ancestor takes the whole subtree out of a pointer's reach
     whatever the descendant declares. */
  .cq-btn { font: inherit; padding: 4px 10px; border: 1px solid var(--border-2); border-radius: 6px; background: var(--card); cursor: pointer; white-space: nowrap; color: inherit; display: inline-block; }
  .cq-ui[role="button"]:not([data-cq-said]):not(:has([data-cq-said])) { user-select: none; -webkit-user-select: none; }
  .cq-btn:hover { background: var(--chip); }
  .cq-btn.primary { background: var(--accent); border-color: var(--accent); color: var(--paper); }
  .cq-btn.primary:hover { filter: brightness(.92); }
  /* Two selectors, two mechanisms, one look: the platform's own on the banner's real
     buttons, and the attribute wireInput sets, which is the only one a span press can
     wear. */
  .cq-btn:disabled, .cq-btn[aria-disabled="true"] { opacity: .55; cursor: default; }
  .cq-btn.on { border-color: var(--accent); color: var(--accent); background: var(--chip); }
  /* The colloquy text box, in one rule. field-sizing does the growing, so no script
     measures a textarea: the JS that did had to reset height to auto to re-measure,
     which made the box briefly too small for its own text on every keystroke — and a
     box that overflows, however briefly, flashes a scrollbar. Past max-height the
     scrollbar is real and stays. Both selectors: the panel's boxes sit inside .cq-ui,
     a widget's own box wears the class itself. */
  .cq-ui textarea, textarea.cq-ui { font: inherit; padding: 5px 8px; border: 1px solid var(--border-2); border-radius: 6px; background: var(--card); color: inherit; resize: none; field-sizing: content; max-height: 200px; overflow-y: auto; }
  .cq-ui textarea:focus, textarea.cq-ui:focus { outline: none; border-color: color-mix(in srgb, var(--accent) 45%, var(--card)); box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 25%, transparent); }
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
  /* Holding ⌥ changes what a click means, and nothing on the page said so — the chord's
     whole cost is that it is invisible. Two things say it now, and the division
     matters: the item under the pointer outlines, which answers
     *which*, and the cursor only has to stop saying "text". crosshair was tried and read
     as a cross — an icon for closing something, not for aiming at it — and every other
     stock cursor names an action this isn't (copy, alias, a menu). So the plain arrow: it
     is the one thing that says "not a text selection" without claiming to be anything
     else, and the outline is already carrying the meaning.
     One declaration on the body, inherited, rather than a rule reaching down the page:
     naming .cq-chrome here to hold the chrome out would put that class into the
     document-level surface, and the class the chrome is rooted at is not vocabulary a
     widget wears. The chrome holds itself out instead, from inside its own scope. */
  body.cq-aiming { cursor: default; }
  /* Inside the element's own box, never outside it. An outline drawn outside is at the
     mercy of whatever encloses it: a board scrolls (overflow-x: auto), its columns sit
     flush against its padding box on three sides, and the mark on a column was clipped
     down to the single vertical line that fell in the gutter — for the posted amber as
     much as for the draft accent, so a comment on a container was a comment with no
     visible mark at all. Containers are exactly what element anchoring is for, so this
     is not a corner. Drawn inside, the mark cannot be clipped by an ancestor and cannot
     stand on a neighbour, and it takes the element's own corner radius rather than
     restating one, which is what the radius here used to override. */
  .cq-mark-el { outline: 2px solid var(--quote-bar); outline-offset: -2px; cursor: pointer; }
  .cq-mark-el.cq-pending { outline-color: var(--accent); cursor: auto; }
  /* The one runtime word living inside the page's own elements, so its hiding cannot
     come from the chrome's scoped .cq-unseen — the same recipe, restated at document
     level. It becomes a skip-link-style control on focus: a reader who hears the count
     can enter its first thread, then j/k through the rest. user-select keeps it out of
     a selection, so the runtime's own words never enter a captured quote. */
  .cq-mark-note { position: absolute; width: 1px; height: 1px; padding: 0; border: 0;
    overflow: hidden; clip-path: inset(50%); user-select: none; }
  .cq-mark-note:focus-visible { position: fixed; z-index: 9050; top: 48px; left: 8px;
    width: auto; height: auto; padding: 6px 10px; overflow: visible; clip-path: none;
    border: 1px solid var(--accent); border-radius: var(--r); background: var(--card);
    color: var(--ink); box-shadow: var(--shadow); }
  .cq-ins-block { background: var(--add-tint); box-shadow: 0 0 0 4px var(--add-tint); border-radius: 2px; }
  /* Paper takes no input, so what a widget injects to be worked goes: the control,
     and the box that holds controls. What stays is a control whose label is one of
     the page's own words — a pick mark reading "chosen" is the only place the page
     says which option it carries — which is why this keys on the declaration each
     label makes (see relabel) rather than on .cq-ui, whose question is anchoring's.
     Asked of the control itself, not of what it holds: a settled group's disclosure
     names the chosen card, and that word is worth keeping on screen where the row is
     the only place it stands and worth dropping on paper, where the cards are open
     underneath saying it themselves. The runtime's own layer hides as one thing, in
     the @scope block below. */
  @media print { [data-cq-offer]:not([data-cq-said]) { display: none !important; } }
  /* Keyframe names are document-global even beside an @scope block. The stable salt
     makes this runtime-private in the one CSS namespace scoping cannot protect. */
  @keyframes cq-runtime-4f3c2a8d-pulse { 50% { opacity: .35; } }
  @keyframes cq-runtime-4f3c2a8d-flash {
    0% { background: var(--hi-tint); } 100% { background: var(--card); }
  }
  @keyframes cq-runtime-4f3c2a8d-grow {
    0% { opacity: 0; transform: translateY(-6px) scale(.985); }
  }
  /* Everything below is private to the chrome, scoped to the runtime's own container:
     no widget or page class can match a rule here, whatever it is named. (cq-tabs once
     marked itself cq-live — this block's name for the visually-hidden live region —
     and every tabbed page clipped to a pixel.) */
  @scope (.cq-chrome) {
    /* The layer is the runtime's, not the document's, so it never prints — one rule
       for all of it, rather than each piece remembering. :scope is the container
       itself, which is why this can't be written at document level without widening
       the shared vocabulary by a class only the runtime ever wears. */
    @media print { :scope { display: none; } }
    /* cursor inherits, and the page's own body may be armed for ⌥ aiming — which is a
       statement about the document, not about this layer. Stated here so the document
       side needs no mention of this container's class, which would widen the shared
       vocabulary by a name no widget ever wears. */
    :scope { cursor: auto; }
    .cq-banner { position: fixed; top: 0; left: 0; right: 0; z-index: 9000; height: 42px;
      display: flex; align-items: center; gap: 10px; padding: 0 14px;
      background: var(--veil); backdrop-filter: blur(6px); border-bottom: 1px solid var(--rule); }
    .cq-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--muted-2); flex: none; }
    .cq-dot.working { background: var(--accent);
      animation: cq-runtime-4f3c2a8d-pulse 1.4s ease-in-out infinite; }
    .cq-dot.listening { background: var(--ok); }
    .cq-dot.away { background: var(--warn); }
    .cq-dot.offline { background: var(--danger); }
    .cq-status-text { color: var(--ink-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
    .cq-status-text .cq-age { color: var(--muted); }
    .cq-spacer { flex: 1; min-width: 0; }
    /* This row is packed to the right against the spacer, and that decides who pays for
       a control changing size: it moves itself and everything to its left, while
       everything to its right keeps its place. Four of these rewrite their own words —
       the chooser's label carries the version's note, "✓ Approved" is 12px narrower than
       "✓ Looks good", and two of them count something that gains a digit — so each states
       a width rather than taking one, and the row holds still whichever of them speaks.
       What a stated width cuts off, the chooser's own menu and its tooltip still hold.

       The numbers are measured rather than derived, so they are only as good as the font
       they were measured in. That is what the two sweeps are for: a press, and the poll,
       which between them work every one of these. Either fails the day a reservation
       stops covering, rather than the day someone notices the row twitching. Three have
       done that already, and their numbers below are the re-measurement: --t-5 moved
       from 13.5px to 14px with the theme's type, taking "✓ Looks good" to 112.7px,
       "Comments (999)" to 132.4px and "✓ Accept all (999)" to 141.8px — past all three
       reservations at once. Each was read back out of a browser, because scaling the old
       number by the ratio of the sizes is deriving it, which is the thing this comment
       says not to do. */
    .cq-banner select { font: inherit; padding: 3px 6px; border: 1px solid var(--border-2); border-radius: 6px; background: var(--card); color: inherit; flex: none; width: 190px; text-overflow: ellipsis; }
    .cq-signoff { min-width: 116px; }
    /* The two that count reserve the widest they reach anywhere below a thousand, so no
       arithmetic on the count can move them and none of it has to be thought about again.
       A page with a thousand open threads on it is not one anyone hands a reviewer. */
    .cq-comments { min-width: 136px; }
    .cq-accept-all { min-width: 145px; }
    /* The one control on the right of the row that may give, because it is the leftmost
       of them and giving there moves nothing; the status text, off at the other end, is
       the other. The rest are .cq-btn, floored at their own words by nowrap — the chooser
       was the exception, so a row with no room left took the width it states back off it,
       which put every reservation above back in play on any narrow enough window. */
    .cq-latest-chip { background: var(--warn-tint); border: 1px solid var(--warn); color: var(--warn-ink); border-radius: 6px; padding: 3px 8px; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
    .cq-panel { position: fixed; top: 42px; right: 0; bottom: 0; width: min(${PANEL_W}px, 100vw); z-index: 8900;
      background: var(--card); border-left: 1px solid var(--rule); display: none; flex-direction: column; }
    .cq-panel.open { display: flex; }
    .cq-panel-head { display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; border-bottom: 1px solid var(--rule); font-weight: 600; }
    /* contain: reaching the end of the thread list must not start scrolling the page
       behind it — one wheel gesture moves one region. */
    .cq-threads { flex: 1; overflow-y: auto; overscroll-behavior: contain; padding: 10px 14px; }
    /* An Escape rung lands here (general box → the list), so the rung is visible. */
    .cq-threads:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
    .cq-empty { color: var(--muted); padding: 18px 4px; }
    .cq-thread { position: relative; border: 1px solid var(--rule); border-radius: var(--r); padding: 10px; margin-bottom: 12px; }
    .cq-thread.flash { animation: cq-runtime-4f3c2a8d-flash 1.2s ease-out; }
    /* An arrival the reconcile added while the reviewer was watching. Motion, not a
       jump: nothing above it moves, and the newcomer settles rather than appears. */
    .cq-thread.grow, .cq-msg.grow { animation: cq-runtime-4f3c2a8d-grow .32s cubic-bezier(.2,.7,.3,1); }
    .cq-thread:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
    /* The g leader's address chip, worn on the reply box it addresses — where the
       digit lands, not the thread's corner — and painted only while the window is
       armed: the placeholder speaks the address at all times, so the chip is the
       armed moment's paint rather than a standing second copy of the fact. Empty is
       unaddressed (a thread past the ninth); renderThreads writes the number, it
       doesn't add or drop the element. Top-anchored: field-sizing grows the box
       downward, and the chip must not ride the growth. */
    .cq-compose { position: relative; }
    .cq-thread-num { display: none; position: absolute; top: -8px; left: -8px; width: 17px;
      height: 17px; border: 1px solid var(--accent); border-radius: 50%; background: var(--card);
      color: var(--accent); font-size: 11px; line-height: 15px; text-align: center; z-index: 1; }
    .cq-leader-armed .cq-thread-num:not(:empty) { display: block; }
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
    /* A message body is rendered Markdown, which is why this dresses a box and not a
       paragraph. The theme's element rules are at document level and reach in here, so a
       reply's lists, code, quotes and tables already read as the page's do; what is left
       is the panel's narrower column — tighter blocks, headings that don't shout at
       360px, and no margin where the body meets its own head. */
    .cq-msg-body { margin: 2px 0 0; overflow-wrap: anywhere; }
    .cq-msg-body > :first-child { margin-top: 0; }
    .cq-msg-body > :last-child { margin-bottom: 0; }
    .cq-msg-body :is(p, ul, ol, pre, blockquote, table, hr) { margin: 6px 0; }
    /* Prose here breaks anywhere, because the thing a reply overflows on is a URL
       no wrap can help. A table is the one block in a reply with somewhere else to
       put the width — the theme makes it scroll inside itself — so breaking its
       cells to save that room spends the alignment the table was written for:
       "12,000" arrived as "12,0" over "00", in a column of figures to compare. */
    .cq-msg-body :is(th, td) { overflow-wrap: normal; }
    .cq-msg-body :is(h1, h2, h3, h4, h5, h6) { margin: 8px 0 4px; font-size: var(--t-5); }
    .cq-msg-body li { margin: 2px 0; }
    .cq-msg-body pre { padding: 8px 10px; }
    .cq-msg-body blockquote { padding: 2px 10px; }
    /* Send buttons sit at the bottom so a growing textarea doesn't stretch them. */
    .cq-compose, .cq-general { display: flex; gap: 6px; margin-top: 8px; align-items: flex-end; }
    .cq-compose textarea, .cq-general textarea { flex: 1; min-width: 0; }
    .cq-thread-actions { display: flex; justify-content: space-between; margin-top: 8px; }
    .cq-resolve { border: none; background: none; color: var(--muted); cursor: pointer; font: inherit; }
    .cq-resolve:hover { color: var(--ok); }
    .cq-general { padding: 10px 14px; border-top: 1px solid var(--rule); }
    .cq-details { margin-top: 6px; color: var(--muted); background: none; border: none; padding: 0; }
    .cq-system { color: var(--ok); margin: 8px 0; }
    .cq-fab { position: fixed; z-index: 9100; display: none; }
    /* Its own fixed row beside the button, so the button keeps its box. The chips are
       quieter than it because the words are still the ordinary case — an item is what
       the reviewer reaches for when the words are not the point. */
    .cq-fab-chain { position: fixed; z-index: 9100; display: none; gap: 4px; }
    .cq-fab-item { background: var(--card); color: var(--ink-2); }
    .cq-composer { position: fixed; z-index: 9100; display: none; width: 320px; background: var(--card);
      border: 1px solid var(--border-2); border-radius: var(--r); box-shadow: 0 8px 24px rgba(0,0,0,.12); padding: 10px; }
    /* A stranded quote is the whole passage, and the box is 320px wide. Only while showing:
       on the hidden one this would out-specify .cq-unseen's own overflow. */
    .cq-composer .cq-quote:not(.cq-unseen) { max-height: 4.2em; overflow-y: auto; }
    .cq-suggest-row { display: none; align-items: center; gap: 6px; margin: 0 0 6px; color: var(--muted); font-size: 12.5px; cursor: pointer; }
    .cq-suggest-row input { margin: 0; accent-color: var(--accent); }
    .cq-suggest-label { font-size: var(--t-6); letter-spacing: .05em; text-transform: uppercase; color: var(--ok-ink); margin: 4px 0 2px; }
    /* A suggestion renders verbatim — its characters are what the next version
       carries (see msgNode) — so this is where they keep their own line breaks. */
    .cq-msg-body.cq-suggest-body { background: var(--add-tint); padding: 4px 8px;
      border-radius: 6px; white-space: pre-wrap; }
    .cq-composer textarea { width: 100%; min-height: 56px; }
    .cq-composer-row { display: flex; justify-content: flex-end; gap: 6px; margin-top: 6px; }
    .cq-toast { position: fixed; bottom: 18px; right: 18px; z-index: 9200; max-width: calc(100vw - 36px);
      overflow-wrap: anywhere; background: var(--ink); color: var(--paper); padding: 9px 14px;
      border-radius: var(--r); opacity: 0; transition: opacity .25s, right .18s ease; pointer-events: none; }
    .cq-toast.show { opacity: .95; }
    .cq-toast.clickable { pointer-events: auto; cursor: pointer; }
    .cq-live { position: fixed; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
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
    .cq-help kbd, .cq-keyline kbd { font-family: ui-monospace, monospace; font-size: 12px; background: var(--chip);
      border: 1px solid var(--border-2); border-radius: 4px; padding: 1px 6px; }
    /* The key line: what a key does right now, rendered from the same scene() that
       runs Escape (see the module docstring). Floating chrome nothing presses
       (pointer-events none) and the eye's copy of facts spoken elsewhere
       (aria-hidden), so it owes the press sweep nothing; syncLayout lifts it over a
       covering sheet the way it lifts the toast, and body reserves its height so
       the document's last lines never end under it. */
    .cq-keyline { position: fixed; left: 18px; bottom: 14px; z-index: 9000; pointer-events: none;
      display: flex; gap: 12px; align-items: baseline; max-width: calc(100vw - 36px);
      overflow: hidden; color: var(--muted); font-size: 12px; white-space: nowrap;
      background: var(--card); border: 1px solid var(--rule); border-radius: var(--r);
      padding: 5px 10px; }
    .cq-keyline:empty { display: none; }
    .cq-keyline .cq-key { display: inline-flex; gap: 5px; align-items: baseline; }
    .cq-keyline kbd.armed { border-color: var(--accent); color: var(--accent); }
  }
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
// The three controls the banner's news arrives as, each present only while it has
// something to say. Room a control has once taken is room it keeps for the rest of the
// page's life: before it first appears there is nothing to hold, so a page that never
// falls behind pays nothing for the chip, and once one has stood somewhere the others
// can't close ranks over it — a second tab deciding the last pending suggestion took the
// ✓ Accept all away and slid the New-version chip 148px right, under whoever was
// reaching for it. Reserving from the start instead would hold room on every row for news
// that page will never get, which shows as a gap the moment one of them is there and its
// neighbour isn't; reserving nothing is the movement. This spends only where the
// alternative is a control moving, and only on the pages that got the news.
//
// One setter stating the whole outcome, per showComposer and showFab, so no caller has
// to know which of the two ways of being absent this control is currently in.
const showNews = (control, on) => {
  if (on) control.dataset.cqStood = "1";
  control.style.display = on || control.dataset.cqStood ? "" : "none";
  control.style.visibility = on ? "" : "hidden";
};
const latestChip = el("button", "cq-ui cq-btn cq-latest-chip", "");
const diffBtn = el("button", "cq-btn", "Δ");
const acceptAllBtn = el("button", "cq-btn cq-accept-all", "");
acceptAllBtn.title = "Accept every suggested change still pending";
for (const control of [latestChip, diffBtn, acceptAllBtn]) showNews(control, false);
const versionSelect = document.createElement("select");
versionSelect.title = "Version";
versionSelect.setAttribute("aria-label", "Version");
// Which version this is, is the document's own answer (VNUM, off the path), so the
// chooser states it now rather than standing empty until the first poll answers.
// A blank control beside a rendered page is a page still loading, which this one
// isn't; the width is the theme's either way, so the list arriving moves nothing.
if (VNUM !== null)
  versionSelect.append(
    Object.assign(document.createElement("option"), {
      value: VNUM,
      textContent: `v${VNUM}`,
    }),
  );
const toggleBtn = el("button", "cq-btn cq-comments", "Comments");
toggleBtn.title =
  "Show or hide the comment panel (c toggles, Esc closes, ? lists all keys)";
toggleBtn.setAttribute("aria-expanded", "false");
const approveBtn = el("button", "cq-btn primary cq-signoff", "✓ Looks good");
approveBtn.title = "Approve this work; the page stays open for follow-up";
const endReviewBtn = el("button", "cq-btn cq-end-review", "End review");
endReviewBtn.title = "End this comments-only review";
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
banner.append(SIGNOFF ? approveBtn : endReviewBtn);

const panel = el("aside", "cq-ui cq-panel");
const panelHead = el("div", "cq-panel-head");
const closeBtn = Object.assign(el("button", "cq-btn", "×"), {
  title: "Close (Esc)",
  onclick: () => setPanel(false),
});
closeBtn.setAttribute("aria-label", "Close comments");
panelHead.append(el("span", "", "Comments"), closeBtn);
const threadsBox = el("div", "cq-threads");
// An Escape rung: backing out of the general box lands on the list (visible ring,
// j/k walk on from it) rather than on nothing. -1 keeps it out of the Tab order.
threadsBox.tabIndex = -1;
const generalRow = el("div", "cq-general");
const generalInput = document.createElement("textarea");
const generalSend = el("button", "cq-btn primary", "Send");
generalRow.append(generalInput, generalSend);
panel.append(panelHead, threadsBox, generalRow);

const fab = el("button", "cq-ui cq-btn primary cq-fab", "💬 Comment");
// A chip per element enclosing the selection, in its own row beside the button rather
// than inside it. The 💬 keeps its words, its width and its place, because the
// reviewer's aim is on it before the chips are drawn — a control that
// changes size under a pointer already reaching for it is what the press sweep exists to
// catch. See "pointing at an item" below.
const fabChain = el("div", "cq-ui cq-fab-chain");
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
// The key line — scene()'s rendering; aria-hidden per the module docstring (the
// eye's copy of facts spoken by placeholders, announce() and the "?" overlay).
const keylineEl = el("div", "cq-ui cq-keyline");
keylineEl.setAttribute("aria-hidden", "true");

// The one scope root for the chrome's private rules: they match nothing outside
// this container. A div, not a cq-* element — the render gate reads a cq-* ancestor
// as "inside a widget", and the runtime's layer is inside none.
const chromeRoot = el("div", "cq-chrome");
chromeRoot.append(
  banner,
  panel,
  fab,
  fabChain,
  composer,
  toastEl,
  liveEl,
  helpEl,
  keylineEl,
);
document.body.append(chromeRoot);
const basePaddingTop = parseFloat(getComputedStyle(document.body).paddingTop) || 0;
document.body.style.paddingTop = basePaddingTop + 42 + "px";
// The banner's reservation at the other edge: the key line stands for the page's
// life, so the document's last lines get room rather than ending under it. The
// amount is measured off the rendered line in syncLayout rather than stated here —
// a number alone stops being true silently, which is the press-sweep norm's whole
// subject.
const basePaddingBottom =
  parseFloat(getComputedStyle(document.body).paddingBottom) || 0;

// ---------- state ----------
let events = [];
let lastEventSeq = -1;
let lastVersionsKey = "";
let latestVersion = null;
let versions = [];
let agentMsgCount = -1;
let panelOpen = false;
// Whether the panel stands over the page rather than beside it. That is the same fact as
// which region the reader's own scrolling moves, so syncLayout — the layout's one writer
// — writes it, and the half-page keys read it rather than re-deriving the breakpoint or
// asking the overflow it set.
let panelCovers = false;
let pendingAnchor = null;

// The fold answers where state stands; this answers how it got there. Widgets receive
// their own absolute actions in log order, bounded by the version being viewed. A reply
// widget lives in the chrome rather than in a version, so its frozen log markup sees the
// whole sequence. Returning fresh event copies keeps the private event store private.
export function actionSequence(widget, action) {
  return events
    .filter(
      (event) =>
        event.kind === "action" &&
        event.widget === widget.id &&
        (!action || event.action === action) &&
        (inChrome(widget) || event.version <= VNUM) &&
        appliedActions.has(event.seq),
    )
    .map((event) => structuredClone(event));
}

// Subscribe after replay has had the last word for a poll. actionSequence exposes only
// actions replay has settled, so a widget that deferred under live input never narrates
// a state its body does not hold. The callback also runs immediately, so a module owns
// its complete rendering in one function whether the first state arrived before or
// after it connected.
export function watchActions(widget, action, callback) {
  const update = () => callback(actionSequence(widget, action));
  document.addEventListener("cq-actions", update);
  update();
  return () => document.removeEventListener("cq-actions", update);
}

// ---------- draft persistence ----------
// Text the user typed but hasn't sent must survive navigation, reload, version switches,
// and server death; only a successful send clears it. It is working state of this tab,
// not shared page state: sessionStorage keeps another tab's send or Cancel from clearing
// a newer local edit. Recorded actions in the log are what converge across tabs.
// Surviving the tab's own close is the open question (TODO.md), and it is a question
// about what a second tab then sees rather than about where a draft lives. Storage
// failures never break typing. Exported: a widget holding user text (cq-draft's in-place
// edit) keeps it under the same discipline, in the same store.
const DRAFT = "cq-draft:";
export const saveDraft = (ctx, val) => {
  try {
    if (val) sessionStorage.setItem(DRAFT + ctx, val);
    else sessionStorage.removeItem(DRAFT + ctx);
  } catch {}
};
export const loadDraft = (ctx) => {
  try {
    return sessionStorage.getItem(DRAFT + ctx) || "";
  } catch {
    return "";
  }
};
const pruneReplyDrafts = (liveIds) => {
  const rp = DRAFT + "reply:";
  try {
    for (let i = sessionStorage.length - 1; i >= 0; i--) {
      const k = sessionStorage.key(i);
      if (k && k.startsWith(rp) && !liveIds.has(k.slice(rp.length)))
        sessionStorage.removeItem(k);
    }
  } catch {}
};

// Panel open/closed is remembered too: a version switch reloads the document, and
// reopening the panel by hand after every revision gets old fast.
const PANEL_KEY = "cq-panel-open";
function syncLayout() {
  // A margin, not padding: body is the document's scroll container, so this is what
  // ends its box — and its scrollbar — at the panel's edge instead of under it.
  // Below the breakpoint there is no room to reserve, so the panel covers the page
  // and the page hands over scrolling with it: one wheel gesture moves one region,
  // and while the sheet is up that region is its thread list. The page holds its
  // place for when the sheet closes — a hidden-overflow scroller keeps its position,
  // and still moves for a j/k walk or a version switch restoring where the reviewer
  // was, so the passage behind the sheet is the one the panel is talking about.
  //
  // The strip is taken from the page rather than held aside for it, which makes
  // opening the panel the largest movement in the product: the column re-centres by
  // half the panel's width, and on a window narrow enough to lose width as well it
  // rewraps every line. Both are carried as motion rather than as a jump — the
  // transition granted to body at the end of the restore — because an eye can follow
  // a sentence that slides and cannot find one that teleports.
  panelCovers = panelOpen && innerWidth <= PANEL_W * 2;
  document.body.style.marginRight = panelOpen && !panelCovers ? PANEL_W + "px" : "";
  document.body.style.overflowY = panelCovers ? "hidden" : "";
  // The toast lives in the same corner as the panel's Send button. Beside a wide
  // panel it steps left; over a covering sheet it stays inside the viewport and
  // rises above the whole composer, including a textarea grown by an unsent draft.
  toastEl.style.right = (panelOpen && !panelCovers ? PANEL_W + 18 : 18) + "px";
  toastEl.style.bottom = (panelCovers ? generalRow.offsetHeight + 18 : 18) + "px";
  // The key line takes the toast's lift over a covering sheet, or the sheet's own
  // composer stands on the words saying what Esc will do to it.
  keylineEl.style.bottom = (panelCovers ? generalRow.offsetHeight + 14 : 14) + "px";
  document.body.style.paddingBottom =
    basePaddingBottom + keylineEl.offsetHeight + 20 + "px";
}
function setPanel(open) {
  // Closing while focus is inside would drop it on body, the reviewer's place
  // lost silently; it lands on the one control that reopens what just closed.
  if (!open && panel.contains(document.activeElement))
    toggleBtn.focus({ preventScroll: true });
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
  paintLine();
}
toggleBtn.onclick = () => setPanel(!panelOpen);
addEventListener("resize", syncLayout);
// field-sizing and every other rendered-size change feed the one geometry writer —
// the key line included, whose height sets the body's bottom reservation.
const layoutSizes = new ResizeObserver(syncLayout);
layoutSizes.observe(generalRow);
layoutSizes.observe(keylineEl);

let toastTimer = 0;
function showToast(msg, onClick) {
  announce(msg);
  toastEl.textContent = msg;
  syncLayout();
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

// Returns the event the server minted — the id is the sender's only handle on the
// thread or message it just created, which is what revealThread is handed — or null
// when the send failed. The poll is awaited before returning, so by the time a caller
// holds the minted event the panel has already rendered it.
async function post(event) {
  try {
    const res = await fetch("/api/event", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(event),
    });
    if (!res.ok) throw new Error(await res.text());
    const { event: minted } = await res.json();
    await poll();
    return minted;
  } catch {
    showToast("Couldn't send — server offline?");
    return null;
  }
}

// ---------- text inputs ----------
// One helper wires every composer: the general box, each per-thread reply, and the
// selection composer. They persist a draft on each keystroke, send on ⌘/Ctrl+Enter, and
// can't be double-sent by an impatient second click. Growing with their content is the
// stylesheet's job (field-sizing), not this file's.
// Returns a sync() the caller runs after setting .value programmatically, so the send
// button agrees with what's in the box.
export const SEND_KEYS = /Mac|iPhone|iPad/.test(
  navigator.platform || navigator.userAgent,
)
  ? "⌘⏎"
  : "Ctrl+⏎";
function wireInput(ta, { hint, address, save, send, sendBtn }) {
  // The hint goes in the placeholder, where it's visible exactly while the box is
  // empty and can't be found any other way; the button's tooltip spells the send key
  // out. The send shortcut is focus-scoped, so only the focused box may claim it —
  // unfocused, the placeholder carries the box's own address instead (the leader
  // sequence that reaches it), where the box has one. hint is a function where the
  // label changes under a live box (the composer's suggest mode); address is always
  // one, because a thread's number renumbers as earlier threads resolve while its box
  // stands.
  const label = () => (typeof hint === "function" ? hint() : hint);
  const paint = () => {
    const suffix = document.activeElement === ta ? SEND_KEYS : address?.();
    ta.placeholder = suffix ? `${label()} · ${suffix}` : label();
  };
  ta.addEventListener("focus", paint);
  ta.addEventListener("blur", paint);
  sendBtn.title = `Send (${SEND_KEYS})`;
  let sending = false;
  // aria-disabled rather than the property, because a widget's send button is a span
  // wearing role="button" (see offer) and a span has no `disabled` to set — it would
  // have looked live while submit() below refused it. The attribute reads on either
  // element, and the guard in submit() is what actually holds; a focusable button
  // saying it can't send yet is better than one the reader can't reach to find out.
  const sync = () => {
    paint();
    sendBtn.setAttribute("aria-disabled", String(sending || !ta.value.trim()));
  };
  paint();
  const submit = async () => {
    if (sending) return;
    // A send key on an empty box answered with silence reads as a send that
    // happened — the blind drive believed exactly that. Say the nothing out loud
    // (the toast announces too).
    if (!ta.value.trim()) return showToast("Nothing to send — the box is empty");
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
function buildThreads() {
  const threads = new Map();
  const threadFor = new Map();
  for (const e of events) {
    if (e.kind === "comment") {
      const thread = { root: e, msgs: [e], resolved: false };
      threads.set(e.id, thread);
      threadFor.set(e.id, thread);
      continue;
    }
    // An accept snapshots the thread its suggestion answered into the action
    // (the honoring version retires the wrapper that held the mapping, and one
    // atomic event can't half-arrive the way a second POST could).
    if (e.kind === "action" && e.action === "accept") {
      const answered = threads.get(e.detail.resolves);
      if (answered) answered.resolved = true;
      continue;
    }
    if (e.kind === "reply") {
      const thread = threadFor.get(e.parent);
      thread.msgs.push(e);
      threadFor.set(e.id, thread);
    } else if (e.kind === "resolve") {
      threadFor.get(e.parent).resolved = true;
    }
  }
  return [...threads.values()];
}

const escapeHtml = (s) =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

// Lazily, like the tokenizer: a page is usually handed over before anyone has said
// anything, and one with no messages never pays the parse. poll() awaits this before
// the panel builds a body, which is what keeps msgNode synchronous.
//
// Raw HTML — block and inline both route through the one `html` renderer — escapes to
// the characters it was written in: prose says `Vec<T>`, and a message injects widgets
// only through its gate-validated `markup` field, never through text. breaks: a single
// newline is a line break, because a message is typed prose and nobody types two
// spaces to mean the line they just ended.
let renderMarkdown;
let markedReady;
const loadMarked = () =>
  (markedReady ??= import("/vendor/marked.esm.js").then((m) => {
    const md = new m.Marked({
      breaks: true,
      renderer: { html: (t) => escapeHtml(t.text) },
    });
    renderMarkdown = (text) => md.parse(text);
  }));

// Bodies are cached per event id and re-adopted when a thread node is rebuilt — which
// the reconcile leaves one occasion for, a thread resolving: the log is append-only so
// a body's text never changes, and re-adopting the node keeps a widget in a reply
// (a rendered diagram) from re-upgrading across that rebuild.
const msgBodies = new Map();
function msgNode(m) {
  const div = el("div", `cq-msg ${m.author}`);
  div.dataset.mid = m.id; // the reconcile's key, and revealThread's address for it
  const head = el("div", "cq-msg-head");
  head.append(
    el("b", "", m.author === "claude" ? m.agent || "Agent" : "You"),
    el("time", "", ago(m.ts)),
  );
  let body = msgBodies.get(m.id);
  if (!body) {
    body = el("div", "cq-msg-body");
    if (m.suggestion) {
      // Verbatim: a suggestion's characters are bound for the page as typed, and a
      // rendering would show an italic where the next version carries the asterisks.
      body.classList.add("cq-suggest-body");
      body.textContent = m.text;
    } else {
      body.innerHTML = renderMarkdown(m.text);
      // The widget markup beside the text, injected as the CLI gate validated it.
      // Already-defined widgets upgrade on insertion; these two passes don't come
      // along with them — the said pass writes a widget's declared words, and a
      // fenced block is a <pre><code class="language-…"> like any the page holds.
      if (m.markup) body.insertAdjacentHTML("beforeend", m.markup);
      renderSaid(body);
      reachScrollers(body);
      // Not settle()d: that queue holds the page's geometry still for the first anchor
      // pass, and a message colors in the panel, where no anchor is captured and nothing
      // waits. Each block already fails soft to its own plain source.
      highlightBlocks(body);
    }
    msgBodies.set(m.id, body); // the id is server-minted, on every event
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
//
// An id is the page's name for an item and not the reviewer's. `card-migration` says
// nothing they wrote, and pointing at an item is an ordinary gesture rather than the
// diagram's special case, so anchors reading this way are ordinary in the panel too.
// An element anchor is labelled with the item's own opening words, and falls
// back to the id where this version has no such element. The kind goes before the words
// because the two together are a name, where the words alone read as a quote the thread
// does not hold.
function anchorLabel(anchor) {
  if (anchor?.quote) return `“${anchor.quote}”`;
  if (!anchor?.section) return "";
  const item = document.getElementById(anchor.section);
  const says = itemSays(item);
  return `§ ${says ? `${itemWord(item)} · ${says}` : anchor.section}`;
}

// The thread's address under the g leader: 1–9 by open order, 0 past the ninth. One
// writer, renderThreads, because the number is the list's and not the thread's —
// resolving an early thread renumbers every one after it without touching their nodes.
// The reply box's armed chip and its placeholder are both renderings of this map,
// repainted after every reconcile; nothing reads either back.
const threadAddress = new Map();

// The reconcile's one mover, shared by the list and the resolved disclosure: make
// `parent`'s children `nodes`, in that order, touching nothing already in its place.
// Not touching it matters beyond economy: reinserting a node restarts its CSS
// animations, drops any focus and caret inside it, and swaps it out from under a
// pressed pointer, which swallows the click. Stale nodes go first for the same
// reason — with one removed mid-list, everything after it is exactly one place
// forward, so the walk keeps those where they stand instead of reinserting each.
function setChildren(parent, nodes) {
  const keep = new Set(nodes);
  for (const child of [...parent.children]) if (!keep.has(child)) child.remove();
  let cursor = parent.firstChild;
  for (const node of nodes) {
    if (node === cursor) cursor = cursor.nextSibling;
    else parent.insertBefore(node, cursor);
  }
}

const emptyNote = el(
  "div",
  "cq-empty",
  "No comments yet. Select any text on the page to comment on it, or use the box below.",
);

// A terminal event's row, keyed like everything else in the list so its clock can
// refresh in place.
function systemNode(e, text) {
  let div = threadsBox.querySelector(`:scope > .cq-system[data-id="${e.id}"]`);
  if (!div) {
    div = el("div", "cq-system");
    div.dataset.id = e.id;
  }
  if (div.textContent !== text) div.textContent = text;
  return div;
}

// The resolved disclosure, one <details> for the page's life: the reviewer's
// open/closed toggle is the browser's state, and it survives arrivals only if the
// element does — the rebuild this replaced snapped it shut on every one.
let resolvedBox = null;

// A thread's node is found where it already stands — the open list or the resolved
// disclosure — and kept: the log is append-only, so a kept node only ever gains
// messages and refreshes its clocks. Resolving is the one transition that reshapes a
// node (the reply box, the actions and the badge all go) and so the one that rebuilds
// it; msgBodies carries the rendered bodies across. `grow` animates what this call
// creates, for arrivals into a list the reviewer is already looking at.
function threadNode(t, grow) {
  const existing = threadsBox.querySelector(`.cq-thread[data-id="${t.root.id}"]`);
  const existingResolved = existing && !existing.querySelector(":scope > .cq-compose");
  if (existing && existingResolved === t.resolved) {
    const compose = existing.querySelector(":scope > .cq-compose");
    for (const m of t.msgs) {
      let msg = existing.querySelector(`:scope > .cq-msg[data-mid="${m.id}"]`);
      if (!msg) {
        msg = msgNode(m);
        if (grow) msg.classList.add("grow");
        existing.insertBefore(msg, compose);
      }
      // The head's clock, not any <time> a reply's own markup might carry.
      const time = msg.querySelector(":scope > .cq-msg-head time");
      const when = ago(m.ts);
      if (time.textContent !== when) time.textContent = when;
    }
    return existing;
  }

  const div = el("div", "cq-thread");
  div.tabIndex = -1; // j/k focus target; Enter (threadsBox keydown) drops into its reply box
  div.dataset.id = t.root.id;
  if (grow) div.classList.add("grow");
  const label = anchorLabel(t.root.anchor);
  if (label) {
    const quote = el("blockquote", "cq-quote", label);
    quote.onclick = () => scrollToThread(t.root.id);
    div.append(quote);
  }
  t.msgs.forEach((m) => div.append(msgNode(m)));
  if (!t.resolved) {
    const row = el("div", "cq-compose");
    // The box's address under the g leader, worn on the box the digit lands in and
    // painted only while the window is armed. The placeholder speaks the same
    // address at all times ("Reply · g 2"), which is what a screen reader hears —
    // the chip is the armed moment's copy for the eye, so it stays out of the tree.
    // Written by renderThreads, because the number is positional: it changes
    // without this node changing.
    const badge = el("span", "cq-thread-num");
    badge.setAttribute("aria-hidden", "true");
    row.append(badge);
    const input = document.createElement("textarea");
    const draftCtx = "reply:" + t.root.id;
    input.value = loadDraft(draftCtx);
    const send = el("button", "cq-btn", "Reply");
    row.append(input, send);
    div.cqSync = wireInput(input, {
      hint: "Reply",
      address: () => {
        const num = threadAddress.get(t.root.id);
        return num ? `g ${num}` : "";
      },
      sendBtn: send,
      save: (v) => saveDraft(draftCtx, v),
      send: async (text) => {
        const sent = await post({
          kind: "reply",
          parent: t.root.id,
          version: VNUM,
          text,
        });
        if (!sent) return;
        // post() polled, so the reconcile has already appended the message — and kept
        // this very box, which empties for the next thought and holds focus whichever
        // control sent it.
        saveDraft(draftCtx, "");
        input.value = "";
        revealThread(sent.id);
        input.focus({ preventScroll: true });
      },
    });
    div.cqSync(); // a restored reply draft enables its Reply button
    const actions = el("div", "cq-thread-actions");
    const resolve = el("button", "cq-resolve", "✓ Resolve");
    // Resolving rebuilds this node into the disclosure and takes focus with it —
    // the blind drive fell to body here. Land where j would have gone: the thread
    // that now holds this one's place, else the previous, else the list.
    resolve.onclick = async () => {
      const open = [...threadsBox.querySelectorAll(":scope > .cq-thread")];
      const at = open.indexOf(div);
      await post({ kind: "resolve", parent: t.root.id });
      const kept = [...threadsBox.querySelectorAll(":scope > .cq-thread")];
      (kept[at] ?? kept[at - 1] ?? threadsBox).focus({ preventScroll: true });
    };
    actions.append(el("span"), resolve);
    div.append(row, actions);
  }
  return div;
}

// The DOM is the one record of what's rendered, reconciled against the log: nodes the
// list already holds are kept, and only what the log changed is added, moved, or
// dropped. The rebuild this replaced destroyed every node on every render and then
// hand-restored the reader's place — scroll offset, focused thread, caret — and what
// no restore could give back was identity: nothing could animate, one send route kept
// focus and the other dropped it, and a reviewer's own comment landed below the fold
// of a list put back exactly where it was. Nodes surviving is what deleted all of it.
function renderThreads() {
  const threads = buildThreads();
  const open = threads.filter((t) => !t.resolved);
  const resolved = threads.filter((t) => t.resolved);
  // Newcomers settle in (`grow`) only when the reviewer already has the list in front
  // of them: the first populated render is the page loading, not news arriving, and a
  // node animated while the panel is closed would replay the moment it opens.
  const grow =
    panelOpen && !REDUCED && Boolean(threadsBox.querySelector(":scope > .cq-thread"));

  const wanted = [];
  if (!threads.length) wanted.push(emptyNote);
  threadAddress.clear();
  // The first nine open threads are addressable (g 1–9), in the order j/k walk;
  // past nine, digits stop and j/k still reach everything.
  open.forEach((t, i) => {
    threadAddress.set(t.root.id, i < 9 ? i + 1 : 0);
    wanted.push(threadNode(t, grow));
  });
  for (const e of events) {
    if (e.kind === "done") wanted.push(systemNode(e, `✓ Approved ${ago(e.ts)}`));
    else if (e.kind === "close")
      wanted.push(systemNode(e, `Review ended ${ago(e.ts)}`));
  }
  if (resolved.length) {
    if (!resolvedBox) {
      resolvedBox = el("details", "cq-details");
      resolvedBox.append(el("summary"));
    }
    const summary = resolvedBox.firstChild;
    const said = `Resolved (${resolved.length})`;
    if (summary.textContent !== said) summary.textContent = said;
    setChildren(resolvedBox, [summary, ...resolved.map((t) => threadNode(t, false))]);
    wanted.push(resolvedBox);
  }
  setChildren(threadsBox, wanted);

  // The chip and the reply placeholder both speak the thread's address, repainted
  // after ordering because resolving an early thread renumbers everything after it.
  for (const div of threadsBox.querySelectorAll(":scope > .cq-thread")) {
    const num = threadAddress.get(div.dataset.id);
    const worn = num ? String(num) : "";
    const badge = div.querySelector(".cq-compose > .cq-thread-num");
    if (badge.textContent !== worn) badge.textContent = worn;
    div.cqSync();
  }
  toggleBtn.textContent = `Comments (${open.length})`;
  paintLine(); // the key line's j/k and g rows stand only over threads (threadAddress)
}

// A kept node may still be moved by a later reconcile, and reinsertion restarts CSS
// animations — so the class comes off the moment its animation has run. A node grown
// while its list was off-screen never ran one; the panelOpen gate above is what keeps
// that replay from greeting the panel's next open.
threadsBox.addEventListener("animationend", (ev) => ev.target.classList.remove("grow"));

// The panel and the page marks are two views of the same threads, and the paint pass
// reports back to the list renderThreads just reconciled — always render them as a pair.
function renderPanel() {
  renderThreads();
  paintAnchors();
}

// One answer to "show me that thread", whoever asks: a click on a mark out on the page
// and a send that just landed both come here, with a thread's id or a message's. The
// panel scrolls its own list — moving the page to a thread's passage is scrollToThread,
// a different question — and flashes the thread. The flash takes over from a running
// grow explicitly: both classes bind the element's one animation declaration, and the
// send's confirmation is the one the gesture asked for.
function revealThread(id) {
  setPanel(true);
  const node = threadsBox.querySelector(
    `.cq-thread[data-id="${id}"], .cq-msg[data-mid="${id}"]`,
  );
  if (!node) return;
  const thread = node.closest(".cq-thread");
  node.scrollIntoView({
    behavior: SCROLL,
    block: node === thread ? "center" : "nearest",
  });
  thread.classList.remove("grow");
  thread.classList.add("flash");
  setTimeout(() => thread.classList.remove("flash"), 1300);
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
//
// Which slots retire is the registry's to say, so this and interact.py's reading of the
// same page follow one declaration: x-retired-when names the decision that removes the
// element, x-parent the wrapper the decision is recorded on.
const retiredSlots = () =>
  Object.entries(registry)
    .filter(([, entry]) => entry["x-retired-when"])
    .map(
      ([tag, entry]) =>
        `${entry["x-parent"]}[data-cq-state="${entry["x-retired-when"]}"] > ${tag}`,
    )
    .join(", ");
// What no label can speak through, however it is marked: an inline script, the
// stylesheet a rendered diagram carries inside its <svg>, and a slot the reviewer's
// decision took off the page. Chrome is the rest of what the anchor pass skips and
// the one part a label yields — it is a look, and a look cannot make a word the
// runtime's.
function silenced() {
  const retired = retiredSlots();
  return ["script", "style", ...(retired ? [retired] : [])].join(", ");
}

// An element the reviewer's decision took off the page, asked of an element rather
// than of text: a retired slot (or anything inside one), or a decided element the
// retirement emptied — a deletion accepted, an insertion refused — whose every child
// is now a retired slot or the runtime's own chrome, with no text of its own. The
// same declaration the anchor pass skips text by answers both (`inUi`, so a child
// that is a declared label counts as words still showing), and so an element anchor
// and a quote cannot disagree about what left the page.
function settledAway(el) {
  const retired = retiredSlots();
  if (!retired) return false;
  if (el.closest(retired)) return true;
  const nodes = [...el.childNodes];
  return (
    nodes.some((n) => n.nodeType === 1 && n.matches(retired)) &&
    nodes.every((n) =>
      n.nodeType === 1
        ? n.matches(retired) || inUi(n)
        : n.nodeType !== 3 || !n.data.trim(),
    )
  );
}
const GENERATED = ".cq-ui, [data-cq-gen]";
// A label a widget declared as the page speaking (relabel), which the anchor pass reads
// over the chrome it sits in.
const SAID = "[data-cq-said]";
// The same question one node at a time: is this the runtime's own chrome rather than the
// document? Every affordance asks it before acting on where the pointer or the caret is.
// The nearest element that answers wins: a declared label is the page's words inside the
// control it labels, and a control nested inside one is chrome again. `.cq-ui` alone was
// the answer once, and it is a look — which is how a reviewer ended up reading a heading
// they could not point at, twice.
const inUi = (node) => {
  const near = (node?.nodeType === 1 ? node : node?.parentElement)?.closest(
    `.cq-ui, ${SAID}`,
  );
  return Boolean(near) && !near.matches(SAID);
};
// A different question the class also used to answer, and not a question about looks at
// all: which document is this element in? The runtime's layer is one container, so a
// widget inside a reply — markup frozen in the log, carried by no version — is exactly
// what that container holds, and the reading position is a place in the page rather than
// in the panel over it. `.cq-ui` reached those elements and a widget's own controls out
// on the page besides, which is the look standing in for the place.
const inChrome = (node) => Boolean(node?.closest(".cq-chrome"));
const TEXT_BLOCK =
  "p,li,h1,h2,h3,h4,h5,h6,td,th,pre,blockquote,dd,dt,figcaption,summary";
// The two readings, each one predicate over a text node and named for the question it
// answers. Anchoring reads what the reviewer can point at: not the runtime's own words —
// `inUi`, which a declared label answers for itself — and nothing behind a wall no label
// speaks through, so a pick mark inside a slot the reviewer accepted away is gone with
// the slot, its marker notwithstanding. The diff reads what the base version holds, and
// the base parses unupgraded, so everything an upgrade generated goes, a declared label
// included: the version being compared against has none.
//
// Built per walk rather than per node, because the retired half of the wall is read out
// of the registry each time it is asked for.
const quotable = () => {
  const gone = silenced();
  return (n) => !inUi(n) && !n.parentElement?.closest(gone);
};
const authored = () => (n) => !n.parentElement?.closest(GENERATED);
// ownerDocument, not document: the diff walks a base version parsed into its own document.
function textNodesUnder(rootEl, accepts = quotable()) {
  const walker = rootEl.ownerDocument.createTreeWalker(rootEl, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) =>
      accepts(n) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT,
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
// The block a node reads as part of, and null where it belongs to no block of its own —
// which is a different answer from "its parent", and the two callers want different ones.
const blockAt = (node) => node.parentElement.closest(TEXT_BLOCK);
const blockOf = (node) => blockAt(node) ?? node.parentElement;
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

// One lossless text alignment for every widget that needs to explain a sequence of
// whole-text states. Segmenter keeps words and punctuation in the language-aware
// units this runtime already assumes; a linear-space Hirschberg walk supplies the
// ordered shared spine. Its quadratic *time* is capped: after stripping a common
// prefix and suffix, a very large divergent middle is one replacement instead of a
// page-freezing attempt at fine-grained alignment. Joining same+delete reconstructs
// `before`, and joining same+insert reconstructs `after`, exactly.
const textUnits = new Intl.Segmenter(undefined, { granularity: "word" });
const ALIGN_CELLS = 1_000_000;

function lcsRow(left, lo, hi, right, rlo, rhi, reverse) {
  const width = rhi - rlo;
  let previous = new Uint32Array(width + 1);
  for (let at = 0; at < hi - lo; at++) {
    const current = new Uint32Array(width + 1);
    const word = reverse ? left[hi - at - 1] : left[lo + at];
    for (let across = 1; across <= width; across++) {
      const other = reverse ? right[rhi - across] : right[rlo + across - 1];
      current[across] =
        word === other
          ? previous[across - 1] + 1
          : Math.max(previous[across], current[across - 1]);
    }
    previous = current;
  }
  return previous;
}

function lcsMatches(left, lo, hi, right, rlo, rhi, matches) {
  if (lo === hi || rlo === rhi) return;
  if (hi - lo === 1) {
    for (let at = rlo; at < rhi; at++)
      if (left[lo] === right[at]) {
        matches.push([lo, at]);
        break;
      }
    return;
  }

  const middle = lo + Math.floor((hi - lo) / 2);
  let split = 0;
  {
    const forward = lcsRow(left, lo, middle, right, rlo, rhi, false);
    const backward = lcsRow(left, middle, hi, right, rlo, rhi, true);
    let best = -1;
    const width = rhi - rlo;
    for (let at = 0; at <= width; at++) {
      const score = forward[at] + backward[width - at];
      if (score > best) {
        best = score;
        split = at;
      }
    }
  }
  lcsMatches(left, lo, middle, right, rlo, rlo + split, matches);
  lcsMatches(left, middle, hi, right, rlo + split, rhi, matches);
}

export function alignText(before, after) {
  const left = [...textUnits.segment(before)].map((part) => part.segment);
  const right = [...textUnits.segment(after)].map((part) => part.segment);
  const runs = [];
  const push = (kind, text) => {
    if (!text) return;
    const last = runs.at(-1);
    if (last?.kind === kind) last.text += text;
    else runs.push({ kind, text });
  };

  let prefix = 0;
  while (
    prefix < left.length &&
    prefix < right.length &&
    left[prefix] === right[prefix]
  )
    prefix++;
  let suffix = 0;
  while (
    prefix + suffix < left.length &&
    prefix + suffix < right.length &&
    left[left.length - suffix - 1] === right[right.length - suffix - 1]
  )
    suffix++;

  push("same", left.slice(0, prefix).join(""));
  const leftEnd = left.length - suffix;
  const rightEnd = right.length - suffix;
  const matches = [];
  if ((leftEnd - prefix) * (rightEnd - prefix) <= ALIGN_CELLS)
    lcsMatches(left, prefix, leftEnd, right, prefix, rightEnd, matches);

  let i = prefix;
  let j = prefix;
  for (const [li, rj] of matches) {
    push("delete", left.slice(i, li).join(""));
    push("insert", right.slice(j, rj).join(""));
    push("same", left[li]);
    i = li + 1;
    j = rj + 1;
  }
  push("delete", left.slice(i, leftEnd).join(""));
  push("insert", right.slice(j, rightEnd).join(""));
  push("same", left.slice(leftEnd).join(""));
  return runs;
}

// What an element says, read the way this file reads the page everywhere else. A widget
// wanting the words in one of its own slots asks for them here rather than through
// `textContent`, because the two differ: the paint pass writes a hidden line into any text
// block that carries a comment, including blocks inside a widget, and `textContent` returns
// it. A suggestion labelled that way offered to accept “Retry three times. 1 comment”.
export const says = (el) => quoteFrom(textNodesUnder(el));
// The other question, and a different answer: what the *author* wrote here, with
// everything an upgrade generated left out. The version diff asks it because the base
// version it compares against has no generated nodes at all; a widget asks it to name
// one of its own parts, where `says` would hand back the widget's own declared labels
// along with the words — a picked row's mark is the page speaking, so it is in the
// reading a reviewer points at and out of the row's name.
export const wrote = (el) => quoteFrom(textNodesUnder(el, authored()));

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
// `holds` for what checking them means, and what it deliberately refuses to do.
// Anchors written before this carry none: their quote resolves only when it has a
// single candidate, since there is no evidence that can identify one repeated copy.
// The characters of raw[lo..hi) as segments, so a neighbourhood can be read back with the
// same function that wrote it down. Edges hold no character and are simply absent.
function spanOf(origin, lo, hi) {
  const out = [];
  for (let i = Math.max(0, lo); i < Math.min(origin.length, hi); i++) {
    const at = origin[i];
    if (!at) continue;
    const last = out.at(-1);
    if (last && last.node === at.node && last.end === at.offset)
      last.end = at.offset + 1;
    else out.push({ node: at.node, start: at.offset, end: at.offset + 1 });
  }
  return out;
}
// Context identifies a passage only when its neighbours are still exactly what they were.
// A partial match is not weak evidence for the right copy — it is evidence the page moved
// on, and acting on it is how a comment ends up somewhere it was never made: a version that
// rewrote the sentence beside the anchored copy left an untouched copy elsewhere matching
// better, and the comment followed it there. Demanding the whole stored context prevents
// that: without one exact contextual match, only a quote with a sole candidate resolves;
// repeated candidates detach rather than inheriting document order.
//
// Rare, not impossible. The bar is however much was stored, and the capture reads the
// neighbours out of the whole document — a section is a filter on where a passage may sit,
// not on what surrounds it — so both sides are full except against the document's own
// ends. Anchors written before context reached past the section carry a side clipped at
// that edge; they confirm at that shorter bar, which is the bar they were stored under.
//
// The bar is what the capture actually produces, not a number picked to fit: across every
// selection in the shipped examples, an unmodified page confirms its stored context in full.
//
// An empty side is the case worth stating, because reading it as an absent constraint is
// what sends a comment to a copy it was never made on. The capture reads the whole
// document, so a side comes out empty only where the passage had nothing at all beside it:
// the top or bottom of the page, the one place no capture can give two sides to. That is
// not a missing constraint but the tightest one there is, and it is checkable — a candidate
// confirms it by also having nothing there, which exactly one occurrence does. Refusing to
// read it that way handed the last copy's mark to the first.
const holds = ({ origin, fences }, at, want, before) => {
  // One character is all it takes to refute an empty side, and asking for none would answer
  // with none: doubling zero never grows.
  const there = neighbourhood(origin, fences, at, want.length || 1, before);
  if (!want) return there === "";
  return before ? there.endsWith(want) : there.startsWith(want);
};
// As much collapsed text as the stored context is long, however much raw text that takes.
// A fixed raw budget reads less than the capture wrote wherever whitespace runs dense — an
// indented line inside a <pre> — and the right occurrence then confirms none of its own
// neighbours. `want` is the stored string's own length rather than the cap the capture
// spent, because the capture counted code points and this counts code units: an emoji in
// the neighbourhood makes those different numbers, and a window short by even one
// character can never confirm, so a repeated anchor would detach despite unchanged
// context.
function neighbourhood(origin, fences, at, want, before) {
  const edge = before
    ? (fences.filter((f) => f <= at).at(-1) ?? 0)
    : (fences.find((f) => f >= at) ?? origin.length);
  for (let raw = want * 2; ; raw *= 2) {
    const lo = before ? Math.max(edge, at - raw) : at;
    const hi = before ? at : Math.min(edge, at + raw);
    const text = quoteFrom(spanOf(origin, lo, hi));
    if (text.length >= want || (before ? lo === edge : hi === edge)) return text;
  }
}
// What the page says, once, as one string with a way back to the nodes it came from. Built
// per pass rather than per anchor: every anchor a pass places is asking about the same
// document, and the pass is what fixes which document that is — resolving each against its
// own fresh reading would let two marks in one pass answer for two different pages, since a
// widget can upgrade between them. Forty threads on a 13k-character page also spent it
// forty times: 9.3ms of index building per pass, besides the forty tree walks feeding
// it, against 1.5ms for the one read that replaces them.
function pageText() {
  let raw = "";
  const origin = []; // origin[i] = {node, offset} for raw[i]; null for an edge
  const positions = new WeakMap(); // text node -> its offset-zero position in raw
  const fences = new Set();
  const segments = textNodesUnder(document.body);

  // Generated page-words that the registry does not model are their own passage
  // cells. Controls and the hidden comment count contain no accepted text and never
  // become fences; x-says spans are already present in the file-side reading.
  const dynamicWords = new WeakSet();
  for (const seg of segments) {
    const generated = seg.node.parentElement.closest("[data-cq-gen]");
    if (!generated) continue;
    const attr = generated.getAttribute("data-cq-said");
    const hostEntry = registry[generated.parentElement?.localName];
    const declared = attr && hostEntry?.["x-says"]?.[attr];
    if (!declared) dynamicWords.add(generated);
  }
  const cellOf = (node) => {
    for (let el = node.parentElement; el; el = el.parentElement) {
      if (dynamicWords.has(el)) return el;
      if (opaquePassageParts.has(el) || opaquePassageRoots.has(el)) return el;
    }
    return null;
  };

  let previousCell = null;
  let started = false;
  for (const seg of segments) {
    const cell = cellOf(seg.node);
    if (!started) {
      if (cell) fences.add(0);
      started = true;
    } else {
      if (cell !== previousCell && (cell || previousCell)) fences.add(raw.length);
      origin.push(null);
      raw += EDGE;
    }
    positions.set(seg.node, raw.length - seg.start);
    for (let i = seg.start; i < seg.end; i++) {
      origin.push({ node: seg.node, offset: i });
      raw += seg.node.data[i];
    }
    previousCell = cell;
  }
  if (previousCell) fences.add(raw.length);
  return { raw, origin, positions, fences: [...fences].sort((a, b) => a - b) };
}
const escape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
function findQuote(text, quote, anchor, within) {
  const { raw, origin } = text;
  const words = quote.trim().split(/\s+/).filter(Boolean);
  if (!words.length) return [];
  const pattern = new RegExp(
    words.map((w) => [...w].map(escape).join(`${EDGE}*`)).join(`[\\s${EDGE}]+`),
    "g",
  );
  // A unique exact-context occurrence wins. If no context survives, a sole quote
  // occurrence is still identifiable; two are not. Document order is not identity:
  // guessing the first copy after the intended one's neighbours changed quietly moves
  // a comment to words it was never made on. matchAll steps past each hit, so
  // overlapping occurrences of a quote that repeats inside itself are not candidates.
  const [pre, post] = [anchor.prefix ?? "", anchor.suffix ?? ""];
  const candidates = [];
  const exact = [];
  for (const at of raw.matchAll(pattern)) {
    const stop = at.index + at[0].length;
    if (
      within &&
      !(
        within.contains(origin[at.index].node) && within.contains(origin[stop - 1].node)
      )
    )
      continue;
    candidates.push(at);
    if (holds(text, at.index, pre, true) && holds(text, stop, post, false))
      exact.push(at);
  }
  const found =
    exact.length === 1
      ? exact[0]
      : exact.length === 0 && candidates.length === 1
        ? candidates[0]
        : null;
  // The characters the match covers, cut out of the index the same way a neighbourhood is —
  // walking the segments a second time to rebuild the span would be a second answer to
  // "which text is this", and the two disagree wherever an edge falls inside the match.
  return found ? spanOf(origin, found.index, found.index + found[0].length) : [];
}

// ---------- view continuity ----------
// Following a new version is a navigation, so without help the reader lands at the top
// of a fresh document mid-review. The passage they were reading rides across in
// sessionStorage — per-tab like unsent drafts, because a reading position belongs to a
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
// filtered to a section the text isn't in and can only ever fail — restore then falls back
// to the section, which doesn't absorb content added above the reader inside it.
function captureView() {
  const view = { v: VNUM, y: pageScroller.scrollTop };
  for (const block of document.querySelectorAll(TEXT_BLOCK)) {
    // [hidden] needs an explicit skip: hidden="until-found" resolves to
    // content-visibility, under which descendants still report real rects —
    // but what's behind an inactive tab isn't what the reader is reading.
    if (inChrome(block) || block.closest("[hidden]")) continue;
    const range = document.createRange();
    range.selectNodeContents(block);
    const rect = range.getBoundingClientRect();
    if (!rect.height || rect.bottom <= 42) continue; // 42 = banner height
    const section = block.closest("[id]");
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
const jumpBy = (dy, behavior = "instant") =>
  pageScroller.scrollBy({ top: dy, behavior });
function restoreView(view) {
  const text = pageText();
  const found = view.quote && resolveAnchor(view, text);
  if (found?.segments) {
    reveal(found.segments[0].node.parentElement); // the passage may sit behind a tab
    jumpBy(rangeOf(found.segments).getBoundingClientRect().top - view.quoteTop);
    return;
  }
  const section = resolveAnchor({ section: view.section }, text)?.element;
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
// The search always reads the whole document — the same text the capture wrote the
// neighbours from — and the section the anchor names filters where a candidate may sit.
// A section the page no longer has filters nothing, so the quote is still looked for
// everywhere, which is all a stale section ever meant.
// Which element an anchor names, asked in one place: the element it resolves to when it
// carries no quote, the subtree a candidate has to sit inside when it does, and the holder
// of the line saying a passage carries a comment are all this question.
const sectionOf = (anchor) =>
  anchor.section ? document.getElementById(anchor.section) : null;

// ---------- pointing at an item ----------
// Two gestures reach an item, and they serve different moments rather than splitting one.
// The chips are a correction — a reviewer who selected a card's words and meant the card
// is offered the enclosing chain, unasked, beside the button they are already looking at,
// so nobody has to know of them in advance. ⌥-click is direct aim: no selection, no
// chrome, and the only route to an item whose words are all inside controls. Both end in
// openOnItem, so they cannot come to write different anchors for the same intent. A
// third — a rule in the margin raised by hovering — was tried and cut: too strong for
// what it offered, and placed at the item's own left edge, which is the page's margin
// only for an item the page happens to have left-aligned.
//
// What both write is the anchor colloquy already has. A comment on an element is
// {section: <id>} with no quote — the shape a click on a diagram has made since the
// beginning — so none of this is a new representation, a new event field, or a second
// thing for a version to carry. What is missing is only the gesture, and how the panel
// says which item a thread is on.
//
// An item is an element the author gave an id, outside the runtime's own layer and
// outside the panel (a reply's frozen widget markup carries ids of its own). `version
// check` holds every id across versions, which is exactly why an anchor naming one
// survives a rewrite that takes a quote down with it.
const ITEM = "[id]:not(.cq-ui)";
// Innermost first: a card, then its column, then the board, then the section holding it.
// The chain is the answer to "which of these did you mean" — the reviewer is shown it
// rather than the runtime guessing a level for them.
function itemChain(node) {
  const chain = [];
  let at = node?.nodeType === 1 ? node : node?.parentElement;
  for (; at; at = at.parentElement)
    if (at.matches(ITEM) && !inChrome(at) && !inUi(at)) chain.push(at);
  return chain;
}
// What to call an item, in a word the reviewer is about to press. A widget names itself:
// its tag minus the prefix is already the word the vocabulary chose ("card", "option",
// "column"), so the twelfth widget gets a name here without core hearing about it.
//
// The page's own elements have no such word. A tag is markup rather than English, and the
// chips read "⬚ p" and "⬚ section" over ordinary prose — which names the thing to a
// browser and to nobody else. So HTML's tags get the nouns a reader would use, and an
// unlisted one falls back to its tag, which is worse than a word and better than nothing.
const HTML_WORDS = {
  p: "paragraph",
  li: "item",
  tr: "row",
  td: "cell",
  th: "cell",
  figure: "figure",
  blockquote: "quote",
  pre: "block",
  section: "section",
  article: "section",
  aside: "aside",
  ul: "list",
  ol: "list",
  dl: "list",
  table: "table",
  details: "note",
  h1: "heading",
  h2: "heading",
  h3: "heading",
  h4: "heading",
  h5: "heading",
  h6: "heading",
};
function itemWord(item) {
  if (!item) return "";
  const tag = item.tagName.toLowerCase();
  if (tag.startsWith("cq-")) return tag.slice(3);
  // A <pre> is a block of something and the something is in the markup: the documented
  // shape for source is <pre><code class="language-*">, and a <pre> without the <code> is
  // the shape for what isn't source — a transcript, a stack trace, command output. So the
  // word is read rather than assumed, and a reviewer who calls it a code block is offered
  // one.
  if (tag === "pre") return item.querySelector(":scope > code") ? "code" : "block";
  return HTML_WORDS[tag] ?? tag;
}
// The item's own opening words, read the way anchoring reads everything else — so a label
// a widget declared as the page speaking is in it and the runtime's own chrome (the hidden
// "2 comments" line) is not. Cut back to a word boundary and marked as cut, because a label
// ending mid-word reads as a quote that lost its tail rather than as a name for the thing.
const ITEM_SAYS_CAP = 52;
function itemSays(item) {
  if (!item || inChrome(item)) return "";
  const whole = quoteFrom(textNodesUnder(item));
  if ([...whole].length <= ITEM_SAYS_CAP) return whole;
  const short = cut(whole, 0, ITEM_SAYS_CAP);
  const at = short.lastIndexOf(" ");
  return (at > ITEM_SAYS_CAP / 2 ? short.slice(0, at) : short).trimEnd() + "…";
}
function resolveAnchor(anchor, text) {
  // An element anchor asks a different question — whether the section is still on the
  // reviewer's page — and the whole page is not an answer to it. Existence alone isn't
  // either: a decided element whose markup settles to nothing is present in the
  // document and absent from the screen, and an anchor held to it read as attached
  // while outlining nothing.
  if (!anchor.quote) {
    const section = sectionOf(anchor);
    return section && !settledAway(section) ? { element: section } : null;
  }
  const segments = findQuote(text, anchor.quote, anchor, sectionOf(anchor));
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
const NOTE = "cq-mark-note";
const marked = new Map(); // thread id -> (Range | Element)[]: the pass's record of what it drew
let pendingMarks = []; // the same record for the open composer's own passage
let pendingOutline = null; // the element the open composer outlines, owned by nobody else
// The item a control under the pointer would comment on, shown in the same outline
// before anything is committed. paintAnchors is the one thing that marks the page, so
// this is state it reads rather than a second painter.
let previewItem = null;
function previewOn(item) {
  if (previewItem === item) return;
  previewItem = item;
  paintAnchors();
}
const pointer = { x: -1, y: -1 }; // last seen, so a repaint can re-answer the hover
let hovering = null;
let hoverQueued = false;
const marksOf = (id) => marked.get(id) ?? [];
const allMarks = () => [...marked.values()].flat();
// What a reader who cannot see the paint is told. A highlight is glyphs, not an element, so
// it builds no accessibility node — where a <mark> wrapper was a `mark` node, the paint is
// nothing at all, and a passage carrying a comment reads exactly like one that doesn't.
// Neither relation ARIA offers brings it back on something not focusable: NVDA ignores
// aria-describedby there in browse mode and reports none of the labelling attributes on a
// bare p or div at all, VoiceOver reads it only on an interactive, image or landmark role,
// and aria-details is supported unevenly and says only that details exist. What every
// screen reader announces in every mode is text, so the fact is carried as text — one
// hidden, unselectable line inside whatever holds the mark, saying how many comments are
// on it.
//
// Coarser than the mark, and deliberately: it names the block a passage sits in rather than
// the passage, because naming the passage means wrapping it, and wrapping is what a redraw
// between a mousedown and its mouseup turns into a swallowed click. The panel still carries
// each thread's own quote. Written only where the text differs from what is already there,
// because a screen reader rebuilds its buffer on every mutation and this pass runs on every
// poll.
function noteMarks(noted) {
  for (const [holder, threadIds] of noted) {
    const note =
      holder.querySelector(`:scope > .${NOTE}`) ??
      holder.appendChild(offer("button", NOTE));
    note.cqThreads = threadIds;
    note.onclick = () => {
      setPanel(true);
      const id = note.cqThreads.find((threadId) =>
        threadsBox.querySelector(`:scope > .cq-thread[data-id="${threadId}"]`),
      );
      const thread =
        id && threadsBox.querySelector(`:scope > .cq-thread[data-id="${id}"]`);
      if (!thread) return;
      thread.focus({ preventScroll: true });
      thread.scrollIntoView({ behavior: SCROLL, block: "nearest" });
      scrollToThread(id);
    };
    const n = threadIds.length;
    const said = `${n} comment${n === 1 ? "" : "s"}`;
    if (note.textContent !== said) note.textContent = said;
  }
  for (const note of document.querySelectorAll(`.${NOTE}`))
    if (!noted.has(note.parentElement)) note.remove();
}

function paintAnchors() {
  if (!anchoringReady) return;
  for (const where of allMarks())
    if (where instanceof Element) where.classList.remove("cq-mark-el");
  pendingOutline?.classList.remove("cq-mark-el", PENDING);
  marked.clear();
  pendingOutline = null;

  const text = pageText(); // read once, for every anchor this pass places
  const posted = [];
  const noted = new Map(); // element -> ordered thread ids marking something inside it
  for (const t of buildThreads()) {
    if (t.resolved || !t.root.anchor) continue;
    const found = resolveAnchor(t.root.anchor, text);
    if (!found) continue;
    if (found.element) {
      found.element.classList.add("cq-mark-el");
      marked.set(t.root.id, [found.element]);
    } else {
      const ranges = found.segments.map((seg) => rangeOf([seg]));
      marked.set(t.root.id, ranges);
      posted.push(...ranges);
    }
    // Where the line goes: every block the passage crosses, so the reader of any of them
    // hears it — or, for a passage that sits in no block of its own, the element the
    // anchor names, which is where the runtime already puts chrome a widget has to live
    // with (a card's drag grip). Never the inline run or the body div in between, because
    // a widget reads those back as its own: cq-draft seeds the editor a reviewer types
    // into from its body div, and a line inside it is chrome in the text they send back.
    const blocks = found.element
      ? [found.element]
      : [...new Set(found.segments.map((seg) => blockAt(seg.node)))].filter(Boolean);
    for (const holder of blocks.length ? blocks : [sectionOf(t.root.anchor)])
      if (holder) noted.set(holder, [...(noted.get(holder) ?? []), t.root.id]);
  }

  // The composer's own passage, in the accent rather than the marker amber, so a draft
  // never reads as a posted comment. An element a thread already outlines keeps the posted
  // colour: there is one outline to give, and the thread's is the clickable one.
  //
  // Before the composer exists, the same outline answers "which of these am I about
  // to comment on". A blind user offered `card`, `column` and
  // `board` had no way to tell them apart, because the outline only arrived after the
  // click — so the chain the chips exist to offer could not actually be chosen between.
  // What a control would take is the same fact as what the composer holds, one step
  // earlier, so it is the same paint rather than a second one.
  const draft =
    composerOpen && pendingAnchor
      ? resolveAnchor(pendingAnchor, text)
      : previewItem && !settledAway(previewItem)
        ? { element: previewItem }
        : null;
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
  CSS.highlights.set(
    PENDING,
    Object.assign(new Highlight(...pending), { priority: 2 }),
  );
  noteMarks(noted); // and the same fact for a reader who can't see any of it
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
      : "This passage can't be identified in the version you're viewing";
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
  node.style.top =
    Math.max(48, Math.min(top, innerHeight - node.offsetHeight - 8)) + "px";
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
    where instanceof Range
      ? [...where.getClientRects()]
      : [where.getBoundingClientRect()],
  );
  const box = composer.getBoundingClientRect();
  // Vertically only: the document never scrolls sideways and body's margin keeps it clear
  // of the panel, so off-screen means scrolled past, and a mark scrolled past is not one
  // this box is standing on.
  const onScreen = (r) => r.bottom > 48 && r.top < innerHeight;
  const behindBox = (r) =>
    r.left >= box.left &&
    r.right <= box.right &&
    r.top >= box.top &&
    r.bottom <= box.bottom;
  // A passage and a thing want different rules here, because
  // they are read differently. Covering the tail of a quote is fine — the reviewer has read
  // it, and the mark still names where it starts. A card, a column, a metric is judged as
  // one object, so a box standing anywhere on it is a box between them and the thing they
  // are writing about. ⌥-click made that plain by opening the composer under the pointer,
  // which is by definition inside what was clicked.
  const whole = pendingMarks.some((where) => where instanceof Element);
  const touching = (r) =>
    r.left < box.right &&
    box.left < r.right &&
    r.top < box.bottom &&
    box.top < r.bottom;
  const clear = whole
    ? !rects.some((r) => onScreen(r) && touching(r))
    : rects.some((r) => onScreen(r) && !behindBox(r));
  if (!rects.length || clear) return;
  const below = Math.max(...rects.map((r) => r.bottom)) + 8;
  const above = Math.min(...rects.map((r) => r.top)) - box.height - 8;
  if (below + box.height <= innerHeight - 8) return place(composer, left, below);
  if (above >= 48) return place(composer, left, above);
  // Neither end has room, which a tall thing reaches easily: a board column is most of the
  // viewport before the box's own height is counted, and place()'s clamp would haul the box
  // back over it — the very thing this is here to stop. So go beside instead. The document
  // is one column with margin either side, and that margin is the room a box this size
  // wants; the side is chosen rather than clamped, for the reason the fab's chips are.
  const rightOf = Math.max(...rects.map((r) => r.right)) + 8;
  const leftOf = Math.min(...rects.map((r) => r.left)) - box.width - 8;
  place(composer, rightOf + box.width <= rightEdge() ? rightOf : leftOf, top);
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
  // The neighbours come from the same indexed reading the search uses and stop at
  // the same opaque-widget fences as the file-side capture. The browser knows words
  // a module generated and may quote them; it does not pretend the file can confirm
  // context across their seam.
  const segments = segmentsIn(range);
  const whole = quoteFrom(segments);
  const quote = cut(whole, 0, QUOTE_CAP);
  const reading = pageText();
  const first = segments[0];
  const last = segments.at(-1);
  const start = first ? reading.positions.get(first.node) + first.start : 0;
  const stop = last ? reading.positions.get(last.node) + last.end : start;
  const prefix = cut(
    neighbourhood(reading.origin, reading.fences, start, CONTEXT, true),
    -CONTEXT,
    Infinity,
  );
  const suffix = cut(
    neighbourhood(reading.origin, reading.fences, stop, CONTEXT, false),
    0,
    CONTEXT,
  );
  // Only what there is, and only what follows the quote. A passage against the document's
  // own edge has no neighbour on that side, and writing that down as an empty string puts
  // a field in the event that never says anything. A quote cut to the cap ends inside the
  // selection, so what follows it is the rest of the selection rather than the text after
  // it — read from there, the suffix still names the place the search will look.
  // trimStart because the search reads its side through quoteFrom, which trims, and `whole`
  // is already collapsed so there is at most one space to lose. Without it, a cut landing
  // just before a space stored a suffix beginning with one — a character no occurrence can
  // produce, so every one failed at the first comparison.
  const tail =
    quote === whole
      ? suffix
      : cut(cut(whole, QUOTE_CAP, Infinity).trimStart(), 0, CONTEXT);
  return {
    section,
    quote,
    ...(prefix && { prefix }),
    ...(tail && { suffix: tail }),
  };
}

// Controls the page is standing on its own account, as against the ones in the runtime's
// layer: a reply's widget is markup frozen in the log, and the layer's own buttons are
// what floating chrome is allowed to sit beside. `data-cq-offer` is what makes a thing
// pressable (`offer`), so this asks after any widget's controls without naming one.
const pageControls = () =>
  [...document.querySelectorAll("[data-cq-offer]")].filter((c) => !inChrome(c));

// The 💬 button carries the anchor it would open a composer on, so raising it and acting
// on it can't come to different conclusions about what the reader picked. Visibility is
// derived from that anchor and never read back off the stylesheet.
const beside = (rect) => [rect.right + 6, rect.top - 6];
// It has one more thing to stay clear of, and it is the same kind of thing the composer's
// mark is: a control standing on the page. The button floats and they don't. A selection
// runs to the column's right edge on any line it fills, so `beside` puts the button in
// the margin — which is where a suggestion hangs the row deciding the change that
// selection just covered. The reviewer's own gesture then hid the Accept they were
// reaching for, and the press that would have dismissed the button was the press it was
// covering.
//
// Down, and past each in turn, because the margin runs down the page: clearing one row
// can land on the next, and walking a sorted list is the step the rows themselves take to
// nudge apart. place()'s clamp still has the last word, so a button with nowhere left to
// go keeps the best spot rather than leaving the screen.
function placeFab(left, top) {
  place(fab, left, top);
  const box = fab.getBoundingClientRect();
  const sharing = pageControls()
    .map((c) => c.getBoundingClientRect())
    .filter((r) => r.width && r.left < box.right && box.left < r.right)
    .sort((a, b) => a.top - b.top);
  let y = box.top;
  for (const r of sharing) if (r.top < y + box.height && y < r.bottom) y = r.bottom + 6;
  if (y !== box.top) place(fab, left, y);
}
let fabAnchor = null;
// The chips state everything else this gesture could be about — each item
// enclosing the passage, innermost first. Whatever the button itself already carries is
// dropped from them, so no level is offered twice. Capped, because a card inside a column
// inside a board inside a section is already four and the reviewer is choosing rather than
// browsing. Placed off the button's own box after it has been placed, so the chips follow
// wherever placeFab moved it to clear the page's controls.
const CHAIN_CAP = 3;
function showFab(anchor, left, top, items = []) {
  fabAnchor = anchor;
  fab.style.display = anchor ? "block" : "none";
  fabChain.textContent = "";
  fabChain.style.display = "none";
  if (!anchor) return;
  placeFab(left, top);
  const carried = anchor.quote ? null : anchor.section;
  const chips = items.filter((item) => item.id !== carried).slice(0, CHAIN_CAP);
  if (!chips.length) return;
  for (const item of chips) {
    const chip = el("button", "cq-btn cq-fab-item", `⬚ ${itemWord(item)}`);
    chip.title = `Comment on this ${itemWord(item)} — ${itemSays(item) || item.id}`;
    chip.onclick = () => openOnItem(item, fabChain.getBoundingClientRect());
    // Which of the chain this chip means, shown before it is pressed rather than after.
    chip.onmouseenter = () => previewOn(item);
    chip.onmouseleave = () => previewOn(null);
    chip.onfocus = () => previewOn(item);
    chip.onblur = () => previewOn(null);
    fabChain.append(chip);
  }
  fabChain.style.display = "flex";
  placeChain();
}
// Where the chips go, which is anywhere except on top of the button they are beside.
// `place`'s clamp is the wrong tool here: it keeps a box on screen by sliding it left,
// and a row of chips slid left lands on the 💬 and eats the press aimed at it. So the
// side is chosen rather than clamped — right of the button, else left of it, else under
// it — and only the vertical is clamped, where sliding covers nothing.
function placeChain() {
  const box = fab.getBoundingClientRect();
  const width = fabChain.offsetWidth;
  const right = box.right + 6;
  const left = box.left - width - 6;
  const [x, y] =
    right + width <= rightEdge()
      ? [right, box.top]
      : left >= 8
        ? [left, box.top]
        : [Math.max(8, Math.min(box.left, rightEdge() - width)), box.bottom + 6];
  fabChain.style.left = x + "px";
  fabChain.style.top =
    Math.max(48, Math.min(y, innerHeight - fabChain.offsetHeight - 8)) + "px";
}
// One way in to the composer for all three routes, so they cannot come to write different
// anchors for the same press.
function openOnItem(item, from) {
  showFab(null);
  previewOn(null); // the composer's own mark takes over from here
  openComposer({ section: item.id }, "", from.left, from.top);
}
// The button follows the selection. What counts as one is measured on the quote it would
// store, not on the selection's own toString(): those are different strings, and gating on
// the one the reader sees while storing the one the document holds lets a two-character
// quote through behind a rendered three-character selection — a quote short enough to match
// almost anywhere.
const MIN_QUOTE = 3;
// A selection of the page's own words, as against none, a bare caret, or one made inside
// the runtime's own layer. That is the line between a reviewer reaching for a passage and
// one working the chrome, and it is the question every caller here is really asking.
const pageSelection = () => {
  const sel = getSelection();
  return sel && !sel.isCollapsed && !inUi(sel.anchorNode) ? sel : null;
};
// What the button is on, decided here alone. The selection is read fresh; a visual find —
// a clicked diagram or image, which has no text to select — comes in from the click that
// found it, and a qualifying selection outranks it. The last branch is why order between
// that click and the update queued behind its mouseup never matters: no selection speaks
// for an element anchor, so the selection's absence takes down only a quote, and the
// queued re-decide lands on the same outcome.
function updateFab(visual) {
  if (!anchoringReady) {
    showFab(null);
    return false;
  }
  const sel = pageSelection();
  const anchor = sel ? selectionAnchor(sel) : null;
  if (anchor?.quote.length >= MIN_QUOTE)
    showFab(
      anchor,
      ...beside(sel.getRangeAt(0).getBoundingClientRect()),
      itemChain(sel.getRangeAt(0).commonAncestorContainer),
    );
  else if (visual)
    showFab(
      { section: visual.id },
      visual.x + 6,
      visual.y - 40,
      itemChain(document.getElementById(visual.id)),
    );
  else if (fabAnchor?.quote) showFab(null);
  return true;
}
// Where the pointer stopped is not the question; where the selection is, is. The guard
// exists so a mouseup inside the runtime's layer — a click in the panel, the composer —
// can't re-decide the button out from under an open draft. A drag that ends on a widget's
// control is the opposite case: the reviewer was selecting that control's label, and a
// tab's name runs to within a few pixels of the strip button's padding, so the mouseup
// lands on chrome while the selection is the page's.
document.addEventListener("mouseup", (ev) => {
  if (inUi(ev.target) && !pageSelection()) return;
  setTimeout(updateFab);
});
// Selections made from the keyboard (shift-arrows, ⌘A) deserve the same button. Typing in
// a box never does, whatever is selected elsewhere.
document.addEventListener("keyup", (ev) => {
  if (editable(ev.target)) return;
  if (inUi(ev.target) && !pageSelection()) return;
  setTimeout(updateFab);
});
document.addEventListener("mousedown", (ev) => {
  if (!ev.target.closest?.(".cq-fab, .cq-fab-chain, .cq-composer")) {
    showFab(null);
    // Keep a composer that holds unsent text open so a stray click can't drop it;
    // Cancel discards explicitly, and the draft is persisted regardless. Asked only of a
    // composer that is up, so an ordinary press in the page repaints nothing.
    if (composerOpen && !composerInput.value) hideComposer();
  }
  if (helpOpen && !ev.target.closest?.(".cq-help")) showHelp(false);
});

// What a click on the page means, decided once. A mark under the pointer opens its thread;
// otherwise a diagram or image is a find handed to updateFab, which raises the same 💬
// button on an element anchor — the id the visual lives under — unless a selection
// outranks it.
//
// Once, because the hit-test reads layout and opening the panel rewrites it. Two handlers
// each asking `markAt` looked independent and were not: the first one's setPanel() reflowed
// the document out from under the second, which then missed the very mark it had just
// opened and raised the comment button on top of it — leaving an element anchor set, which
// midComposition() reads, so the page quietly stopped following new versions. The rule this
// file already carries covers it: a guard that reads state another function wrote is a sign
// the two are one function.
// What a click anchors on whole, because there is no text in it to select: the page's
// own pictures, and every widget that declares it renders as one.
const visualSel = () =>
  [...tagsDeclaring((e) => e["x-visual"]), "svg", "img", "figure"].join(",");
// While ⌥ is held the page shows what a click would take — the item under
// the pointer wears the same outline a chip's hover paints, so the chord answers "which"
// the way every other route does rather than asking the reviewer to click and find out.
// `aiming` is the state and the class is a rendering of it; nothing reads the class back.
//
// It comes off on blur as well as on keyup, because the chord that switches windows takes
// the keyup with it, and a page left armed under nobody's hand is a claim the reviewer
// cannot dismiss.
let aiming = false;
// What the pointer is over, asked of the page rather than of an event, so pressing the key
// without moving the mouse answers too — the reviewer holds ⌥ to find out what they would
// get, and the answer cannot wait for them to jiggle the mouse first.
function aimedItem() {
  if (composerOpen || pointer.x < 0) return null;
  const at = document.elementFromPoint(pointer.x, pointer.y);
  return at && !inChrome(at) ? (itemChain(at)[0] ?? null) : null;
}
function setAiming(on) {
  aiming = on;
  document.body.classList.toggle("cq-aiming", on);
  previewOn(on ? aimedItem() : null);
}
addEventListener("keydown", (ev) => ev.key === "Alt" && setAiming(true));
addEventListener("keyup", (ev) => ev.key === "Alt" && setAiming(false));
addEventListener("blur", () => setAiming(false));
document.addEventListener("mousemove", () => aiming && previewOn(aimedItem()));
document.addEventListener("click", (ev) => {
  if (inUi(ev.target)) return;
  // ⌥-click means the item under the pointer, whatever it holds. It costs
  // the page no chrome and the reviewer no selection, and it reaches an item whose words
  // are all inside a control. What it costs is discoverability, which the cursor answers
  // as far as a modifier can: while the key is down the pointer says a click will aim.
  if (ev.altKey) {
    const item = itemChain(ev.target)[0];
    if (!item) return;
    ev.preventDefault();
    return openOnItem(item, { left: ev.clientX + 6, top: ev.clientY - 40 });
  }
  const threadId = markAt(ev.clientX, ev.clientY);
  if (threadId) return revealThread(threadId);
  if (ev.target.closest?.("a")) return;
  const sel = visualSel();
  let visual = ev.target.closest?.(sel);
  if (!visual) return;
  // Outermost visual: a rendered diagram's inner svg carries a generated id;
  // the anchor belongs to the widget (or figure) that holds it.
  while (visual.parentElement?.closest(sel)) visual = visual.parentElement.closest(sel);
  const id = visual.closest("[id]:not(.cq-ui)")?.id;
  if (!id) return;
  updateFab({ id, x: ev.clientX, y: ev.clientY });
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
  hint: () => (suggestCheck.checked ? "Replacement text" : "Your comment"),
  sendBtn: composerSend,
  save: saveComposerDraft,
  send: async (text) => {
    const event = { kind: "comment", version: VNUM, anchor: pendingAnchor, text };
    if (suggestCheck.checked) event.suggestion = true;
    const sent = await post(event);
    if (!sent) return;
    closeComposer();
    revealThread(sent.id);
    // The composer this was sent from is gone with the send; the thread it became
    // carries the same conversation, so its reply box is where typing continues.
    threadsBox
      .querySelector(`.cq-thread[data-id="${sent.id}"] textarea`)
      ?.focus({ preventScroll: true });
  },
});
// The composer's suggest-mode rendering — button label and placeholder — derived
// from the checkbox in one place, so the three paths that set the checkbox
// (toggle, open, close) can't each restate half of it. The placeholder itself is
// wireInput's to write; syncComposer repaints it from the hint above.
function syncSuggestMode() {
  composerSend.textContent = suggestCheck.checked ? "Suggest" : "Comment";
  syncComposer();
  paintLine(); // the line's send row says which of the two the box will do
}
suggestCheck.onchange = () => {
  // Entering suggestion mode seeds the box with the passage to edit in place.
  if (suggestCheck.checked && !composerInput.value.trim() && pendingAnchor?.quote) {
    composerInput.value = seededQuote = pendingAnchor.quote;
    syncComposer();
  }
  syncSuggestMode();
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
  paintLine();
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
  syncSuggestMode();
  suggestRow.style.display = anchor?.quote ? "flex" : "none";
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
  syncSuggestMode();
  pendingAnchor = null;
  saveDraft("composer", "");
  hideComposer();
}

// The button opens the composer where it stands, on the anchor it is carrying. Where it
// stands, and not where it was asked for: placement moves it — down past the controls it
// would cover, and off the viewport's edges — so the two are no longer the same point,
// and handing on the asked-for one put the composer straight back over the row the button
// had just stepped off.
fab.onclick = () => {
  if (!fabAnchor) return;
  const anchor = fabAnchor;
  const { left, top } = fab.getBoundingClientRect();
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
    const sent = await post({ kind: "comment", version: VNUM, text });
    if (!sent) return;
    generalInput.value = "";
    saveDraft("general", "");
    revealThread(sent.id);
    generalInput.focus({ preventScroll: true }); // both send routes end where typing was
  },
});

approveBtn.onclick = () => post({ kind: "done", version: VNUM, text: "Looks good" });
endReviewBtn.onclick = () => post({ kind: "close", version: VNUM });

// ---------- keyboard ----------
// One table drives both the dispatcher and the "?" overlay, so help can't drift
// from behavior. Rows without a key are display-only — focus-scoped (the thread's
// Enter, ⌘⏎) or dispatched before the table (Esc, the one key that crosses typing
// contexts); rows without `does` ride the previous row's label (k under "j / k");
// `line` is the row's word in the key line, and `when` gates the row whole — the
// line row and the press alike, so a key the line wouldn't show keeps its native
// meaning instead of half-working (j over no threads used to open an empty panel).
// The leader: g arms a short window in which a digit is an address — the nth open
// thread's reply box, in the order j/k walk. While armed each addressable box wears
// its digit as a chip and the key line shows the pending chord (both renderings of
// leaderTimer, never read back), so the armed window is visible wherever the
// reviewer is looking, panel open or closed. A digit consumes the window; any other
// key disarms it and keeps its ordinary meaning, so a mistyped g costs nothing; Esc,
// the timeout, and focus entering a box disarm too.
const LEADER_MS = 1500;
let leaderTimer = null;
function setLeader(on) {
  // Armed over a control that has claimed Escape (a grabbed grip), one press would
  // have two owners — the control consumes the key while the chord promises its
  // cancel — so the leader refuses to arm there at all, the drift scene() exists
  // to make impossible.
  if (on && claimsEsc(document.activeElement)) return;
  const was = Boolean(leaderTimer);
  if (leaderTimer) clearTimeout(leaderTimer);
  leaderTimer = on ? setTimeout(() => setLeader(false), LEADER_MS) : null;
  panel.classList.toggle("cq-leader-armed", on);
  // The chips are the eye's copy; the arming itself is spoken, or the mode change
  // is silent to exactly the reviewer who can't see them.
  if (on && !was) announce("Reply to thread — press 1 to 9, Escape cancels");
  paintLine();
}
// What a digit does with the window: stepThread-to-nth and its Enter in one press.
function replyTo(n) {
  if (!panelOpen) setPanel(true);
  const thread = threadsBox.querySelectorAll(":scope > .cq-thread")[n - 1];
  const ta = thread?.querySelector("textarea");
  if (!ta) return;
  ta.focus({ preventScroll: true });
  thread.scrollIntoView({ behavior: SCROLL, block: "nearest" });
  scrollToThread(thread.dataset.id);
}

const KEYS = [
  {
    key: "c",
    label: "c",
    does: "Comment on the selection — or toggle the panel",
    line: "comment",
    run: commentKey,
  },
  // No key of its own. Holding the key shows what it
  // would take, so what the reference is still the only place for is that the key exists.
  { label: "⌥ click", does: "Comment on the item under the pointer, whole" },
  // The selection c acts on has a keyboard author, and it is the browser's: caret
  // browsing. Unnamed, the keyboard story ended at "the selection" and quietly
  // assumed a mouse — the blind drive's finding. Display-only, like ⌥ click: the
  // key is the browser's to own, this row only says it exists.
  {
    label: "F7",
    does: "Caret browsing (the browser's): select text by keyboard, then c",
  },
  { key: "d", label: "d / u", does: "Half a page down / up", run: () => stepPage(0.5) },
  { key: "u", run: () => stepPage(-0.5) },
  {
    key: "j",
    label: "j / k",
    does: "Next / previous open thread",
    line: "threads",
    when: () => threadAddress.size > 0,
    run: () => stepThread(1),
  },
  { key: "k", run: () => stepThread(-1) },
  { label: "Enter", does: "On a focused thread: write a reply" },
  {
    key: "g",
    label: "g 1–9",
    does: "Reply to the nth open thread",
    line: "reply",
    when: () => threadAddress.size > 0,
    run: () => setLeader(true),
  },
  {
    key: "v",
    label: "v",
    does: "Highlight changes since the previous version",
    run: () => diffBase && diffBtn.onclick(),
  },
  {
    key: "[",
    label: "[ / ]",
    does: "Older / newer version",
    run: () => stepVersion(-1),
  },
  { key: "]", run: () => stepVersion(1) },
  { key: "?", label: "?", does: "This key reference", line: "keys", run: toggleHelp },
  {
    label: "Esc",
    does: "Back out one layer: an armed g, help, composer, reply, panel",
  },
  { label: SEND_KEYS, does: "Send, in the focused composer" },
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
  if (ev.metaKey || ev.ctrlKey || ev.altKey || editable(ev.target)) {
    if (leaderTimer) setLeader(false); // any key ends the window, chords included
    return;
  }
  if (leaderTimer) {
    setLeader(false);
    if (/^[1-9]$/.test(ev.key)) {
      ev.preventDefault();
      return replyTo(+ev.key);
    }
    // Any other key disarms and falls through to its ordinary meaning: g j is a
    // thread step, and g g re-arms.
  }
  // Help is a scope: while the overlay is up the table stands down — ? toggles it,
  // Esc (above) closes it. A focused control's own keys stay its own, here as
  // everywhere; the overlay holds focus on open, so reaching one takes a deliberate
  // Tab out.
  if (helpOpen && ev.key !== "?") return;
  const bound = KEYS.find((b) => b.key === ev.key);
  if (!bound || (bound.when && !bound.when())) return;
  ev.preventDefault();
  bound.run();
});

// A focus move is the one scope change no state writer sees, so it repaints the
// line itself; focus entering a box, or a control that claims Escape, also disarms
// the leader — a digit typed in a box is text, and a chip left blooming would
// promise a cancel the control would consume.
document.addEventListener("focusin", () => {
  const active = document.activeElement;
  if (leaderTimer && (editable(active) || claimsEsc(active))) setLeader(false);
  paintLine();
});
document.addEventListener("focusout", () => paintLine());

// Escape runs the rung scene() returns — the ladder's one definition, shared with
// the key line, so what Esc promises and what it does cannot drift.
function escapeKey() {
  scene().esc?.out();
}

// The current keyboard scope, top layer first: what the next press can do (rows),
// and what Escape backs out of (esc — null where Escape deliberately does nothing:
// an authored input outside the panel keeps its own Escape, and a widget control
// that claims the key consumes it before the dispatcher looks). Backing out of a
// reply returns focus to its thread, so Esc then Enter round-trips; out of the
// general box, to the list, so j/k walk on from where the backing-out started;
// drafts are kept at every rung.
function scene() {
  const active = document.activeElement;
  if (leaderTimer)
    return {
      chord: "g",
      rows: [["1–9", "reply to thread"]],
      esc: { says: "cancel", out: () => setLeader(false) },
    };
  if (helpOpen)
    return { rows: [], esc: { says: "close help", out: () => showHelp(false) } };
  if (composerOpen)
    return {
      rows:
        active === composerInput
          ? [[SEND_KEYS, suggestCheck.checked ? "suggest" : "comment"]]
          : [],
      esc: {
        says: "close — draft kept",
        out: () => {
          hideComposer();
          showFab(null);
        },
      },
    };
  if (editable(active)) {
    if (!panel.contains(active)) return { rows: [], esc: null };
    const thread = active.closest(".cq-thread");
    return {
      rows: [[SEND_KEYS, "send"]],
      esc: thread
        ? {
            says: "back to thread",
            out: () => {
              active.blur();
              thread.focus();
            },
          }
        : {
            says: "back to list",
            out: () => {
              active.blur();
              threadsBox.focus();
            },
          },
    };
  }
  // The thread div itself, j/k's target — not a control inside it, whose Enter is
  // its own press and must not be promised as "reply"; nor a resolved thread,
  // which has no reply box for Enter to reach. The j/k row is the KEYS entry's
  // own, not a restatement free to drift from it.
  if (active?.classList?.contains("cq-thread")) {
    const jk = KEYS.find((b) => b.key === "j");
    return {
      rows: [
        ...(active.querySelector(":scope > .cq-compose") ? [["Enter", "reply"]] : []),
        [jk.label, jk.line],
      ],
      esc: { says: "close comments", out: () => setPanel(false) },
    };
  }
  return {
    rows: KEYS.filter((b) => b.line && (!b.when || b.when())).map((b) => [
      b.label,
      b.line,
    ]),
    esc: panelOpen ? { says: "close comments", out: () => setPanel(false) } : null,
  };
}

// The key line's paint, coalesced to a frame: a focus move is a focusout then a
// focusin, and painting between them would flash the scope of nowhere.
let linePending = false;
function paintLine() {
  if (linePending) return;
  linePending = true;
  requestAnimationFrame(() => {
    linePending = false;
    renderLine();
  });
}
function renderLine() {
  const s = scene();
  // A focused control's own declaration outranks the scope's rows. Under a chord or
  // the overlay the scope's promise takes the line instead: the leader refuses to
  // arm over a control that claims Escape, so the chord's cancel is true, and other
  // control keys keep their meaning without the line narrating them.
  const hinted = s.chord || helpOpen ? null : hintFor(document.activeElement);
  const rows = hinted ?? s.rows;
  keylineEl.textContent = "";
  const chip = (key, word, armed) => {
    const span = el("span", "cq-key");
    const kbd = document.createElement("kbd");
    if (armed) kbd.className = "armed";
    // One spelling in this position, whatever the declaration wrote: the overlay
    // says "Esc" in its own voice, the line says "esc" in its.
    kbd.textContent = key === "Esc" ? "esc" : key;
    span.append(kbd);
    if (word) span.append(el("span", "", word));
    keylineEl.append(span);
  };
  if (s.chord) chip(s.chord, "", true);
  for (const [key, word] of rows) chip(key, word);
  // A hint's own Esc row outranks the ladder's chip: the control consumes the
  // press, so the rung is not what this press would do.
  if (s.esc && !rows.some(([key]) => key.toLowerCase() === "esc"))
    chip("esc", s.esc.says);
}
paintLine();

// c goes where commenting happens: a live selection gets the composer (what the
// floating button does), an element click's pending 💬 gets that, and otherwise
// the panel toggles — focusing the general box on open.
function commentKey() {
  if (!anchoringReady && pageSelection()) return;
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

// d and u step the reader half a page down and up — less's pair, and half a page rather
// than a whole one so the lines they were reading are still on screen to read on from.
// The browser's own keys are left to the browser (Space, Home/End, PageUp/Down all reach
// it untouched, and a test pins that); these are the runtime's.
//
// They move the region the reader's own scrolling moves, which under a covering sheet is
// its thread list rather than the page behind it — the rule syncLayout already states
// for the wheel, and a key is no different. Scrolling a page nobody can see reads to the
// reviewer as the key doing nothing, and then the document is somewhere else when the
// sheet closes.
//
// The destination is carried rather than measured afresh, because scrollBy measures from
// where the glide has got to and not from where it is going: two presses 40ms apart move
// 461px of a 900px page, so the half the reader believes they passed is still ahead of
// them, with nothing on screen to say it was skipped. scrollend hands the destination
// back whenever the region comes to rest, whoever moved it, so a press only ever extends
// a move still in flight and one made after the reader took the page somewhere themselves
// starts from where they left it. It is clamped, so pressing on at the foot of the page
// banks no debt for u to press back through.
let scrollGoal = null;
for (const region of [pageScroller, threadsBox])
  region.addEventListener("scrollend", () => (scrollGoal = null));
function stepPage(fraction) {
  const box = panelCovers ? threadsBox : pageScroller;
  const from = scrollGoal?.box === box ? scrollGoal.top : box.scrollTop;
  const top = Math.max(
    0,
    Math.min(box.scrollHeight - box.clientHeight, from + fraction * box.clientHeight),
  );
  scrollGoal = { box, top };
  box.scrollTo({ top, behavior: SCROLL });
}

// [ and ] step versions with the picker's own pin semantics.
function stepVersion(dir) {
  const at = versions.indexOf(VNUM);
  const next = at === -1 ? null : versions[at + dir];
  if (next) goVersion(next);
}

// Whether the overlay is up, and the only thing that decides it: the class is
// a rendering of this, never read back — the same contract composerOpen keeps,
// which this overlay used to break with three writers and two classList reads.
let helpOpen = false;
function showHelp(open) {
  helpOpen = open;
  if (open) {
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
    for (const { title, rows } of helpSections.values())
      helpEl.append(el("h3", "", title), table(rows));
  }
  helpEl.classList.toggle("open", open);
  if (open) helpEl.focus({ preventScroll: true });
  paintLine();
}
function toggleHelp() {
  showHelp(!helpOpen);
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
  showNews(acceptAllBtn, Boolean(n));
  acceptAllBtn.textContent = `✓ Accept all (${n})`;
}
// A decision also changes what text the page has — the retired slot leaves it
// (`quotable`) — so the marks are repainted from the same signal, and a comment
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
  }
};

// ---------- version diff ----------
// "Changes since vN": blocks (paragraphs, list items, widget items) whose text
// isn't present in the base version get a tinted marker, so re-reviewing a
// revision is cheap. Block-level and additions-only — deleted text has no home
// to mark — and a widget that renders its own body is opaque to it. The base is
// the previous published version.
//
// Which blocks and which widgets is the registry's answer both times, so a widget added
// to the vocabulary diffs on the strength of its entry: a widget item whose content
// model is prose is a block of the page's prose the same way a paragraph is.
const diffBlockSel = () =>
  [
    TEXT_BLOCK,
    "aside",
    ...tagsDeclaring((e) => e["x-parent"] && (e["x-content"] ?? "prose") === "prose"),
  ].join(",");
// Opaque: a widget whose upgrade renders its data body, so the text on screen is the
// module's and can't compare; and one whose slots a decision retires, which holds two
// versions of one passage and is already its own mark. Plus svg, drawn by either.
const diffOpaqueSel = () =>
  [
    ...tagsDeclaring(
      (e) => e["x-upgrade"] && !e["x-verbatim"] && e["x-content"] === "data",
    ),
    ...new Set(
      tagsDeclaring((e) => e["x-retired-when"]).map((tag) => registry[tag]["x-parent"]),
    ),
    "svg",
  ].join(",");
let diffBase = null;
let diffOn = false;
const diffMarked = [];
// A block's key is its *authored* text (`wrote`), which is why that reading exists: it
// drops even the labels anchoring reads as the page's own words, because the base
// version is parsed unupgraded and holds none of them.
function diffBlocks(root) {
  const pairs = [];
  const [blocks, opaque] = [diffBlockSel(), diffOpaqueSel()];
  for (const b of root.querySelectorAll(blocks)) {
    if (inChrome(b) || b.closest(opaque)) continue;
    if (b.querySelector(blocks)) continue; // leaf blocks only, or nesting double-marks
    const key = wrote(b);
    if (key) pairs.push([b, key]);
  }
  // Opaque widgets key by identity, not body: an upgrade rewrote the live body,
  // so text can't compare — but a widget the base didn't have still marks.
  for (const w of root.querySelectorAll(opaque)) {
    // parentElement, not w itself: an svg a widget rendered stays its widget's.
    if (inChrome(w) || w.parentElement?.closest(opaque)) continue;
    pairs.push([w, ` ${w.tagName}#${w.id}`]);
  }
  return pairs;
}
async function applyDiff(baseVersion) {
  const baseName = `v${baseVersion}.html`;
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
  // The state half: block keys catch words, and a pure state change — a card
  // in a different column, a pick on a different option — has no text of its
  // own. Compare declared facets instead: the base version's state (its markup
  // plus the fold as of it) against the live DOM, which already wears the
  // current fold. Body facets are words and the block keys above own them.
  const baseFold = stateFold(baseVersion);
  for (const [tag, spec] of stateSpecs()) {
    if (!spec.record || spec.record.kind === "body") continue;
    for (const widget of document.body.querySelectorAll(tag)) {
      if (inChrome(widget) || quoted(widget)) continue;
      const units =
        spec.unit === "widget" || !spec.unit
          ? widget.id
            ? [widget]
            : []
          : [...widget.querySelectorAll(`${spec.record.within} > [id]`)];
      for (const el of units) {
        const baseEl = doc.getElementById(el.id);
        if (!baseEl) continue; // new to this version: the content half marks it
        const before = baseFold.has(el.id)
          ? foldedFacet(baseFold.get(el.id).e, spec.record)
          : domFacet(baseEl, spec.record);
        const now = domFacet(el, spec.record);
        if (before === now) continue;
        // The element the change reads on: the option now picked, or the moved
        // card itself.
        const target =
          (spec.record.kind === "attribute" && now && document.getElementById(now)) ||
          el;
        if (!target.classList.contains("cq-ins-block")) {
          target.classList.add("cq-ins-block");
          diffMarked.push(target);
        }
      }
    }
  }
  // Container widgets surface marks their panels hide (cq-tabs badges each tab).
  document.dispatchEvent(new CustomEvent("cq-diff"));
  return diffMarked.length;
}
// Whether the diff is showing, and the only thing that decides it: the button's
// class and the page's marks are renderings of diffOn, not a second and third
// copy of it.
function setDiff(on) {
  diffOn = on;
  diffBtn.classList.toggle("on", on);
  diffBtn.setAttribute("aria-pressed", String(on)); // the class is the eye's copy

  if (!on) {
    for (const b of diffMarked) b.classList.remove("cq-ins-block");
    diffMarked.length = 0;
    document.dispatchEvent(new CustomEvent("cq-diff"));
  }
}
diffBtn.onclick = async () => {
  if (diffOn) return setDiff(false);
  try {
    const n = await applyDiff(diffBase);
    setDiff(true);
    const baseLabel = `v${diffBase}`;
    showToast(
      n
        ? `${n} changed passage${n === 1 ? "" : "s"} since ${baseLabel}`
        : `No text changes since ${baseLabel}`,
    );
  } catch {
    showToast("Couldn't load the previous version");
  }
};

// ---------- banner ----------
// "Claude is working" is a claim in status.json, and nothing revises a claim once the
// session behind it walks away — so a page nobody is watching reads exactly like a page
// whose reviewer has said nothing yet. The banner asks whether anyone is attending, and
// only two things answer yes: Claude is credibly busy, or a `review wait` is live. Everything
// else is absence, where the reason and the remedy are all that vary.
const HANDOFF_GRACE_MS = 2 * 60 * 1000;
const WORKING_GRACE_MS = 15 * 60 * 1000;
function renderStatus(state) {
  // One writer for the dot and the text, offline included: null is the poll
  // saying it couldn't reach the server, not a second function's own rendering.
  if (state === null) {
    dot.className = "cq-dot offline";
    statusText.textContent = "Server offline — comments won't send";
    return;
  }
  const { status, listening, pending, session_alive } = state;
  // The one hard fact here is the owning process. Unknown counts as alive: a page
  // nothing claimed (interact.py run outside Claude Code) isn't an abandoned one.
  const alive = session_alive !== false;
  // How long the claim has gone unrefreshed. The rope is short for the status
  // `review wait` writes as it prints a batch, because the agent writes its own
  // `review state` after acknowledgement — that mark outliving minutes is a dropped
  // pickup, not a long turn.
  const grace = status.handoff ? HANDOFF_GRACE_MS : WORKING_GRACE_MS;
  const quiet =
    Boolean(status.ts) && Date.now() - new Date(status.ts).getTime() > grace;
  let cls = "away",
    text = "",
    showAge = false;
  if (status.state === "idle") {
    cls = "";
    text = "Review closed";
  } else if (alive && status.state === "working" && !quiet) {
    cls = "working";
    showAge = Boolean(status.ts);
    text = `${agentName()} is working${status.detail ? " — " + status.detail : ""}`;
  } else if (alive && listening) {
    cls = "listening";
    text = `${agentName()} is listening — select text to comment`;
  } else {
    // Nobody is attending: say why, what's waiting, and what to do. A dead session is
    // never coming back, a recent check-in means Claude is mid-turn, and a long silence
    // means it lost the thread.
    const [why, how] = !alive
      ? [
          `The ${agentName()} session reviewing this page has ended.`,
          "Start one in the terminal to pick it up.",
        ]
      : quiet
        ? [
            `${agentName()} last checked in ${ago(status.ts)}.`,
            "Nudge it in the terminal.",
          ]
        : [`${agentName()} isn't watching right now.`, "It picks them up next turn."];
    // Reviewer updates land in the append-only log either way; what changes is when
    // they're read.
    const held = pending
      ? `${pending} update${pending === 1 ? "" : "s"} waiting.`
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

// Navigate to a version with the pin semantics every chooser shares: an older
// version pins the view, the newest unpins it.
const goVersion = (version) => {
  const path = `/versions/v${version}.html`;
  location.href = version === latestVersion ? path : `${path}?pin`;
};
function renderVersions(state) {
  versions = state.versions;
  const notes = {};
  for (const e of events) if (e.kind === "note") notes[e.version] = e.text;
  const key = JSON.stringify([state.versions, notes]);
  const current = state.versions.includes(VNUM) ? VNUM : null;
  if (key !== lastVersionsKey) {
    lastVersionsKey = key;
    versionSelect.textContent = "";
    for (const version of state.versions) {
      const opt = document.createElement("option");
      opt.value = version;
      const isLatest = version === state.versions.at(-1);
      opt.textContent = `v${version}${isLatest ? " (latest)" : ""}${
        notes[version] ? " · " + notes[version] : ""
      }`;
      versionSelect.append(opt);
    }
    versionSelect.value = current ?? "";
    // The box states its width rather than taking one (see the theme), so a note
    // longer than it ends in an ellipsis. Carrying the whole label as the tooltip
    // puts the rest a hover away instead of only inside the open menu.
    versionSelect.title = versionSelect.selectedOptions[0]?.textContent || "Version";
  }
  latestVersion = state.versions.at(-1) ?? null;
  const behind = latestVersion !== null && VNUM !== null && latestVersion !== VNUM;
  // Follow the newest version unless pinned or the user is mid-composition:
  // drafts survive navigation, but an open composer or a live selection
  // doesn't. While deferred, the chip shows instead.
  if (behind && !PINNED && !midComposition()) {
    location.replace(`/versions/v${latestVersion}.html`);
    return;
  }
  showNews(latestChip, behind);
  if (behind) latestChip.textContent = `New version available → open v${latestVersion}`;
  const idx = current === null ? -1 : state.versions.indexOf(current);
  diffBase = idx > 0 ? state.versions[idx - 1] : null;
  showNews(diffBtn, Boolean(diffBase));
  if (diffBase) {
    diffBtn.textContent = `Δ v${diffBase}`;
    diffBtn.title = `Highlight what changed since v${diffBase}`;
  }
}
// A live widget gesture (.cq-dragging) counts: navigating mid-drag would unload
// the document from under the pointer and lose the move.
const midComposition = () =>
  composerOpen ||
  Boolean(fabAnchor) ||
  Boolean(document.querySelector(".cq-dragging")) ||
  Boolean(document.querySelector('cq-draft[aria-busy="true"]')) ||
  (document.activeElement?.tagName === "TEXTAREA" &&
    (document.activeElement.value !== "" ||
      document.activeElement.classList.contains("cq-draft-edit")));
versionSelect.onchange = () => goVersion(Number(versionSelect.value));
latestChip.onclick = () => (location.href = "/");

// ---------- polling ----------
// Rendering version V shows V plus every action recorded up to it, replayed in
// seq order: a reload keeps the reviewer's drag, a second tab follows along
// live, and a decision made on v10 still stands on v25. Widgets opt in by
// exposing applyAction(action, detail) — an absolute placement, so replaying
// the sender's own action is a no-op. The first poll runs after upgrades
// settle, so the methods exist, and the pass runs at the end of a poll, so the
// panel's own widgets do too.
//
// The log outranks the markup, and that is the whole rule: authored state is the
// initial condition, never a later correction, so nothing a version does or
// omits can un-make a decision by itself. The repo's own CLAUDE.md carries why,
// and what it cost to learn. Replay used to stop at the handoff cursor, on the
// premise that a version written after the agent saw an action encoded it — a
// premise nothing checked, and acknowledgement is not assent. Only a version can say
// what the agent did with an action, and saying it is `version check`'s business now
// (restatement_errors), not something inferred here from silence.
const appliedActions = new Set();
// What an action rests on: the widget that sent it, and the parts of that widget
// its detail names — a `move` rests on its card as much as on the board. Either
// can be taken back, which is what lets a rewritten card drop its own moves while
// the rest of the board stays where the reviewer put it. Containment is the test,
// not "the page has an element by that id", so a literal detail value can't
// collide with an unrelated element that happens to be called the same thing.
function restsOn(e, widget) {
  // flat(), because a detail field may name several elements at once (a group's
  // set of picks) and each of them is something the action rests on.
  const parts = Object.values(e.detail)
    .flat()
    .map((v) => (typeof v === "string" ? document.getElementById(v) : null))
    .filter((el) => el && widget.contains(el))
    .map((el) => el.id);
  return [e.widget, ...parts];
}
// Retractions: a version that rewrote the words or state under a decision says
// so with `restated`, and publishing records it on the note that released it.
// Reading it from the log rather than from the markup is what makes it last —
// the version *after* the rewrite declares nothing, and its silence would
// otherwise hand the reviewer's retracted state straight back.
function retractionFloors(upto) {
  const floors = new Map();
  for (const e of events)
    if (e.kind === "note" && e.version <= upto)
      for (const id of e.restated || [])
        floors.set(id, Math.max(floors.get(id) ?? 0, e.version));
  return floors;
}
// An id-bearing element's state as markup can say it: tag, attributes, and
// place among its id-bearing kin. Text is deliberately absent — words are the
// static gate's subject (restatement_errors); this is the rest, the state no
// version file can speak. What the runtime itself paints onto page elements —
// exactly PAGE_PAINT_ATTRIBUTES — is absent too: no version can assert those,
// and looking away from them keeps a reading taken from the live DOM equal to
// one taken from the file without hiding a widget's own data-cq state. Diffed around each replay batch to
// record what replay wrote, and imported by version check --render to read the version
// files with the same eyes, so the two readings cannot drift.
export function shallowSigs(root) {
  const sigs = new Map();
  for (const el of [root, ...root.querySelectorAll("[id]")]) {
    if (!el.id) continue;
    const attrs = [...el.attributes]
      .filter((a) => !PAGE_PAINT_ATTRIBUTES.has(a.name))
      .map((a) => `${a.name}=${a.value}`)
      .sort()
      .join(" ");
    const kin = [...(el.parentElement?.children ?? [])].filter((c) => c.id);
    sigs.set(
      el.id,
      `${el.tagName} [${attrs}] in=${el.parentElement?.id ?? ""}#${kin.indexOf(el)}`,
    );
  }
  return sigs;
}
function applyActions() {
  // Never mutate the page under a live gesture — a replayed foreign action could
  // move the nodes a drag preview is holding. Retry next poll.
  if (document.querySelector(".cq-dragging")) return;
  const takenBack = retractionFloors(VNUM);
  // One snapshot brackets the batch: the loop below is synchronous, so between
  // these two readings nothing but its applyAction calls — no gesture, no widget
  // rendering itself — can touch the page, and the diff of the ends is exactly
  // what replay wrote.
  const before = events.some((e) => e.kind === "action" && !appliedActions.has(e.seq))
    ? shallowSigs(document.body)
    : null;
  let applied = false;
  const deferredWidgets = new Set();
  for (const e of events) {
    if (
      e.kind !== "action" ||
      appliedActions.has(e.seq) ||
      deferredWidgets.has(e.widget)
    )
      continue;
    const el = document.getElementById(e.widget);
    // Every terminal action is decided here and never looked at again. This pass runs
    // after the panel has rendered the log, so a widget that isn't here is one no
    // version can carry — an honored suggestion, whose wrapper the version replaced.
    if (!el?.applyAction) {
      appliedActions.add(e.seq);
      continue;
    }
    // A pinned older version is a historical view, so it shows what the reviewer
    // had done by then and not what they did later. A widget inside the comment
    // layer (.cq-chrome — a reply's inline question) has no version at all: its markup
    // is frozen in the log, and no version can rewrite or retract it.
    if (!inChrome(el)) {
      if (e.version > VNUM) {
        appliedActions.add(e.seq);
        continue;
      }
      const gone = restsOn(e, el).filter((id) => (takenBack.get(id) ?? 0) > e.version);
      if (gone.length) {
        // Say so on the page: a decision undone looks exactly like one never
        // made, and the reviewer is owed the difference.
        for (const id of gone) {
          const target = document.getElementById(id);
          if (target) target.setAttribute(PAGE_PAINT_ATTRIBUTE.restated, "1");
        }
        appliedActions.add(e.seq);
        continue;
      }
    }
    // A widget may briefly own live local input. `false` asks replay to leave this
    // action and later actions for the same widget in order for the next poll.
    if (el.applyAction(e.action, e.detail) === false) {
      deferredWidgets.add(e.widget);
      continue;
    }
    appliedActions.add(e.seq);
    applied = true;
  }
  if (applied) {
    const now = shallowSigs(document.body);
    // What the batch wrote — the ids whose shallow state its calls changed —
    // recorded on the body, where version check --render reads it. A no-op says the
    // markup already held the state; only a page widget can contradict its
    // version, so a reply's widget (.cq-chrome, no version) goes unrecorded.
    const wrote = [...new Set([...before.keys(), ...now.keys()])].filter(
      (id) => before.get(id) !== now.get(id) && !inChrome(document.getElementById(id)),
    );
    if (wrote.length) {
      const prior =
        document.body.getAttribute(PAGE_PAINT_ATTRIBUTE.replayWrote)?.split(" ") ?? [];
      document.body.setAttribute(
        PAGE_PAINT_ATTRIBUTE.replayWrote,
        [...new Set([...prior, ...wrote])].join(" "),
      );
    }
    // A replay moves the page's text — a card to another column, a suggestion to its
    // settled slot — so the marks are repainted where they now belong. Said here rather
    // than left to the caller's order: a pass held off by a live drag lands on a poll
    // that has nothing else to re-render.
    paintAnchors();
  }
  paintPending();
  // Every action in the log is now decided (applied, skipped, or retired), and
  // the stamp says so — it is what version check --render awaits before reading the
  // replay's record, so the gate never reads a page mid-replay.
  document.body.setAttribute(PAGE_PAINT_ATTRIBUTE.applied, String(appliedActions.size));
}

// ---------- decided, awaiting the honoring version ----------
// The registry's x-state names each verb's fold unit and record form, so one
// pass renders "the reviewer decided this and no version has carried it yet"
// for every widget alike — choose had its mark, edit its tint, move nothing,
// and the asymmetry was each widget remembering (or not) on its own. The
// authored facets are captured once per page load, after upgrades and before
// the first replay: the markup's initial condition, which replay then
// overwrites in the DOM.
const authoredFacets = new Map(); // unit id -> the facet this version arrived showing

function stateSpecs() {
  const specs = [];
  for (const [tag, entry] of Object.entries(registry))
    for (const spec of Object.values(entry["x-state"] ?? {})) specs.push([tag, spec]);
  return specs;
}

// What the page shows for one unit's declared record form, asked of the live
// DOM or of the diff's parsed base document alike. An attribute record is the
// set of elements wearing it — a group taking several picks marks several — so
// both readings collapse to the sorted ids, and comparing them stays a !==.
function domFacet(el, record) {
  if (record.kind === "attribute")
    return [...el.querySelectorAll(`[${record.attr}]`)]
      .map((o) => o.id)
      .sort()
      .join(" ");
  if (record.kind === "position") return el.closest(record.within)?.id ?? null;
  return quoteFrom(textNodesUnder(el)); // "body": the words, read the way a quote is
}

// The state the folded action left, from the detail field the record declares,
// collapsed the way the DOM reading collapses — its words where it is words,
// its sorted ids where it is a set.
function foldedFacet(e, record) {
  const value = e.detail[record.value];
  if (record.kind === "body")
    return [
      ...String(value ?? "")
        .replace(/\s+/g, " ")
        .trim(),
    ].join("");
  if (record.kind === "attribute") return [...value].sort().join(" ");
  return value ?? null;
}

function captureAuthoredFacets() {
  for (const [tag, spec] of stateSpecs()) {
    if (!spec.record) continue;
    for (const widget of document.querySelectorAll(tag)) {
      if (spec.unit === "widget" || !spec.unit) {
        if (widget.id) authoredFacets.set(widget.id, domFacet(widget, spec.record));
      } else
        // Per-part units, at the record form's own key: a position facet is
        // carried by the container's direct children (a column's cards), and
        // an id'd element nested inside one — a draft in a card — is not a
        // unit, just a passenger whose `closest()` would echo its carrier's.
        for (const part of widget.querySelectorAll(`${spec.record.within} > [id]`))
          authoredFacets.set(part.id, domFacet(part, spec.record));
    }
  }
}

// The reviewer's standing state as of `upto`: the last surviving action per
// declared unit. Every applyAction is absolute, which is what makes this a
// fold — one linear scan, no replay simulation. Surviving means not under a
// retraction floor keyed on what the action rests on — the same containment
// set replay skips by, so the two can't disagree about what a `restated` took
// back.
function stateFold(upto) {
  const floors = retractionFloors(upto);
  const fold = new Map();
  for (const e of events) {
    if (e.kind !== "action" || e.version > upto) continue;
    const el = document.getElementById(e.widget);
    if (!el?.applyAction || inChrome(el)) continue;
    const spec = registry[el.tagName.toLowerCase()]?.["x-state"]?.[e.action];
    if (!spec) continue;
    if (restsOn(e, el).some((id) => (floors.get(id) ?? 0) > e.version)) continue;
    const unit = spec.unit === "widget" || !spec.unit ? e.widget : e.detail[spec.unit];
    if (typeof unit === "string") fold.set(unit, { e, spec });
  }
  return fold;
}

// data-cq-pending: this element's decided state differs from what the version's
// markup arrived showing — the record is behind the log. It clears when a
// version carries the decision (the two agree again) or a retraction hands the
// state back to the author. A decided suggestion has no record form to agree
// with (honoring retires the wrapper), so it stays marked while the wrapper
// stands.
function paintPending() {
  for (const el of document.querySelectorAll(`[${PAGE_PAINT_ATTRIBUTE.pending}]`))
    el.removeAttribute(PAGE_PAINT_ATTRIBUTE.pending);
  for (const [unit, { e, spec }] of stateFold(VNUM)) {
    const el = document.getElementById(unit);
    if (!el) continue;
    const behind = spec.record
      ? foldedFacet(e, spec.record) !== authoredFacets.get(unit)
      : true;
    if (behind) el.setAttribute(PAGE_PAINT_ATTRIBUTE.pending, "1");
  }
}
async function poll() {
  let state;
  try {
    state = await (await fetch("/api/state")).json();
  } catch {
    renderStatus(null);
    return;
  }
  const nextEvents = state.events;
  const eventSeq = nextEvents.at(-1)?.seq ?? 0;
  // post() and the timer can poll together. The log is append-only, so a response
  // behind one already rendered is unambiguously stale; accepting it would move
  // every event-derived view backwards until the next poll.
  if (eventSeq < lastEventSeq) return;
  // Messages render from Markdown; have the renderer in hand before the panel
  // builds a body, so msgNode stays synchronous.
  if (nextEvents.some((e) => e.kind === "comment" || e.kind === "reply"))
    await loadMarked();
  events = nextEvents;
  agent = state.agent || "Claude";
  renderStatus(state);
  renderVersions(state);
  if (eventSeq > lastEventSeq) {
    lastEventSeq = eventSeq;
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
    endReviewBtn.disabled = events.some((e) => e.kind === "close");
    const agentReplies = events.filter(
      (e) => e.author === "claude" && e.kind === "reply",
    );
    if (agentMsgCount >= 0 && agentReplies.length > agentMsgCount && !panelOpen)
      showToast(`${agentReplies.at(-1).agent || "Agent"} replied — open Comments`, () =>
        setPanel(true),
      );
    agentMsgCount = agentReplies.length;
  }
  // Last, because the panel has just rendered the log: a widget carried by a reply is
  // on the page by now, so an action naming one that isn't names a widget no version
  // holds, and applyActions can retire it instead of looking for it forever.
  applyActions();
  // Sequence consumers render after replay, so their history and the widget's
  // standing body describe the same poll. This also fires when the event list did
  // not grow: applyAction may have deferred while a reviewer was typing, then become
  // applicable on the next poll after they close the editor.
  document.dispatchEvent(new Event("cq-actions"));
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
  if (!anchoringReady) return;
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
  // Before the first poll's replay: the authored facets are the markup's
  // initial condition, and replay is about to overwrite them in the DOM.
  captureAuthoredFacets();
  syncSuggestions();
  anchoringReady = true;
  paintAnchors(); // an early general post may already have loaded anchored threads
  updateFab(); // an early selection is now read from the fully upgraded page
  if (savedView) {
    restoreView(savedView);
    if (savedView.v < VNUM) showToast(`Updated to v${VNUM}`);
  }
  if (savedComposer)
    try {
      const { text, anchor, suggest } = JSON.parse(savedComposer);
      if (text)
        openComposer(anchor, text, (innerWidth - 320) / 2, 64, Boolean(suggest));
    } catch {}
  poll();
  setInterval(poll, POLL_MS);
  // Every widget has upgraded and every async one has settled, so the geometry and
  // the drawn SVG are final. `version export` copies the page at this moment and has no
  // other way to know it arrived: a load event fires before the modules run, and
  // networkidle only says a bundle finished downloading, not that it finished
  // drawing. The stamp says the document is done becoming itself.
  document.body.setAttribute(PAGE_PAINT_ATTRIBUTE.upgraded, "1");
});
