/* cq-board: the one widget the reviewer edits directly, movable two ways that
 * share one send path and one gesture gate. Dragging is wired via the vendored
 * SortableJS (pointer-driven `forceFallback` mode, so touch works and the
 * follower is stylable — native HTML5 DnD is not used). The grip is a press
 * (`offer`), so the keyboard path needs no pointer: Enter grabs, arrows restate
 * the card's placement (announced through the live region), Enter drops, and
 * Escape or focus loss restores the origin. Either way the board wears
 * .cq-dragging for the whole gesture — the runtime's poll gates on it (no
 * version-follow, no foreign-action replay mid-gesture) — and a completed move
 * reports through #send as one absolute `move` action, indistinguishable on
 * the wire. applyAction states the absolute placement (card X sits at index i
 * of column C), so the poll's replay reconstructs a reload, syncs a second
 * tab, and no-ops on the sender. Presentation is theme CSS; authored content
 * is never replaced, so there is no failSoft.
 *
 * The board also says what it is non-visually: columns are labeled lists and
 * cards their items (#structure), and each grip is named for the column its
 * card now sits in (#names). Both are attributes on authored elements — the
 * light DOM stays verbatim, which is what the anchor pass and the version diff
 * walk. The theme's column heading is CSS generated content with empty alt
 * text, so the label reaches the tree once, as the list's name, rather than
 * twice. */
import Sortable from "/vendor/sortable.esm.js";
import {
  once,
  offer,
  quoted,
  says,
  sendAction,
  toast,
  announce,
  keyHelp,
  pageScroller,
  REDUCED,
  SCROLL,
} from "/colloquy.js";

// Registered on first upgrade, not at import: every x-upgrade module loads on
// every page, but the "?" overlay should list grip keys only where a board is.
let helpRegistered = false;

customElements.define(
  "cq-board",
  class extends HTMLElement {
    #grabbed = null; // {card, grip, from, index} — the origin, for cancel and no-op drops
    #superseded = null; // a grab folded into a pointer drag of the same card (see onStart)

    connectedCallback() {
      if (!once(this)) return;
      this.#structure();
      // A quoted board is an exhibit: no grips, no sortable, no grip keys in
      // the "?" overlay — it stays the static board the theme renders anyway.
      if (quoted(this)) return;
      if (!helpRegistered) {
        helpRegistered = true;
        keyHelp("On a card grip", [
          ["Enter", "grab, then drop, the card"],
          ["arrows", "move the grabbed card"],
          ["Esc", "cancel the move"],
        ]);
      }
      // Own cards only (:scope-deep would double-wire a nested board's cards).
      for (const card of this.querySelectorAll(":scope > cq-column > cq-card"))
        this.#grip(card);
      for (const col of this.querySelectorAll(":scope > cq-column")) this.#sortable(col);
      this.#names();
      // Grip names come from where their cards sit, so the board's own mutations
      // are what restate them — not the four paths that move a card (arrow step,
      // drag, cancel, replay), one of which would eventually forget, and one of
      // which is Sortable reparenting cards without telling us. Setting an
      // attribute records no childList mutation, so the pass can't feed itself.
      const moves = new MutationObserver(() => this.#names());
      for (const col of this.querySelectorAll(":scope > cq-column"))
        moves.observe(col, { childList: true });
    }

    // What a board is, said in roles: each column a labeled list, each card an
    // item in it. What says so visually is three boxes side by side — geometry,
    // which the accessibility tree doesn't carry — so without this a board is
    // one flat run of cards and Move buttons, and which column a card is in,
    // the one fact about it not in its own text, is never announced. Roles
    // describe rather than afford, so this holds for a quoted board too: an
    // exhibit is read like anything else, it just takes no input.
    //
    // The heading is written here too, rather than declared x-says and left to
    // the runtime's pass, because it is two things at once: the words a reviewer
    // selects to comment on the column, and the list's accessible name. The pass
    // renders one run of words at an edge and knows nothing about names, so it
    // would put these into the tree a second time under a list already carrying
    // them. Same marker (the theme styles [data-cq-said]) and same contract
    // (generated, so the diff looks away; not .cq-ui, so the anchor pass doesn't)
    // — a widget with a module of its own does the part only it can, which is
    // the line CLAUDE.md draws and cq-milestone's chips are the other case of.
    #structure() {
      for (const col of this.querySelectorAll(":scope > cq-column")) {
        col.setAttribute("role", "list");
        col.setAttribute("aria-label", col.getAttribute("label"));
        for (const card of this.#cards(col)) card.setAttribute("role", "listitem");
        if (col.querySelector(':scope > [data-cq-said="label"]')) continue;
        const heading = document.createElement("span");
        heading.dataset.cqSaid = "label";
        heading.dataset.cqGen = "1";
        // The column already carries these words as its name, so the heading is
        // the visible half only: the tree hears them once, the reviewer can still
        // select them, and the theme's generated copy is left to the no-script case.
        heading.setAttribute("aria-hidden", "true");
        heading.textContent = col.getAttribute("label");
        col.prepend(heading);
      }
    }

    // Every grip's name, in the idiom the live region already announces moves in
    // ("card — column"): the reviewer who lands on a grip by Tab hears where the
    // card is without having read the list it sits in.
    #names() {
      for (const col of this.querySelectorAll(":scope > cq-column")) {
        const where = col.getAttribute("label");
        for (const card of this.#cards(col)) {
          const name = `Move: ${this.#title(card)} — ${where}`;
          card.querySelector(":scope > .cq-grip")?.setAttribute("aria-label", name);
        }
      }
    }

    // A board inside a Claude reply detaches on every panel rebuild; no blur
    // fires for a detached grip, so drop a live grab here or it wedges the
    // .cq-dragging gate open — freezing action replay and version-follow.
    disconnectedCallback() {
      if (this.#grabbed) this.#cancel();
    }

    #title(card) {
      const strong = card.querySelector(":scope > strong");
      return (strong && says(strong)) || card.id;
    }
    #cards(col) {
      return [...col.querySelectorAll(":scope > cq-card")];
    }

    #grip(card) {
      const grip = offer("button", "cq-grip", "⠿");
      grip.title = "Drag to move — or Enter, then arrows"; // the name is #names'
      grip.addEventListener("keydown", (ev) => this.#key(ev, card, grip));
      // Leaving the grip drops the grab: restore the origin. Arrow moves reparent
      // the grip (which blurs it) and synchronously refocus, so by the time this
      // settles only a real departure still lacks focus.
      grip.addEventListener("blur", () => {
        if (this.#grabbed?.grip !== grip) return;
        setTimeout(() => {
          if (this.#grabbed?.grip === grip && document.activeElement !== grip)
            this.#cancel();
        });
      });
      card.append(grip);
    }

    #key(ev, card, grip) {
      if (this.#grabbed?.grip !== grip) {
        if (ev.key !== "Enter" && ev.key !== " ") return;
        // .cq-dragging without a grab is a live pointer drag — one gesture at a time.
        if (this.classList.contains("cq-dragging")) return;
        ev.preventDefault();
        const from = card.parentElement;
        this.#grabbed = { card, grip, from, index: this.#cards(from).indexOf(card) };
        this.classList.add("cq-dragging");
        card.classList.add("cq-lift");
        announce(
          `${this.#title(card)} grabbed — arrows move, Enter drops, Escape cancels`,
        );
        return;
      }
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        this.#drop();
      } else if (ev.key === "Escape") {
        ev.preventDefault();
        this.#cancel(true);
      } else if (ev.key === "ArrowUp" || ev.key === "ArrowDown") {
        ev.preventDefault();
        this.#step(card, grip, 0, ev.key === "ArrowDown" ? 1 : -1);
      } else if (ev.key === "ArrowLeft" || ev.key === "ArrowRight") {
        ev.preventDefault();
        this.#step(card, grip, ev.key === "ArrowRight" ? 1 : -1, 0);
      }
      // Any other key (Tab) proceeds natively; leaving the grip cancels via blur.
    }

    #step(card, grip, dCol, dRow) {
      const col = card.parentElement;
      if (dRow) {
        const cards = this.#cards(col);
        const at = cards.indexOf(card);
        const to = at + dRow;
        if (to < 0 || to >= cards.length) return;
        col.insertBefore(card, dRow > 0 ? cards[to].nextSibling : cards[to]);
      } else {
        const cols = [...this.querySelectorAll(":scope > cq-column")];
        const target = cols[cols.indexOf(col) + dCol];
        if (!target) return;
        // Same visual index, clamped to the target's end.
        target.insertBefore(card, this.#cards(target)[this.#cards(col).indexOf(card)] ?? null);
      }
      grip.focus({ preventScroll: true }); // reparenting blurred it (Chromium)
      card.scrollIntoView({ behavior: SCROLL, block: "nearest" });
      const now = card.parentElement;
      announce(
        `${this.#title(card)} — ${now.getAttribute("label")}, position ${
          this.#cards(now).indexOf(card) + 1
        } of ${this.#cards(now).length}`,
      );
    }

    #drop() {
      const { card, from, index } = this.#grabbed;
      this.#release();
      const to = card.parentElement;
      if (to === from && this.#cards(to).indexOf(card) === index) return;
      this.#send(card, from, index, to);
    }

    #cancel(refocus = false) {
      const { card, grip, from, index } = this.#grabbed;
      this.#release();
      this.#place(card, from, index);
      if (refocus) grip.focus({ preventScroll: true }); // Esc keeps focus; blur means it left
      announce(`${this.#title(card)} — move cancelled`);
    }

    #release() {
      this.#grabbed.card.classList.remove("cq-lift");
      this.#grabbed = null;
      this.classList.remove("cq-dragging");
    }

    // The one writer of "card X sits at index i among column C's cards": a
    // cancelled grab and a failed send restore the origin through it, and
    // replay places through it.
    #place(card, col, index) {
      const rest = this.#cards(col).filter((c) => c !== card);
      col.insertBefore(card, rest[index] ?? null);
    }

    // One completed move, drag or keyboard: an absolute placement, sent once.
    #send(card, from, oldIndex, to) {
      sendAction(this, "move", {
        card: card.id,
        to: to.id,
        index: this.#cards(to).indexOf(card),
      }).then((ok) => {
        if (ok) toast(`Moved to ${to.getAttribute("label")} — sent to Claude`);
        else this.#place(card, from, oldIndex);
      });
    }

    #sortable(col) {
      new Sortable(col, {
        group: `board-${this.id}`, // per board: two boards on a page don't cross-drag
        draggable: "cq-card",
        handle: ".cq-grip",
        // Named, not left to Sortable's search: its walk stops at body and hands back
        // document.scrollingElement, which isn't what scrolls here. Left to guess, a
        // drag toward a column below the fold would sit there and never scroll.
        scroll: pageScroller,
        forceFallback: true, // pointer-driven: stylable follower, touch, no native ghost
        fallbackTolerance: 4, // a click on the grip stays a click
        delay: 120,
        delayOnTouchOnly: true, // touch arms by press-hold so scrolling stays free
        animation: REDUCED ? 0 : 150,
        direction: "vertical",
        swapThreshold: 0.65, // hysteresis: boundaries don't flip-flop under a still pointer
        emptyInsertThreshold: 12,
        ghostClass: "cq-ghost", // the in-flow slot the drop would fill
        chosenClass: "cq-lift", // the pressed card
        dragClass: "cq-inhand", // the follower under the pointer
        onStart: (evt) => {
          // A pointer drag supersedes a live keyboard grab: Sortable's mid-drag
          // reparents fire no blur, so a stale grab would survive the drag and
          // its Escape would silently revert the recorded move. Dragging the
          // grabbed card folds the grab's origin into the drag — unsent arrow
          // steps become part of the one recorded move; dragging another card
          // cancels the grab exactly as focus loss would.
          if (this.#grabbed) {
            if (this.#grabbed.card === evt.item) {
              this.#superseded = this.#grabbed;
              this.#release();
            } else this.#cancel();
          }
          this.classList.add("cq-dragging");
        },
        onEnd: (evt) => {
          this.classList.remove("cq-dragging");
          const sup = this.#superseded;
          this.#superseded = null;
          const { item: card, to, newIndex } = evt;
          const from = sup ? sup.from : evt.from;
          const oldIndex = sup ? sup.index : evt.oldIndex;
          if (from === to && oldIndex === newIndex) return;
          this.#send(card, from, oldIndex, to);
        },
      });
    }

    // {card, to, index}: card X sits at index i among column C's cards. The moved
    // card FLIPs from its old position so a replay reads as motion, not teleport.
    applyAction(action, detail) {
      if (action !== "move") return;
      const card = document.getElementById(detail.card);
      const col = document.getElementById(detail.to);
      if (!card?.matches("cq-card") || !col?.matches("cq-column") || !this.contains(col)) return;
      const grip = card.querySelector(":scope > .cq-grip");
      const hadFocus = document.activeElement === grip;
      const first = card.getBoundingClientRect();
      this.#place(card, col, detail.index);
      if (hadFocus) grip.focus({ preventScroll: true }); // reparenting blurred it
      if (REDUCED) return;
      const last = card.getBoundingClientRect();
      const dx = first.left - last.left;
      const dy = first.top - last.top;
      if (dx || dy)
        card.animate(
          [{ transform: `translate(${dx}px, ${dy}px)` }, { transform: "none" }],
          { duration: 150, easing: "ease" },
        );
    }
  },
);
