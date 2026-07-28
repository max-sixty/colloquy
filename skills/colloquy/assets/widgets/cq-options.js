/* cq-options: upgraded for two attributes, and without either the theme's CSS is
 * the whole widget and this module is a no-op.
 *
 * `choose` takes the reader's pick: clicking a card picks that option and
 * clicking it again clears it, and each card carries one injected mark that is
 * both the keyboard path and the state — a toggle button reading "choose", which
 * becomes "your pick" once this reader picks it, or "chosen" where the document
 * already carries the pick. One element for both states, so nothing hides,
 * nothing moves, and a keyboard pick leaves focus where it was. The pick is
 * applied as an absolute placement (chosen on the target, cleared from siblings,
 * marks relabelled) and reported as a `choose` action naming the group's pick —
 * or null for no pick, which is how clearing travels rather than a second verb.
 * It's the second rider on the channel cq-board opened. Clicks that are really
 * text selections or link follows don't choose. An injected button rather than
 * ARIA option/radio roles, whose presentational children would silence links
 * inside an option's prose; `aria-pressed` carries the state alongside the
 * label, a promise the toggle keeps. Outside a `choose` group the same mark
 * renders as a span — the document's state, with nothing to press, and so a
 * passage a reviewer can quote rather than a label anchoring skips.
 *
 * `settled` retires the decision once it has been made and acted on: the group
 * collapses to one line naming the chosen option, with every card — the chosen
 * one included — behind a disclosure. Nothing is deleted, so the ids, the
 * anchors on them, and check's id-survival rule are all untouched; what's
 * reclaimed is the height. Open or closed is view state for this reader,
 * remembered per browser tab in sessionStorage like a cq-tabs tab: opening a
 * settled group is reading, not editing, so it sends no action and no version
 * carries it. Collapsed cards wear hidden="until-found", so find-in-page and
 * the runtime's reveal() (a click on a comment's quote) both open the group
 * rather than jumping to a card nobody can see, and while the version diff is
 * on the row wears a Δ count so a change can't hide behind the collapse. A
 * settled group still takes a pick once opened — settling is a sweep, not a
 * lock, and the summary line follows whatever is chosen, including back to a
 * bare "Settled" when the reader clears it.
 *
 * Inside a <cq-specimen> the group is quoted — exhibited, not offered — so it
 * takes the same path as a group that never declared `choose`: the mark is a
 * span, the click handler is never wired, and an example decision can't be
 * answered. `settled` still collapses there, because quoting gates the action
 * channel and not presentation.
 *
 * Authored content is never replaced, so there is no failSoft. */
import { once, quoted, sendAction, toast } from "/colloquy.js";

const OPEN = "choose"; // the card is pickable
const PICKED = "your pick"; // this reader picked it, this session
const AUTHORED = "chosen"; // the document arrived carrying the pick

const SETTLED_KEY = "cq-settled:";
// hidden="until-found" is only a hide where the UA supports it (it rides
// content-visibility, and the theme's display:block outranks the boolean
// [hidden] rule) — without beforematch, fall back to plain boolean hidden,
// which the theme hides itself; the group still collapses, ⌘F just can't see in.
const HIDDEN = "onbeforematch" in document.body ? "until-found" : "";

customElements.define(
  "cq-options",
  class extends HTMLElement {
    connectedCallback() {
      if (!once(this)) return;
      // An authored `chosen` (the honoring version carrying an earlier pick) wears
      // the same mark a live pick wears, so honoring doesn't change the look — but
      // worded as the document's state, not attributed to this reader.
      const honored = this.querySelector(":scope > cq-option[chosen]");
      this.#honored = honored;
      // Quoted material is exhibited, not offered, so a specimen renders exactly
      // like a group that was never choosable: it shows what a decision looks
      // like without taking one.
      const choosable = this.hasAttribute("choose") && !quoted(this);
      // Without `choose` there is nothing to press: the mark still reports the
      // document's state, as a span.
      if (choosable)
        for (const option of this.querySelectorAll(":scope > cq-option"))
          this.#mark(option, option === honored ? AUTHORED : OPEN, true);
      else if (honored) this.#mark(honored, AUTHORED, false);
      if (this.hasAttribute("settled")) this.#settle();
      if (!choosable) return;
      this.addEventListener("click", (e) => {
        // A click that lands inside a selection is that selection's, not a pick:
        // it's the mouseup of a drag-select. A selection elsewhere on the page —
        // a comment's, most often — is none of this click's business, and a
        // keyboard activation (detail 0) is never a drag-select.
        const sel = getSelection();
        if (e.detail !== 0 && sel && !sel.isCollapsed && sel.containsNode(e.target, true)) return;
        if (e.target.closest("a")) return; // links keep their job
        const option = e.target.closest("cq-option");
        if (!option || option.parentElement !== this) return;
        const prev = this.querySelector(":scope > cq-option[chosen]");
        // Clicking the card that already holds the pick clears it: one gesture
        // both ways, so a reader who picked by mistake needn't pick something
        // else to get out of it.
        const next = option === prev ? null : option;
        this.#choose(next);
        const title = option.querySelector(":scope > strong")?.textContent || option.id;
        const sent = next ? `Chose “${title}” — sent to Claude` : "Cleared your pick — sent to Claude";
        sendAction(this, "choose", { option: next?.id ?? null }).then((ok) => {
          if (ok) toast(sent);
          // Unsent means unrecorded: rewind rather than show a pick Claude will
          // never see. (post already toasted the failure.) No previous pick means
          // rewinding to no pick at all, which is #choose(null).
          else this.#choose(prev, prev === this.#honored ? AUTHORED : PICKED);
        });
      });
    }

    // The keyboard affordance and the state marker, one element — a button whose
    // click bubbles into the group's pick handler where there's a pick to make,
    // and the same mark as a span where there isn't.
    #mark(option, label, pressable) {
      const mark = document.createElement(pressable ? "button" : "span");
      if (pressable) mark.type = "button";
      // .cq-ui reaches exactly as far as the control does: a button's label is a
      // word for working the thing and anchoring skips it, while the span is the
      // page saying which option it carries, and the obvious thing to hang "not
      // this one" on. data-cq-gen either way — the diff parses the base version
      // unupgraded and would read any mark as text that version lacked.
      mark.className = pressable ? "cq-pick cq-ui" : "cq-pick";
      mark.dataset.cqGen = "1";
      option.append(mark);
      this.#relabel(option, label);
    }

    #honored = null; // the authored-chosen option, so a rollback rewords it honestly

    #choose(option, label = PICKED) {
      for (const o of this.querySelectorAll(":scope > cq-option")) {
        o.toggleAttribute("chosen", o === option);
        this.#relabel(o, o === option ? label : OPEN);
      }
      this.#retitle();
    }

    // A button's accessible name has to say which card it picks, and to contain
    // the visible word — so it tracks the label rather than staying "choose".
    // Pressed reads off the card, which #choose sets before relabelling.
    #relabel(option, label) {
      const mark = option.querySelector(":scope > .cq-pick");
      if (!mark) return;
      mark.textContent = label;
      if (mark.tagName !== "BUTTON") return;
      const title = option.querySelector(":scope > strong")?.textContent || option.id;
      mark.setAttribute("aria-label", `${label}: ${title}`);
      mark.setAttribute("aria-pressed", String(option.hasAttribute("chosen")));
    }

    // ---------- settled ----------

    #row = null; // the one-line summary a settled group collapses to
    #title = null; // the part of it naming the chosen option

    #settle() {
      this.#row = document.createElement("button");
      this.#row.type = "button";
      this.#row.className = "cq-settled cq-ui"; // UI, not content: anchoring skips it
      this.#row.dataset.cqGen = "1"; // and the version diff ignores it
      this.#title = document.createElement("span");
      const options = [...this.querySelectorAll(":scope > cq-option")];
      const count = document.createElement("span");
      count.className = "cq-settled-count";
      count.textContent = `${options.length} option${options.length === 1 ? "" : "s"}`;
      this.#row.append(this.#title, count);
      this.#row.setAttribute("aria-controls", options.map((o) => o.id).join(" "));
      this.#row.onclick = () => this.#open(!this.hasAttribute("open"), true);
      this.prepend(this.#row);
      for (const option of options) {
        // The browser found something inside (find-in-page, an anchor jump), or
        // the runtime is about to scroll a comment anchor into view: open up.
        option.addEventListener("beforematch", () => this.#open(true, true));
        option.addEventListener("cq-reveal", () => this.#open(true, true));
      }
      this.classList.add("cq-rendered"); // the upgraded marker every widget uses
      this.#retitle();
      let saved = null;
      try {
        saved = sessionStorage.getItem(SETTLED_KEY + this.id);
      } catch {}
      this.#open(saved === "1", false);
      // Δ badges follow the version diff; the runtime announces each toggle.
      document.addEventListener("cq-diff", () => this.#delta());
    }

    #open(open, remember) {
      this.toggleAttribute("open", open);
      for (const option of this.querySelectorAll(":scope > cq-option"))
        if (open) option.removeAttribute("hidden");
        else option.setAttribute("hidden", HIDDEN);
      this.#row.setAttribute("aria-expanded", open ? "true" : "false");
      if (remember)
        try {
          sessionStorage.setItem(SETTLED_KEY + this.id, open ? "1" : "0");
        } catch {}
    }

    // The summary carries the decision, so it names whichever option holds it —
    // including after a pick made in an opened group, which would otherwise leave
    // the line contradicting the cards it hides.
    #retitle() {
      if (!this.#title) return;
      const chosen = this.querySelector(":scope > cq-option[chosen]");
      const name = chosen?.querySelector(":scope > strong")?.textContent.trim();
      this.#title.textContent = name ? `Settled: ${name}` : "Settled";
    }

    // One Δn chip on the row when the diff marks passages inside, so the toast's
    // count is accounted for even where the marks sit behind the collapse.
    #delta() {
      this.#row.querySelector(".cq-settled-diff")?.remove();
      const n = this.querySelectorAll(".cq-ins-block").length;
      if (!n) return;
      const chip = document.createElement("span");
      chip.className = "cq-settled-diff";
      chip.textContent = `Δ${n}`;
      this.#row.append(chip);
    }

    // {option}: option X is this group's pick — or null, for no pick at all.
    applyAction(action, detail) {
      if (action !== "choose") return;
      if (detail.option === null) {
        this.#choose(null);
        return;
      }
      const option = document.getElementById(detail.option);
      if (option?.matches("cq-option") && option.parentElement === this) this.#choose(option);
    }
  },
);
