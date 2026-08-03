/* cq-suggestion: Claude's edit to content the user has already seen, offered
 * as a proposal rather than shipped as a fait accompli. The user accepts or
 * rejects it in place; the outcome rides the action channel cq-board opened, and
 * the next version carries the settled markup.
 *
 * Deciding is the end of the matter on screen: the element settles to the
 * surviving slot there and then (the theme drops every mark from it), exactly as a
 * dragged card sits where it was dropped before the honoring version exists —
 * the live view is the version plus the user's actions replayed on it. So
 * applyAction states an absolute outcome, which makes a reload, a second tab,
 * and the sender itself all converge on the same view. A pick can be cleared by
 * clicking its mark again; a decision can't. Changing your mind is a comment,
 * and the version reverses it.
 *
 * What deciding must not be is the page rearranging itself under the hand that
 * pressed. It was both. A block change is a struck old paragraph over a tinted
 * new one, so accepting took 179 measured pixels out of the middle of the page in
 * one frame, and everything below jumped up under the pointer; and the row the
 * user had just pressed cleared itself in the same frame, leaving a corner toast
 * as the only evidence that anything had been done at all. Two rules answer it,
 * both of them already written down. Where something has to move it moves as
 * motion, so the retired slot folds over a fifth of a second and the eye follows
 * the sentence to where it went. And the pressed control's own line holds still:
 * the row stays, the control the user pressed says what it did ("✓ Accepted"),
 * and its pair goes without giving up its room. The rail is reserved for the
 * page's life whether or not any row is left in it, so the standing record costs
 * nothing that was going to be reclaimed — and a reader who looks back at the
 * margin can see which changes they took.
 *
 * The word a decision leaves behind has its room from the start: a control that
 * took the room for two more glyphs at the moment it was pressed would move its
 * neighbour on the one line where nothing may. Each control reserves the width of
 * its own decided word as the row is built (reserve), measured in the control's
 * live face rather than stated as a number, so the reservation re-measures itself
 * when the font moves — and the one table below is what the controls write and
 * what they reserve, so the two cannot drift.
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
import {
  agentName,
  motion,
  offer,
  once,
  quoted,
  reserve,
  says,
  sendAction,
  toast,
} from "/colloquy.js";

// How long the retired slot takes to fold away. Long enough that the eye can follow a
// paragraph's worth of page closing, short enough that the decision still reads as
// having happened at the press: the board's own FLIP is 150ms over a card's width, and
// this is a taller distance travelled by the whole column below it.
const FOLD_MS = 220;

// Each control's word in both states — what #name writes, and what the control
// reserves room for, out of the one table so neither can outgrow the other.
const WORDS = {
  accept: ["✓ Accept", "✓ Accepted"],
  reject: ["✗ Reject", "✗ Rejected"],
};
const verb = (btn) => (btn.matches(".cq-sug-accept") ? "accept" : "reject");

// Every row on the page against the anchor it hangs from, so one observer serves
// all of them and the pass can ask each whether its change is on screen.
const rows = new Map();
let pending = 0;
let observing = false;
let railStated = false; // --rail is measured off the first row and holds for the page

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
    #motion = null; // the fold in flight, so a rewind can take it back

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
      this.#row.append(this.#button("accept"), this.#button("reject"));
      this.#hang();
      // In the document now, so each control measures its decided word in the face it
      // actually renders in and floors itself there — the line the press is made on
      // holds still when the word changes (see the module header).
      for (const btn of this.#row.querySelectorAll(":scope > [role='button']"))
        reserve(btn, WORDS[verb(btn)]);
      // The rail is the row it holds: measured off the first row once its controls
      // hold their decided words' room, and stated on the root element — the page's
      // own inline style, so an exported copy keeps the value it was rendered with.
      // theme.css spends it (body's padding-right) and deliberately states no number.
      if (!railStated) {
        railStated = true;
        const width =
          this.#row.getBoundingClientRect().width +
          parseFloat(getComputedStyle(this.#row).marginLeft);
        document.documentElement.style.setProperty("--rail", Math.ceil(width) + "px");
      }
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
    // a thing to do, and a press is a span (see offer) whatever it says. cq-pill is
    // the margin's shape, the runtime's word too.
    #button(outcome) {
      const btn = offer("button", `cq-pill cq-sug-${outcome}`);
      btn.onclick = () => this.#decide(outcome);
      this.#name(btn, false, this.#label());
      return btn;
    }

    // Everything a control says, in the state it is in: the word it shows (from
    // WORDS, the same table its reservation is measured from), and the name that has
    // to carry the change as well, since the visible word says only the outcome. The
    // change's own words come in rather than being read here, because settling
    // retires the slot they live in and a name asked for afterwards would answer the
    // id. Both controls restate together — the pair's word flips too, unseen inside
    // its hidden box and inside the room both reserved.
    #name(btn, decided, change) {
      const kind = verb(btn);
      btn.textContent = WORDS[kind][decided ? 1 : 0];
      btn.setAttribute(
        "aria-label",
        `${kind === "accept" ? "Accept" : "Reject"}${decided ? "ed" : ""} the suggested change: ${change}`,
      );
      // A decision is the end of the matter, so the record it leaves is a record and
      // not a control: it keeps its place and its focus ring, and refuses a press the
      // way #decide already does.
      btn.setAttribute("aria-disabled", String(decided));
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
      // then named the widget's id instead of the words the user just judged.
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
          `${outcome === "accept" ? "Accepted" : "Rejected"} “${label}” — sent to ${agentName()}`,
        );
        return true;
      });
    }

    #settle(outcome) {
      // A settle that changes nothing does nothing, which is what makes the poll's
      // replay of this tab's own decision the no-op an absolute action promises to be.
      // The attribute was idempotent on its own and the fold is not: replayed, it
      // folded a slot that had already folded, from a height it no longer had.
      if ((this.dataset.cqState ?? null) === (outcome ?? null)) return;
      // A send the server refused rewinds a decision that may still be folding, and a
      // fold outliving the state it was playing would leave the slot to reappear
      // whenever it happened to land. Cancelling it runs the same cleanup finishing
      // does, so the slot comes back to whatever the state now says.
      this.#motion?.cancel();
      // Both of these are read before the state moves, because the state is what
      // retires a slot: its words leave the page's reading with it, and its box stops
      // being drawn at all.
      const change = this.#label();
      const fold = outcome && this.#fold(outcome);
      if (outcome) this.dataset.cqState = outcome;
      else delete this.dataset.cqState;
      if (this.#row) {
        // The row stays; what changes is which of the two controls is speaking. A
        // quoted one grew none.
        if (outcome) this.#row.dataset.cqOutcome = outcome;
        else delete this.#row.dataset.cqOutcome;
        for (const btn of this.#row.querySelectorAll(":scope > [role='button']"))
          this.#name(btn, Boolean(outcome), change);
      }
      fold?.();
      schedule(); // the rows below may no longer need the nudge they had
      // The banner's count of what the page is still asking is derived from the page,
      // so tell it the page changed rather than making it poll the DOM.
      document.dispatchEvent(new CustomEvent("cq-answered"));
    }

    // The retired slot's room, given back as motion rather than taken in a frame. Only
    // where there is room worth following: a slot holding block content is the case that
    // moves the page, and an inline one swaps a few words inside a line the reader is
    // looking at.
    //
    // Measured before the decision and played after it, so the state the rest of the
    // page reads is true from the first frame — the log has it, the banner's count has
    // it, a second tab converging on it has it — while the pixels catch up. The inline
    // display outranks the rule that hides the slot for exactly as long as the fold
    // lasts, and nothing but this function writes it.
    //
    // The height is stated as a border box, whatever the slot's own sizing is. The
    // measurement to hand is the rendered box (padding included, since the block form
    // pads its slots), and starting a content-box height there would open the fold two
    // pixels taller than the paragraph it is replacing — a jump on the first frame, in
    // the one animation written to remove one.
    #fold(outcome) {
      const going = this.querySelector(
        outcome === "accept" ? ":scope > cq-old" : ":scope > cq-new",
      );
      if (!going) return null;
      const style = getComputedStyle(going);
      if (style.display !== "block") return null;
      const from = {
        height: going.getBoundingClientRect().height + "px",
        marginTop: style.marginTop,
        marginBottom: style.marginBottom,
        paddingTop: style.paddingTop,
        paddingBottom: style.paddingBottom,
        opacity: 1,
      };
      const to = Object.fromEntries(Object.keys(from).map((k) => [k, "0px"]));
      to.opacity = 0;
      return () => {
        going.style.display = "block";
        going.style.boxSizing = "border-box";
        going.style.overflow = "hidden";
        const played = (this.#motion = motion(going, [from, to], FOLD_MS));
        const done = () => {
          going.style.display = "";
          going.style.boxSizing = "";
          going.style.overflow = "";
          if (this.#motion === played) this.#motion = null;
        };
        // Cancelling rejects `finished`, which is a rewind rather than a fault:
        // caught, so it is not an unhandled rejection, and the same hand-back runs
        // either way. A reader who asked for less motion gets no animation at all
        // (motion returns null), so the hand-back runs at once and the collapse is
        // the frame of the press.
        played ? played.finished.catch(() => {}).then(done) : done();
      };
    }

    // accept | reject: the outcome is absolute, so replaying the sender's own
    // action is a no-op and a second tab lands in the same state.
    applyAction(action) {
      if (action === "accept" || action === "reject") this.#settle(action);
    }
  },
);
