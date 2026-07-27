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
 *    anchor pass and the diff to look away. The textarea exists only while an edit is
 *    open, and its result is written back as text. Read mode is the resting state;
 *    comments and Δ work there. The capture also strips the indentation the HTML
 *    source gave every line, so an agent can indent a draft like any other child
 *    content without the indentation becoming part of the text under review.
 * 2. applyAction states absolute values — the whole body, never a patch — so replay is
 *    idempotent, two tabs converge on the last write, and an edit no version has
 *    honored yet re-applies to each new version instead of visibly reverting. Until
 *    one does, the element wears data-cq-edited and the theme tints its border.
 *
 * Editing has two doors: double-click the text (the fast path — it wins over the
 * word-selection it makes, so no comment button flashes), or the ✎ button (the door
 * keyboards and touch can use; it also makes the block *look* editable). Unsent
 * keystrokes ride the runtime's draft store (saveDraft/loadDraft), the composer's
 * discipline: written on input, cleared only by a successful send, so reload, version
 * switch, and server death all recover.
 *
 * Chrome is injected as .cq-ui so anchoring skips it and data-cq-gen so the diff
 * ignores it; the class also earns the edit box the runtime's one textarea rule.
 * Presentation is theme CSS; authored content is never discarded, so there is no
 * failSoft.
 */
import { once, quoted, sendAction, toast, keyHelp, saveDraft, loadDraft } from "/colloquy.js";

// Registered on first upgrade, not at import: the "?" overlay should list edit
// keys only where a draft is.
let helpRegistered = false;

// The store key for a draft's unsent edit. The page's port is its own origin, so
// the id alone is unambiguous — the same scoping every composer draft relies on.
const ctx = (id) => "edit:" + id;

// What the agent wrote, verbatim, minus what the HTML source needed: the leading
// newline after the open tag, trailing whitespace before the close tag, and the
// common indentation the source gave every line.
function capture(el) {
  const raw = el.textContent.replace(/^\n/, "").replace(/\s+$/, "");
  const lines = raw.split("\n");
  const indents = lines.filter((l) => l.trim()).map((l) => l.match(/^[ \t]*/)[0].length);
  const cut = indents.length ? Math.min(...indents) : 0;
  return lines.map((l) => l.slice(cut)).join("\n");
}

customElements.define(
  "cq-draft",
  class extends HTMLElement {
    #body; #pencil; #ta = null; #row = null;

    connectedCallback() {
      if (!once(this)) return;
      this.classList.add("cq-rendered"); // the upgraded marker every widget uses

      const raw = capture(this);
      this.textContent = "";

      this.#body = document.createElement("div");
      this.#body.className = "cq-draft-body"; // NOT .cq-ui: anchoring and Δ must see this
      this.#body.textContent = raw;
      this.append(this.#body);

      // A quoted draft is an exhibit: the same dedented text, none of the doors —
      // no pencil, no double-click, no edit keys in the "?" overlay. Quoting
      // gates the action channel, not presentation.
      if (quoted(this)) return;

      if (!helpRegistered) {
        helpRegistered = true;
        keyHelp("On a draft", [
          ["dblclick or ✎", "edit the text in place"],
          ["⌘/Ctrl+Enter", "save the edit"],
          ["Esc", "cancel the edit"],
        ]);
      }

      this.#pencil = this.#button("✎", () => this.#open());
      this.#pencil.classList.add("cq-draft-pencil");
      this.#pencil.setAttribute("aria-label", `Edit ${this.id}`);
      this.#pencil.title = "Edit this text — or double-click it";
      this.prepend(this.#pencil);

      // The fast path. Editing wins over the word-selection the gesture makes;
      // clearing it keeps the comment button from contesting the double-click.
      this.addEventListener("dblclick", (ev) => {
        if (ev.target.closest(".cq-ui")) return;
        getSelection()?.removeAllRanges();
        this.#open();
      });

      // A recovered edit outranks the authored text: the reviewer typed it and never
      // got it sent, so it must survive exactly as the composer's drafts do.
      const pending = loadDraft(ctx(this.id));
      if (pending && pending !== raw) this.#open(pending);
    }

    #button(text, onClick, variant) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "cq-btn cq-ui" + (variant ? " " + variant : "");
      b.dataset.cqGen = "1";
      b.textContent = text;
      b.addEventListener("click", onClick);
      return b;
    }

    #open(seed) {
      if (this.#ta) return;
      const ta = document.createElement("textarea");
      ta.className = "cq-draft-edit cq-ui";
      ta.dataset.cqGen = "1";
      ta.value = seed ?? this.#body.textContent;
      ta.setAttribute("aria-label", `Edit ${this.id}`);
      ta.addEventListener("input", () => saveDraft(ctx(this.id), ta.value));
      // Cmd/Ctrl+Enter saves, Escape cancels — the composer's bindings.
      ta.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) this.#commit();
        else if (e.key === "Escape") this.#close(true);
      });
      this.#row = document.createElement("div");
      this.#row.className = "cq-draft-editrow cq-ui";
      this.#row.dataset.cqGen = "1";
      this.#row.append(
        this.#button("Cancel", () => this.#close(true)),
        this.#button("Save", () => this.#commit(), "primary"),
      );
      this.#ta = ta;
      this.#body.hidden = true;
      this.#pencil.hidden = true;
      this.#body.after(ta, this.#row);
      ta.focus();
    }

    #close(discard) {
      if (!this.#ta) return;
      if (discard) saveDraft(ctx(this.id), "");
      this.#ta.remove();
      this.#row.remove();
      this.#ta = this.#row = null;
      this.#body.hidden = false;
      this.#pencil.hidden = false;
      // The edit box had focus and is gone; hand it to the draft's one persistent
      // control so a keyboard reviewer isn't dropped back at the page top.
      this.#pencil.focus();
    }

    #commit() {
      const text = this.#ta.value;
      if (text === this.#body.textContent) {
        this.#close(true);
        return;
      }
      const previous = this.#body.textContent;
      const wasEdited = "cqEdited" in this.dataset;
      this.#body.textContent = text;
      this.dataset.cqEdited = "1";
      this.#close(false);
      sendAction(this, "edit", { text }).then((ok) => {
        if (ok) {
          saveDraft(ctx(this.id), "");
          toast(`Edited “${this.id}” — sent to Claude`);
        } else {
          // Unsent means unrecorded. Put the words back on screen and keep the
          // reviewer's text in storage so nothing they typed is lost.
          this.#body.textContent = previous;
          if (!wasEdited) delete this.dataset.cqEdited;
          saveDraft(ctx(this.id), text);
        }
      });
    }

    // An absolute value, so replaying this tab's own edit is a no-op and a second
    // tab converges rather than drifting.
    applyAction(action, detail) {
      if (action !== "edit" || typeof detail?.text !== "string") return;
      if (this.#ta) return; // never yank the words out from under a live edit
      this.#body.textContent = detail.text;
      this.dataset.cqEdited = "1";
    }
  },
);
