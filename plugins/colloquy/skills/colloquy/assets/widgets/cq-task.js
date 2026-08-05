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
 * count deserves.
 *
 * `status` is also the widget's agent channel (x-report): a worker's report
 * replays here through applyAction, which states the absolute value — the
 * attribute — so a reload or a second tab converges and re-applying is a
 * no-op. The status marker follows the attribute through theme CSS for free;
 * what has to be recomputed is the done-fraction, a count over the whole
 * tree, so every task's chip row re-renders rather than this one guessing
 * which ancestors the count reaches. Rebuilding is idempotent, and the rows
 * are generated (data-cq-gen), so the diff and the anchor pass already look
 * away. */
import { once } from "/colloquy.js";

function renderChips(task) {
  task.querySelector(":scope > .cq-chips[data-cq-gen]")?.remove();
  const labels = [
    task.getAttribute("owner"),
    task.getAttribute("when"),
    ...(task.getAttribute("tags")?.split(",") ?? []),
  ].filter(Boolean);
  const leaves = [...task.querySelectorAll("cq-task")].filter(
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
    row.append(Object.assign(document.createElement("span"), { textContent: label }));
  const title = task.querySelector(":scope > strong");
  if (title) title.after(row);
  else task.prepend(row);
}

customElements.define(
  "cq-task",
  class extends HTMLElement {
    connectedCallback() {
      if (!once(this)) return;
      renderChips(this);
    }

    applyAction(action, detail) {
      if (action !== "status") return;
      this.setAttribute("status", detail.status);
      // The tree tops out at a cq-tasks (x-parent), and the fractions are
      // counts over it, so the whole tree's rows re-render.
      for (const task of this.closest("cq-tasks").querySelectorAll("cq-task"))
        renderChips(task);
    }
  },
);
