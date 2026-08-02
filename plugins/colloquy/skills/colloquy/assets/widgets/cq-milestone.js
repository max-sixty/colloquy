/* cq-milestone: upgraded because its chip row (`when` plus each `tags` entry)
 * outruns CSS's two pseudo-elements. The upgrade only inserts a built chip row
 * after the leading <strong>; authored text is preserved verbatim — an error
 * here surfaces on the console and leaves the prose untouched, so there is no
 * failSoft (which replaces content, the data-widget degradation). The rail and
 * status dot are theme CSS.
 *
 * The chips are real text for the same reason every x-says attribute is: the
 * reviewer has to be able to select and quote a word the page says. They aren't
 * x-says because that pass renders one run of words at an edge a pseudo-element
 * could have reached, while this row is a list placed after the title — which is
 * the line past which a widget needs a module of its own. */
import { once } from "/colloquy.js";

customElements.define(
  "cq-milestone",
  class extends HTMLElement {
    connectedCallback() {
      if (!once(this)) return;
      const labels = [
        this.getAttribute("when"),
        ...(this.getAttribute("tags")?.split(",") ?? []),
      ].filter(Boolean);
      if (!labels.length) return;
      const row = document.createElement("div");
      row.className = "cq-chips";
      row.dataset.cqGen = "1"; // generated, not authored — the version diff skips it
      for (const label of labels)
        row.append(
          Object.assign(document.createElement("span"), { textContent: label }),
        );
      const title = this.querySelector(":scope > strong");
      if (title) title.after(row);
      else this.prepend(row);
    }
  },
);
