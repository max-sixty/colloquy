/* cq-options: upgraded only for `choose` — without the attribute the theme's CSS
 * is the whole widget and this module is a no-op. With it, clicking a card picks
 * that option, and each card carries an injected "Choose" button so the keyboard
 * reaches the same path: Tab to the button, Enter picks — a native button, so no
 * key handling of its own. The pick is applied as an absolute placement (chosen
 * on the target, cleared from siblings, ✓ badge moved, chosen's button hidden)
 * and reported as a `choose` action, the second rider on the channel cq-board
 * opened. Clicks that are really text selections or link follows don't choose.
 * An injected button rather than ARIA option/radio roles, whose presentational
 * children would silence links inside an option's prose. Authored content is
 * never replaced, so there is no failSoft. */
import { once, sendAction, toast } from "/colloquy.js";

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

    // {option}: option X is the chosen one of this group.
    applyAction(action, detail) {
      if (action !== "choose") return;
      const option = document.getElementById(detail.option);
      if (option?.matches("cq-option") && option.parentElement === this) this.#choose(option);
    }
  },
);
