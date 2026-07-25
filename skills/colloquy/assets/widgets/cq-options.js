/* cq-options: upgraded for two attributes, and without either the theme's CSS is
 * the whole widget and this module is a no-op.
 *
 * `choose` takes the reader's pick: clicking a card picks that option, and each
 * card carries an injected "Choose" button so the keyboard reaches the same path
 * — Tab to the button, Enter picks, a native button, so no key handling of its
 * own. The pick is applied as an absolute placement (chosen on the target,
 * cleared from siblings, ✓ badge moved, chosen's button hidden) and reported as
 * a `choose` action, the second rider on the channel cq-board opened. Clicks
 * that are really text selections or link follows don't choose. An injected
 * button rather than ARIA option/radio roles, whose presentational children
 * would silence links inside an option's prose.
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
 * lock, and the summary line follows whatever is chosen.
 *
 * Authored content is never replaced, so there is no failSoft. */
import { once, sendAction, toast } from "/colloquy.js";

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
      // An authored `chosen` (the honoring version carrying an earlier pick) gets
      // the same ✓ badge a live pick gets, so honoring doesn't change the look —
      // but worded as the document's state, not attributed to this reader.
      const honored = this.querySelector(":scope > cq-option[chosen]");
      if (honored) this.#badge(honored, "✓ chosen");
      this.#honored = honored;
      if (this.hasAttribute("settled")) this.#settle();
      if (!this.hasAttribute("choose")) return;
      for (const option of this.querySelectorAll(":scope > cq-option")) this.#pick(option);
      this.addEventListener("click", (e) => {
        // A pointer click amid a selection is the selection's, not a pick — but a
        // keyboard activation (detail 0) can't be one, and a stale selection
        // elsewhere on the page must not swallow it.
        if (e.detail !== 0 && getSelection()?.toString()) return;
        if (e.target.closest("a")) return; // links keep their job
        const option = e.target.closest("cq-option");
        if (!option || option.parentElement !== this || option.hasAttribute("chosen")) return;
        const prev = this.querySelector(":scope > cq-option[chosen]");
        this.#choose(option);
        const title = option.querySelector(":scope > strong")?.textContent || option.id;
        sendAction(this, "choose", { option: option.id }).then((ok) => {
          if (ok) toast(`Chose “${title}” — sent to Claude`);
          // Unsent means unrecorded: rewind rather than show a pick Claude
          // will never see. (post already toasted the failure.)
          else if (prev) this.#choose(prev, prev === this.#honored ? "✓ chosen" : "✓ your pick");
          else {
            option.removeAttribute("chosen");
            option.querySelector(":scope > .cq-chosen-badge")?.remove();
            const btn = option.querySelector(":scope > .cq-pick");
            if (btn) btn.hidden = false;
            this.#retitle();
          }
        });
      });
    }

    // The keyboard affordance: a real button whose click bubbles into the group's
    // pick handler. The chosen option hides its button — the ✓ badge says it.
    #pick(option) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "cq-pick cq-ui"; // UI, not content: anchoring skips it
      btn.dataset.cqGen = "1"; // and the version diff ignores it
      btn.textContent = "Choose";
      const title = option.querySelector(":scope > strong")?.textContent || option.id;
      btn.setAttribute("aria-label", `Choose: ${title}`);
      btn.hidden = option.hasAttribute("chosen");
      option.append(btn);
    }

    #honored = null; // the authored-chosen option, so a rollback rebadges it honestly

    #choose(option, badge = "✓ your pick") {
      // Hiding a focused button dumps focus to <body>; catch that before it
      // happens and keep the keyboard reviewer's place on the chosen option.
      const chosenBtn = option.querySelector(":scope > .cq-pick");
      const hadFocus = chosenBtn && document.activeElement === chosenBtn;
      for (const o of this.querySelectorAll(":scope > cq-option")) {
        o.toggleAttribute("chosen", o === option);
        o.querySelector(":scope > .cq-chosen-badge")?.remove();
        const btn = o.querySelector(":scope > .cq-pick");
        if (btn) btn.hidden = o === option;
      }
      this.#badge(option, badge);
      this.#retitle();
      if (hadFocus) {
        option.tabIndex = -1;
        option.focus({ preventScroll: true });
      }
    }

    #badge(option, text) {
      const badge = document.createElement("span");
      badge.className = "cq-chosen-badge cq-ui"; // UI, not content: anchoring skips it
      badge.dataset.cqGen = "1"; // and the version diff ignores it
      badge.textContent = text;
      option.append(badge);
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

    // {option}: option X is the chosen one of this group.
    applyAction(action, detail) {
      if (action !== "choose") return;
      const option = document.getElementById(detail.option);
      if (option?.matches("cq-option") && option.parentElement === this) this.#choose(option);
    }
  },
);
