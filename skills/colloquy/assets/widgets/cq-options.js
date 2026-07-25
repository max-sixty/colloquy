/* cq-options: upgraded only for `choose` — without the attribute the theme's CSS
 * is the whole widget and this module is a no-op. With it, clicking a card picks
 * that option: the pick is applied as an absolute placement (chosen on the target,
 * cleared from siblings, ✓ badge moved) and reported as a `choose` action, the
 * second rider on the channel cq-board opened. Clicks that are really text
 * selections or link follows don't choose. Authored content is never replaced, so
 * there is no failSoft. */
import { once, sendAction, toast } from "/colloquy.js";

customElements.define(
  "cq-options",
  class extends HTMLElement {
    connectedCallback() {
      if (!once(this)) return;
      // An authored `chosen` (the honoring version carrying an earlier pick) gets
      // the same ✓ badge a live pick gets, so honoring doesn't change the look.
      const honored = this.querySelector(":scope > cq-option[chosen]");
      if (honored) this.#badge(honored);
      if (!this.hasAttribute("choose")) return;
      this.addEventListener("click", (e) => {
        if (getSelection()?.toString()) return; // a selection, not a pick
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
          else if (prev) this.#choose(prev);
          else {
            option.removeAttribute("chosen");
            option.querySelector(":scope > .cq-chosen-badge")?.remove();
          }
        });
      });
    }

    #choose(option) {
      for (const o of this.querySelectorAll(":scope > cq-option")) {
        o.toggleAttribute("chosen", o === option);
        o.querySelector(":scope > .cq-chosen-badge")?.remove();
      }
      this.#badge(option);
    }

    #badge(option) {
      const badge = document.createElement("span");
      badge.className = "cq-chosen-badge cq-ui"; // UI, not content: anchoring skips it
      badge.dataset.cqGen = "1"; // and the version diff ignores it
      badge.textContent = "✓ your pick";
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
