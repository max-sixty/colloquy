/* cq-task: upgraded because its chip row (`owner`, `when`, each `tags` entry,
 * and a parent's done-fraction) outruns CSS's two pseudo-elements, and the
 * fraction is a count over the subtree that no stylesheet can compute. The
 * upgrade only inserts a built chip row after the leading <strong>; authored
 * text is preserved verbatim — an error here surfaces on the console and
 * leaves the prose untouched, so there is no failSoft. The guides, indent,
 * and status marker are theme CSS.
 *
 * The chips are real text for the same reason cq-milestone's are: the
 * reviewer has to be able to select and quote a word the page says. The
 * fraction counts leaf tasks — descendants with no cq-task children — because
 * the leaves are the work and a parent is the grouping of it; counting parents
 * too would double-count every level of structure. It is a count, not an
 * effort estimate, so it says "n/m done" rather than a percentage: a fraction
 * wears its basis on its face where a bare "40%" invites more trust than a
 * count deserves. */
import { once } from "/colloquy.js";

customElements.define(
  "cq-task",
  class extends HTMLElement {
    connectedCallback() {
      if (!once(this)) return;
      const labels = [
        this.getAttribute("owner"),
        this.getAttribute("when"),
        ...(this.getAttribute("tags")?.split(",") ?? []),
      ].filter(Boolean);
      const leaves = [...this.querySelectorAll("cq-task")].filter(
        (t) => !t.querySelector("cq-task"),
      );
      if (leaves.length) {
        const done = leaves.filter((t) => t.getAttribute("status") === "done").length;
        labels.push(`${done}/${leaves.length} done`);
      }
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
