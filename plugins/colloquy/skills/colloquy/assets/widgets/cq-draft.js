/* cq-draft: a block of text the reviewer owns — rewrite it in place, and the exact
 * words reach the agent.
 *
 * The problem this solves that no other widget does: cq-board and cq-options let the
 * reviewer *choose* among things the agent wrote, but never *change* the words. The
 * fastest correction to a sentence is typing the better sentence, not describing it in
 * a comment. That capability is the whole element: one verb (`edit`, the entire new
 * text), no container, no approve/skip chrome. Decisions compose from structures that
 * already own them — put a draft inside a cq-card and the column is the verdict; page
 * assent is sign-off — rather than growing a second set of buttons here.
 *
 * Two rules shape the implementation:
 *
 * 1. Authored text stays in the light DOM as real text. A textarea's value lives off
 *    the text-node tree, so anything inside one is invisible to comment anchoring and
 *    to the version diff. So the body is a plain div — generated, but deliberately NOT
 *    marked .cq-ui or data-cq-gen, because those are exactly the markers that tell the
 *    anchor pass and the diff to look away. A div and not the <pre> the markup wrote,
 *    which would be the tidier swap: <pre> is a text block, and the runtime's comment
 *    line lands on the nearest one, so keeping it puts that line inside the words the
 *    editor is seeded from — the exact failure the marker rules exist for. The textarea
 *    exists only while an edit is open, and its result is written back as text. Read
 *    mode is the resting state; comments and Δ work there. The capture also strips the
 *    indentation the HTML source gave every line, so an agent can indent a draft like
 *    any other child content without the indentation becoming part of the text under
 *    review.
 * 2. applyAction states absolute values — the whole body, never a patch — so replay is
 *    idempotent, two tabs converge on the last write, and an edit no version has
 *    honored yet re-applies to each new version instead of visibly reverting. Until
 *    one does, the runtime's pending pass marks the element data-cq-pending — the
 *    same mark every decided-and-unhonored widget wears, driven by the registry's
 *    x-state rather than remembered here.
 *
 * Editing has two doors: double-click the text (the fast path), or the ✎ button (the
 * door keyboards and touch can use; it also makes the block *look* editable). It sits
 * in a control row the draft always has, which Cancel and Save join for the length of
 * an edit — one row of the same button either way, so opening one changes what the box
 * offers without changing its shape. Unsent keystrokes ride the runtime's draft store
 * (saveDraft/loadDraft), the composer's discipline: written on input, cleared only by a
 * successful send or explicit Cancel, so reload, version switch, and server death all
 * recover. The stored value is an object rather than the text bare: an empty string is a
 * real replacement here, while the shared store uses a bare empty string to mean remove.
 * Recovery is tab-local; submitted actions converge through the log, but one tab's
 * successful send or Cancel must not erase another tab's newer unsent edit.
 * A send owns the widget until its response, as a composer does; otherwise a second save
 * can overtake the first on the network and the earlier response can clear newer text.
 *
 * Once an edit exists, a native disclosure compares the authored body with the
 * standing one and lists the widget's absolute edit actions in log order. The runtime
 * owns that sequence and its version boundary (`watchActions`); the module owns only
 * its presentation. Restoring a row sends its text as one more ordinary edit, which
 * keeps one state model and lets another tab converge without knowing that the gesture
 * happened in a history view.
 *
 * The fast path is taken on the second mousedown rather than on dblclick, because the
 * word the browser selects is selected *by* that mousedown and painted before dblclick
 * arrives: clearing it afterwards is a frame too late, and the reviewer saw a word
 * flash blue and vanish. Cancelling the mousedown's default means there was never a
 * selection to flash, or a comment button to contest the gesture. What that default
 * was saying — "this word" — is carried into the box instead, where a double-click
 * still means what it means everywhere else: type over this word.
 *
 * Chrome is injected through the runtime's `offer`, which marks it .cq-ui for the chrome
 * look, data-cq-gen so the diff ignores it, and data-cq-offer for a thing to work — which
 * is what keeps it off the printed page, out of the anchor pass (this widget declaring no
 * label the page speaks through), and out of the way of the double-click below; the class
 * also earns the edit box the runtime's one textarea rule. Presentation is theme CSS, the
 * swap between the two views included: an open edit is the box being in the document, so
 * the CSS reads that and this module writes no display state at all. Which is also what
 * lets paper disagree — it drops the box and keeps the words. History is chrome too and
 * exists only on a live page; a scriptless copy cannot honestly offer restore. Authored
 * content is never discarded, so there is no failSoft.
 */
import {
  agentName,
  dataBody,
  once,
  offer,
  quoted,
  sendAction,
  toast,
  keyHelp,
  keyHint,
  SEND_KEYS,
  saveDraft,
  loadDraft,
  alignText,
  watchActions,
} from "/colloquy.js";

// The edit box's keys — one declaration for the "?" overlay and the key line. Esc
// sets the edit aside rather than discarding it (never lose user text: Cancel is
// the only discard), and the handler consumes the press, because a declared Esc
// row promises one action and the runtime's ladder must not add a second.
const EDIT_KEYS = [
  [SEND_KEYS, "save"],
  ["Esc", "close — edit kept"],
];

// The store key for a draft's unsent edit. The page's port is its own origin, so
// the id alone is unambiguous — the same scoping every composer draft relies on.
const ctx = (id) => "edit:" + id;
// Presence and content are different for this widget: deleting every character is an
// unsent edit, so wrap the text in a truthy record before handing it to the shared store.
const saveEdit = (id, text) => saveDraft(ctx(id), JSON.stringify({ text }));
const clearEdit = (id) => saveDraft(ctx(id), "");
function loadEdit(id) {
  const stored = loadDraft(ctx(id));
  if (!stored) return null;
  try {
    const value = JSON.parse(stored);
    if (typeof value?.text === "string") return value.text;
  } catch {}
  clearEdit(id);
  return null;
}

// Where the browser's own double-click would have drawn the word's edges. Segmenter
// knows the boundaries of the language the draft is written in, which /\w+/ does not:
// it keeps "l'écran" and a run of CJK whole where a character class splits them. The
// boundaries follow the script the words are written in; the locale only refines that,
// and the page's own `lang` is not the place to take it from — nothing validates that
// attribute, and Segmenter throws on a tag it can't parse, which at module scope is a
// typo in the markup costing every draft on the page its upgrade.
const words = new Intl.Segmenter(undefined, { granularity: "word" });

// The word under the pointer as a range in the body's text — the body holds one text
// node, so its offsets are the textarea's offsets. Between words the range is the
// collapsed caret the click asked for, which needs no second shape for the caller to
// test; past the end of the text there is no offset to carry at all, and the box opens
// where focus alone would have put it.
function wordAt(body, x, y) {
  const pos = document.caretPositionFromPoint(x, y);
  if (!pos || pos.offsetNode !== body.firstChild) return null;
  for (const w of words.segment(body.textContent)) {
    if (
      w.isWordLike &&
      pos.offset >= w.index &&
      pos.offset <= w.index + w.segment.length
    )
      return [w.index, w.index + w.segment.length];
  }
  return [pos.offset, pos.offset];
}

// What the agent wrote, verbatim, minus what the HTML source needed: the leading
// newline after the open tag, trailing whitespace before the close tag, and the
// common indentation the source gave every line.
function capture(el) {
  const raw = dataBody(el).replace(/^\n/, "").replace(/\s+$/, "");
  const lines = raw.split("\n");
  const indents = lines
    .filter((l) => l.trim())
    .map((l) => l.match(/^[ \t]*/)[0].length);
  const cut = indents.length ? Math.min(...indents) : 0;
  return lines.map((l) => l.slice(cut)).join("\n");
}

customElements.define(
  "cq-draft",
  class extends HTMLElement {
    #body;
    #pencil;
    #row;
    #raw;
    #history = null;
    #historyKey = "";
    #alignments = new Map();
    #ta = null;
    #sending = false;

    connectedCallback() {
      if (!once(this)) return;

      const raw = capture(this);
      this.#raw = raw;
      this.textContent = "";

      this.#body = document.createElement("div");
      this.#body.className = "cq-draft-body"; // NOT .cq-ui: anchoring and Δ must see this
      this.#body.textContent = raw;
      this.append(this.#body);

      // A quoted draft is an exhibit: the same dedented text, none of the doors —
      // no pencil, no double-click, no edit keys in the "?" overlay. Quoting
      // gates the action channel, not presentation.
      if (quoted(this)) return;

      keyHelp("On a draft", [
        ["dblclick or ✎", "edit the text in place"],
        ...EDIT_KEYS,
      ]);

      this.#pencil = this.#button("✎", () => this.#open());
      this.#pencil.classList.add("cq-draft-pencil");
      this.#pencil.setAttribute("aria-label", `Edit ${this.id}`);
      this.#pencil.title = "Edit this text — or double-click it";
      this.#row = offer("div", "cq-draft-controls");
      this.#row.append(this.#pencil);
      this.append(this.#row);
      watchActions(this, "edit", (actions) => this.#renderHistory(actions));

      // The fast path, taken before the browser paints the selection this gesture
      // would have made (see above). The word it aimed at opens selected in the box.
      // A double-click on the widget's own chrome belongs to that control — above all
      // to the edit box, whose word selection this preventDefault would swallow. What
      // the guard means is "a thing to work", so it reads the marker that says so and
      // not the chrome face, which is a look and would answer by coincidence.
      this.addEventListener("mousedown", (ev) => {
        if (ev.detail !== 2 || ev.target.closest("[data-cq-offer]")) return;
        ev.preventDefault();
        this.#open(undefined, wordAt(this.#body, ev.clientX, ev.clientY));
      });

      // A recovered edit outranks the authored text: the reviewer typed it and never
      // got it sent, so it must survive exactly as the composer's drafts do.
      const pending = loadEdit(this.id);
      if (pending !== null && pending !== raw) this.#open(pending);
      else if (pending === raw) clearEdit(this.id);
    }

    #button(text, onClick, variant) {
      const b = offer("button", "cq-btn" + (variant ? " " + variant : ""), text);
      b.addEventListener("click", onClick);
      return b;
    }

    #delta(before, after, cache = true) {
      const line = document.createElement("div");
      line.className = "cq-draft-delta";
      const key = JSON.stringify([before, after]);
      let alignment = this.#alignments.get(key);
      if (!alignment) {
        alignment = alignText(before, after);
        if (cache) this.#alignments.set(key, alignment);
      }
      for (const run of alignment) {
        const node = document.createElement(
          run.kind === "delete" ? "del" : run.kind === "insert" ? "ins" : "span",
        );
        node.textContent = run.text;
        line.append(node);
      }
      if (!line.childNodes.length) line.textContent = "Empty";
      return line;
    }

    #snapshot(label, text, comparison, standing) {
      const item = document.createElement("li");
      const head = document.createElement("div");
      head.className = "cq-draft-revision-head";
      const name = document.createElement("strong");
      name.textContent = label;
      head.append(name);
      if (text !== standing) {
        const restore = this.#button(`Restore ${label.toLowerCase()}`, () =>
          this.#restore(text, label),
        );
        restore.classList.add("cq-draft-restore");
        head.append(restore);
      }
      let body;
      if (comparison === null) {
        body = document.createElement("div");
        body.className = "cq-draft-snapshot";
        body.textContent = text || "Empty";
      } else body = this.#delta(comparison, text);
      item.append(head, body);
      return item;
    }

    #renderHistory(actions) {
      if (this.#sending) return;
      const standing = this.#body.textContent;
      const key = JSON.stringify([
        this.#raw,
        standing,
        actions.map((event) => [event.seq, event.version, event.detail.text]),
      ]);
      if (key === this.#historyKey) return;
      this.#historyKey = key;
      if (!actions.length && standing === this.#raw) {
        this.#history?.remove();
        this.#history = null;
        return;
      }

      const wasOpen = this.#history?.open ?? false;
      const keepFocus = Boolean(this.#history?.contains(document.activeElement));
      const history = offer("details", "cq-draft-history");
      history.open = wasOpen;
      const summary = document.createElement("summary");
      summary.textContent = `Changes · ${actions.length} ${actions.length === 1 ? "edit" : "edits"}`;

      const current = document.createElement("section");
      current.className = "cq-draft-current";
      const currentLabel = document.createElement("strong");
      currentLabel.textContent =
        standing === this.#raw
          ? "Standing text matches this version"
          : "This version → standing text";
      current.append(currentLabel);
      // This pair changes with every standing edit. Recomputing it once for the new
      // history render is cheaper than retaining every obsolete full-body comparison;
      // adjacent log revisions below are stable and remain worth caching.
      if (standing !== this.#raw)
        current.append(this.#delta(this.#raw, standing, false));

      const list = document.createElement("ol");
      list.className = "cq-draft-revisions";
      list.append(this.#snapshot("Version text", this.#raw, null, standing));
      let previous = null;
      actions.forEach((event, index) => {
        const text = event.detail.text;
        list.append(
          this.#snapshot(
            `Edit ${index + 1} · v${event.version}`,
            text,
            previous,
            standing,
          ),
        );
        previous = text;
      });
      history.append(summary, current, list);
      this.#history?.replaceWith(history);
      if (!this.#history) this.append(history);
      this.#history = history;
      if (keepFocus) summary.focus();
    }

    async #restore(text, label) {
      if (this.#sending) {
        toast("Wait for the current edit to finish sending");
        return;
      }
      if (this.#ta) {
        toast("Save or cancel the open edit before restoring history");
        return;
      }
      if (text === this.#body.textContent) return;
      const previous = this.#body.textContent;
      this.#sending = true;
      this.setAttribute("aria-busy", "true");
      this.#body.textContent = text;
      const ok = await sendAction(this, "edit", { text });
      this.#sending = false;
      this.removeAttribute("aria-busy");
      if (ok) toast(`Restored ${label.toLowerCase()} — sent to ${agentName()}`);
      else this.#body.textContent = previous;
    }

    #open(seed, at) {
      if (this.#ta) return;
      if (this.#sending) {
        toast("Wait for the current edit to finish sending");
        return;
      }
      const ta = offer("textarea", "cq-draft-edit");
      // A set-aside edit outranks the authored text here too: reopening resumes it.
      ta.value = seed ?? loadEdit(this.id) ?? this.#body.textContent;
      ta.setAttribute("aria-label", `Edit ${this.id}`);
      ta.addEventListener("input", () => saveEdit(this.id, ta.value));
      // Cmd/Ctrl+Enter saves; Escape sets the edit aside — the composer's bindings,
      // and consumed, or the runtime's ladder would add a second action (closing
      // the panel) to the one EDIT_KEYS promises.
      ta.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) this.#commit();
        else if (e.key === "Escape") {
          e.preventDefault();
          this.#close(false);
        }
      });
      keyHint(ta, EDIT_KEYS);
      this.#row.append(
        this.#button("Cancel", () => this.#close(true)),
        this.#button("Save", () => this.#commit(), "primary"),
      );
      this.#ta = ta;
      this.#body.after(ta);
      ta.focus();
      // Only the pointer names a place; the pencil and a recovered draft leave the
      // caret where focus put it, at the start of the text. The range was measured
      // in the body's text, so it names a word only in a box holding that text — a
      // resumed edit opens with different words at those offsets.
      if (at && ta.value === this.#body.textContent) ta.setSelectionRange(at[0], at[1]);
    }

    #close(discard) {
      if (!this.#ta) return;
      if (discard) clearEdit(this.id);
      this.#ta.remove();
      this.#ta = null;
      // States the whole row rather than removing two buttons from it, so read mode
      // is one call from anywhere. The edit box had focus and is gone; hand it to the
      // draft's one persistent control so a keyboard reviewer isn't dropped back at
      // the page top.
      this.#row.replaceChildren(this.#pencil);
      this.#pencil.focus();
    }

    async #commit() {
      if (!this.#ta || this.#sending) return;
      const text = this.#ta.value;
      if (text === this.#body.textContent) {
        this.#close(true);
        return;
      }
      const previous = this.#body.textContent;
      this.#body.textContent = text;
      this.#close(false);
      this.#sending = true;
      this.setAttribute("aria-busy", "true");
      const ok = await sendAction(this, "edit", { text });
      this.#sending = false;
      this.removeAttribute("aria-busy");
      if (ok) {
        clearEdit(this.id);
        toast(`Edited “${this.id}” — sent to ${agentName()}`);
      } else {
        // Unsent means unrecorded. Put the words back on screen and keep the
        // reviewer's text in storage so nothing they typed is lost.
        this.#body.textContent = previous;
        saveEdit(this.id, text);
        this.#open(text);
      }
    }

    // An absolute value, so replaying this tab's own edit is a no-op and a second
    // tab converges rather than drifting. The edited-but-unhonored tint is the
    // runtime's, not this widget's: the pending pass compares the fold against
    // the authored text and marks data-cq-pending for every widget alike.
    applyAction(action, detail) {
      if (action !== "edit" || typeof detail?.text !== "string") return;
      if (this.#ta || this.#sending) return false; // defer rather than yank words out from under a live edit/send
      this.#body.textContent = detail.text;
    }
  },
);
