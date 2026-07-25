/* cq-board: the one widget the reviewer edits directly. The upgrade wires
 * dragging via the vendored SortableJS (pointer-driven `forceFallback` mode, so
 * touch works and the follower is stylable — native HTML5 DnD is not used) and
 * reports each completed drop as a `move` action via sendAction. The grip stays
 * the handle so card text keeps taking selection comments. During a drag the
 * board wears .cq-dragging — the runtime's poll gates on it (no version-follow,
 * no foreign-action replay mid-gesture). applyAction states the absolute
 * placement (card X sits at index i of column C), so the poll's replay
 * reconstructs a reload, syncs a second tab, and no-ops on the sender.
 * Presentation is theme CSS; authored content is never replaced, so there is no
 * failSoft. */
import Sortable from "/vendor/sortable.esm.js";
import { once, sendAction, toast } from "/colloquy.js";

const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;

customElements.define(
  "cq-board",
  class extends HTMLElement {
    connectedCallback() {
      if (!once(this)) return;
      // Own cards only (:scope-deep would double-wire a nested board's cards).
      for (const card of this.querySelectorAll(":scope > cq-column > cq-card"))
        this.#grip(card);
      for (const col of this.querySelectorAll(":scope > cq-column")) this.#sortable(col);
    }

    #grip(card) {
      const grip = document.createElement("span");
      grip.className = "cq-grip cq-ui"; // UI, not content: anchoring skips it
      grip.dataset.cqGen = "1"; // and the version diff ignores it
      grip.textContent = "⠿";
      grip.title = "Drag to move";
      card.append(grip);
    }

    #sortable(col) {
      new Sortable(col, {
        group: `board-${this.id}`, // per board: two boards on a page don't cross-drag
        draggable: "cq-card",
        handle: ".cq-grip",
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
        onStart: () => this.classList.add("cq-dragging"),
        onEnd: (evt) => {
          this.classList.remove("cq-dragging");
          const { item: card, from, to, oldIndex, newIndex } = evt;
          if (from === to && oldIndex === newIndex) return;
          sendAction(this, "move", { card: card.id, to: to.id, index: newIndex }).then(
            (ok) => {
              if (ok) toast(`Moved to ${to.getAttribute("label")} — sent to Claude`);
              // Unsent means unrecorded: restore the original slot by index rather
              // than show an edit Claude will never see. (post already toasted.)
              else {
                const rest = [...from.querySelectorAll(":scope > cq-card")].filter(
                  (c) => c !== card,
                );
                from.insertBefore(card, rest[oldIndex] ?? null);
              }
            },
          );
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
      const first = card.getBoundingClientRect();
      const rest = [...col.querySelectorAll(":scope > cq-card")].filter((c) => c !== card);
      col.insertBefore(card, rest[detail.index] ?? null);
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
