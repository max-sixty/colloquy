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
 * Placement: the controls hang in the theme's rail, off the column's right edge,
 * on the line the change starts. Two elements say that, because one box cannot.
 * The row is the column's own child, inserted after the block the change sits
 * in: `left: 100%` is the page margin only where the column is the containing
 * block, and inside a positioned widget — a board card — it is that card's edge,
 * which no measurement can undo. Its line comes from a CSS anchor, an empty span
 * the widget prepends to itself and the row names: `top: anchor(top)` is the line
 * that span sits on, mid-sentence included, and the page reflows underneath with
 * both riding along. Hoisted, the row still meets the reader and the tab order
 * beside the change it decides, because it follows that change's own block.
 *
 * That margin is the theme's rail, reserved by a page that carries a row at all;
 * measuring is what finds it, not what makes it. Three things are measured, all by
 * one observer serving every suggestion on the page: whether the change is on
 * screen — one inside a collapsed container (a closed <details>, a tab that isn't
 * showing) has no line to hang on, and its row waits, hidden, for the reflow that
 * opens it; whether the page is wide enough to hold the row beside the column
 * (below the rail's breakpoint it keeps its whole width, and an open comment panel
 * takes the rest), where it isn't the row docks into flow where it was hoisted to,
 * a control line under the block it follows; and whether two rows land on top of
 * each other, which a translate nudges apart without touching layout. */
import { offer, once, quoted, says, sendAction, toast } from "/colloquy.js";

// Every row on the page against the anchor it hangs from, so one observer serves
// all of them and the pass can ask each whether its change is on screen.
const rows = new Map();
let pending = 0;
let observing = false;

const schedule = () => {
  cancelAnimationFrame(pending);
  pending = requestAnimationFrame(relayout);
};

// What the row hangs off, and so also what it hangs in.
const column = () => document.querySelector("main") || document.body;

// Undock every row, bring back the ones that were waiting, clear the nudges, then
// decide again from a clean layout. A row keeps the margin only if its change is
// rendered — an anchor that isn't leaves it hanging beside the block it was
// hoisted to rather than beside the change — and only if the page is wide enough
// to hold it there: body's own right edge is the page's, since the open comment
// panel is cleared by body's margin (syncLayout). The rest dock into flow.
const GAP = 4;
function relayout() {
  for (const row of rows.keys()) {
    row.classList.remove("cq-docked", "cq-waiting");
    row.style.transform = "";
  }
  const room = document.body.getBoundingClientRect().right;
  // Measure every row before moving any: docking one changes the flow the others
  // sit in, so a decision taken mid-pass reads a half-applied layout.
  const measured = [...rows].map(([row, anchor]) => ({
    row,
    rect: row.getBoundingClientRect(),
    // Whether the change is on screen, asked of the anchor rather than measured:
    // cq-suggestion has a box of no size (display: contents), and a collapsed
    // container reports its content's last rendered geometry rather than nothing.
    shown: anchor.checkVisibility(),
  }));
  const inMargin = [];
  for (const { row, rect, shown } of measured) {
    if (row.hidden) continue; // decided: there is nothing left to place
    if (!shown) row.classList.add("cq-waiting");
    else if (rect.right > room) row.classList.add("cq-docked");
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
    #anchor = null;

    connectedCallback() {
      // Re-connection — a card dragged to another column, a replay moving one —
      // must be harmless, and the row is no longer in the subtree that moves, so
      // hanging it again is what carries it along.
      if (!once(this)) return this.#hang();
      // Quoted material is exhibited, not offered: a suggestion inside a
      // <cq-specimen> shows what a pending change looks like, so it keeps the
      // marks the theme draws and never grows controls to decide it with.
      if (quoted(this)) return;
      // The line the change starts on, named for the row to hang from. Empty, so
      // it takes no space and says nothing; ids match [a-z0-9-] and `version check` keeps
      // them unique, so the id is already the dashed-ident the name needs.
      this.#anchor = offer("span", "cq-sug-line");
      this.#anchor.style.anchorName = `--sug-${this.id}`;
      this.prepend(this.#anchor);
      this.#row = offer("span", "cq-sug-actions");
      this.#row.style.positionAnchor = `--sug-${this.id}`;
      this.#row.dataset.cqFor = this.id; // which change it decides, for anyone reading the page
      this.#row.append(
        this.#button("accept", "✓ Accept"),
        this.#button("reject", "✗ Reject"),
      );
      this.#hang();
      if (!observing) {
        observing = true;
        // The body's box carries the horizontal question (viewport, comment
        // panel); the column's carries the vertical one, since anything that
        // moves content down the page changes its height.
        const observer = new ResizeObserver(schedule);
        observer.observe(document.body);
        observer.observe(column());
      }
    }

    disconnectedCallback() {
      rows.delete(this.#row);
      this.#row?.remove(); // it is no longer in the subtree that took it before
      schedule();
    }

    // The row belongs to the column rather than to the change, so that `left:
    // 100%` means the page margin (see the header). It goes after the change's
    // own top-level block, which is the reader's and the tab order's place for
    // it. A suggestion authored outside the column — `version check` accepts prose
    // anywhere in body — has none of that margin to reach, and keeps its row
    // beside itself; the measurement then docks it like any row without room.
    #hang() {
      if (!this.#row) return; // a quoted one grew none
      const col = column();
      let perch = this;
      while (perch.parentElement !== col && col.contains(perch.parentElement))
        perch = perch.parentElement;
      perch.after(this.#row);
      rows.set(this.#row, this.#anchor);
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
