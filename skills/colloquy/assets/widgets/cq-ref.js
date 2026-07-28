/* cq-ref: an inline source reference, upgraded because it computes — it resolves
 * `src="path:line"` against the page's cq-base template into a link. A void widget
 * (no authored children), so it renders freely; without a cq-base meta it renders
 * as plain code, still readable. */
import { once, failSoft, refUrl } from "/colloquy.js";

customElements.define(
  "cq-ref",
  class extends HTMLElement {
    connectedCallback() {
      if (!once(this)) return;
      this.dataset.cqGen = "1"; // everything inside is generated; the version diff skips it
      try {
        const src = this.getAttribute("src");
        const m = src.match(/^(.*?)(?::(\d+))?$/);
        const path = m[1];
        const line = m[2];
        const label = path.split("/").pop() + (line ? `:${line}` : "");
        const url = refUrl(path, line);
        if (url) {
          const a = document.createElement("a");
          a.href = url;
          a.textContent = label;
          this.replaceChildren(a);
        } else {
          this.replaceChildren(label);
        }
        this.title = src;
      } catch (err) {
        failSoft(this, err);
      }
    }
  },
);
