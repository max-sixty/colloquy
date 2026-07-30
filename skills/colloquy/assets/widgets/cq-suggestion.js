/* cq-suggestion: Claude's edit to content the reviewer has already seen, offered
 * as a proposal rather than shipped as a fait accompli. The reviewer accepts or
 * rejects it in place; the outcome rides the action channel cq-board opened, and
 * the next version carries the settled markup.
 *
 * Deciding is the end of the matter on screen: the element collapses to the
 * settled slot immediately (the theme drops every mark from it), exactly as a
 * dragged card sits where it was dropped before the honoring version exists —
 * the live view is the version plus the reviewer's actions replayed on it. So
 * applyAction states an absolute outcome, which makes a reload, a second tab,
 * and the sender itself all converge on the same view. A pick can be cleared by
 * clicking its mark again; a decision can't, because settling deliberately
 * leaves nothing behind to click — that is the whole point of it reading as
 * ordinary prose. Changing your mind is a comment, and the version reverses it.
 *
 * Placement: the controls are the element's first child, absolutely positioned
 * with only `left` set, so the theme's `main { position: relative }` gives them
 * the column's right edge while their static position keeps them on the line
 * the change starts — the page can reflow freely underneath and they ride
 * along. The room they hang in is the theme's rail, reserved by a page that
 * carries a row at all; measuring is what finds it, not what makes it. Two
 * things still have to be measured, both by one observer serving every
 * suggestion on the page: whether there is margin enough to hold the controls
 * (inside a card there is none, and below the rail's breakpoint the page keeps
 * its whole width), where there isn't they dock into flow; and whether two rows
 * land on top of each other, which a translate nudges apart without touching
 * layout. */
import { offer, once, quoted, says, sendAction, toast } from "/colloquy.js";

// Every row on the page, so one observer serves all of them.
const rows = new Set();
let pending = 0;
let observing = false;

const schedule = () => {
  cancelAnimationFrame(pending);
  pending = requestAnimationFrame(relayout);
};

// Undock all and clear the nudges, then decide again from a clean layout. A row
// keeps the margin only if it is hanging off the column itself — a suggestion
// inside a positioned widget (a board card) would otherwise anchor to that and
// land back inside the text — and only if the page is wide enough to hold it
// there: body's own right edge is the page's, since the open comment panel is
// cleared by body's margin (syncLayout). The rest dock into flow. A row with no
// box is inside a collapsed container and waits for the reflow that opens it.
const GAP = 4;
function relayout() {
  for (const row of rows) {
    row.classList.remove("cq-docked");
    row.style.transform = "";
  }
  const column = document.querySelector("main") || document.body;
  const room = document.body.getBoundingClientRect().right;
  // Measure every row before moving any: docking one changes the flow the others
  // sit in, so a decision taken mid-pass reads a half-applied layout.
  const measured = [...rows].map((row) => ({ row, rect: row.getBoundingClientRect() }));
  const inMargin = [];
  for (const { row, rect } of measured) {
    if (!rect.width) continue;
    if (rect.right > room || row.offsetParent !== column) row.classList.add("cq-docked");
    else inMargin.push(row);
  }
  // Those still in the margin walk down the page, each pushed clear of the one
  // above. Re-measured, because docking moved the text they hang beside — and
  // carried here as a list, rather than read back off the class just written.
  const placed = inMargin
    .map((row) => ({ row, rect: row.getBoundingClientRect() }))
    .sort((a, b) => a.rect.top - b.rect.top);
  let floor = -Infinity;
  for (const { row, rect } of placed) {
    const push = Math.max(0, floor + GAP - rect.top);
    if (push) row.style.transform = `translateY(${push}px)`;
    floor = rect.top + push + rect.height;
  }
}

customElements.define(
  "cq-suggestion",
  class extends HTMLElement {
    #row = null;

    connectedCallback() {
      if (!once(this)) return;
      // Quoted material is exhibited, not offered: a suggestion inside a
      // <cq-specimen> shows what a pending change looks like, so it keeps the
      // marks the theme draws and never grows controls to decide it with.
      if (quoted(this)) return;
      this.#row = offer("span", "cq-sug-actions");
      this.#row.append(
        this.#button("accept", "✓ Accept"),
        this.#button("reject", "✗ Reject"),
      );
      // First child, so the static position the theme leans on is the start of
      // the change rather than its end.
      this.prepend(this.#row);
      rows.add(this.#row);
      if (!observing) {
        observing = true;
        // The body's box carries the horizontal question (viewport, comment
        // panel); the column's carries the vertical one, since anything that
        // moves content down the page changes its height.
        const observer = new ResizeObserver(schedule);
        observer.observe(document.body);
        const column = document.querySelector("main");
        if (column) observer.observe(column);
      }
      schedule();
    }

    disconnectedCallback() {
      rows.delete(this.#row);
      schedule();
    }

    // Through `offer` like every other injected control, so the markers and the
    // element are the runtime's one answer rather than this widget's: "✓ Accept" is
    // a thing to do, and a press is a span (see offer) whatever it says.
    #button(outcome, label) {
      const btn = offer("button", `cq-sug-${outcome}`, label);
      btn.setAttribute(
        "aria-label",
        `${outcome === "accept" ? "Accept" : "Reject"} the suggested change: ${this.#label()}`,
      );
      btn.onclick = () => this.#decide(outcome);
      return btn;
    }

    // What the change is about, for the button's label and the toast: the
    // proposal where there is one, since that is what accepting brings about —
    // a deletion has only the markup it would remove.
    #label() {
      const slot =
        this.querySelector(":scope > cq-new") || this.querySelector(":scope > cq-old");
      const text = (slot && says(slot)) || this.id;
      return text.length > 48 ? text.slice(0, 48) + "…" : text;
    }

    accept() {
      return this.#decide("accept");
    }

    #decide(outcome) {
      if (this.dataset.cqState) return Promise.resolve(true);
      // Read before settling: deciding retires a slot, a retired slot leaves the page's
      // reading, and `says` on what has left the reading answers nothing — the toast
      // then named the widget's id instead of the words the reviewer just judged.
      const label = this.#label();
      this.#settle(outcome);
      // Accepting the fix answers the thread it was written for, so the same
      // event carries it: the mapping is snapshotted into the action, because
      // the honoring version retires this wrapper — attribute and all — and a
      // second POST could fail alone, leaving the outcome and the resolution
      // disagreeing with no repair path.
      const comment = this.getAttribute("resolves");
      const detail = outcome === "accept" && comment ? { resolves: comment } : {};
      return sendAction(this, outcome, detail).then((ok) => {
        if (!ok) {
          this.#settle(null); // unsent means unrecorded: back to pending
          return false;
        }
        toast(
          `${outcome === "accept" ? "Accepted" : "Rejected"} “${label}” — sent to Claude`,
        );
        return true;
      });
    }

    #settle(outcome) {
      if (outcome) this.dataset.cqState = outcome;
      else delete this.dataset.cqState;
      if (this.#row) this.#row.hidden = Boolean(outcome); // a quoted one grew none
      schedule(); // one row fewer: the rows below it may no longer need a nudge
      // The banner's pending count is derived from the page, so tell it the page
      // changed rather than making it poll the DOM.
      document.dispatchEvent(new CustomEvent("cq-suggestions"));
    }

    // accept | reject: the outcome is absolute, so replaying the sender's own
    // action is a no-op and a second tab lands in the same state.
    applyAction(action) {
      if (action === "accept" || action === "reject") this.#settle(action);
    }
  },
);
