/* cq-board: the one widget the reviewer edits directly. The upgrade wires
 * dragging — a grip on each card (draggable stays off the card itself so its
 * text keeps taking selection comments), columns as dropzones with a live
 * preview (the card moves as the pointer crosses positions) — and reports each
 * completed drop as a `move` action via sendAction. applyAction states the
 * absolute placement (card X sits at index i of column C), so the poll's
 * replay reconstructs a reload, syncs a second tab, and no-ops on the sender.
 * Presentation is entirely theme CSS; authored content is never replaced, so
 * there is no failSoft. */
import { once, sendAction, toast } from "/colloquy.js";

let drag = null; // {card, board, from, next, dropped} — one drag at a time
let lastCol = null;

function cardsOf(col) {
  return [...col.querySelectorAll(":scope > cq-card")].filter((c) => c !== drag?.card);
}

// The card the dragged one should sit before at pointer height y — null appends.
function positionIn(col, y) {
  for (const c of cardsOf(col)) {
    const r = c.getBoundingClientRect();
    if (y < r.top + r.height / 2) return c;
  }
  return null;
}

function setDropping(col) {
  if (lastCol && lastCol !== col) lastCol.classList.remove("cq-dropping");
  lastCol = col;
  col?.classList.add("cq-dropping");
}

customElements.define(
  "cq-board",
  class extends HTMLElement {
    connectedCallback() {
      if (!once(this)) return;
      // Own cards only (:scope-deep would double-wire a nested board's cards).
      for (const card of this.querySelectorAll(":scope > cq-column > cq-card"))
        this.#wireCard(card);
      for (const col of this.querySelectorAll(":scope > cq-column")) this.#wireColumn(col);
    }

    #wireCard(card) {
      const grip = document.createElement("span");
      grip.className = "cq-grip cq-ui"; // UI, not content: anchoring skips it
      grip.dataset.cqGen = "1"; // and the version diff ignores it
      grip.textContent = "⠿";
      grip.title = "Drag to another column";
      grip.draggable = true;
      grip.addEventListener("dragstart", (e) => {
        drag = { card, board: this, from: card.parentElement, next: card.nextElementSibling };
        // The board wears .cq-dragging synchronously (no visual rule targets it):
        // the runtime's poll gates — don't follow a new version, don't replay
        // foreign actions mid-gesture — key on that class, and the card's own
        // styled copy only lands a frame later.
        this.classList.add("cq-dragging");
        e.dataTransfer.setData("text/plain", card.id); // Firefox requires data to start
        e.dataTransfer.effectAllowed = "move";
        const r = card.getBoundingClientRect();
        e.dataTransfer.setDragImage(card, e.clientX - r.left, e.clientY - r.top);
        // After the drag image snapshots — the ghost shows the card at full opacity.
        // Guarded: if the drag already ended (dragend beat this frame), don't strand
        // the class on the card.
        requestAnimationFrame(() => {
          if (drag?.card === card) card.classList.add("cq-dragging");
        });
      });
      grip.addEventListener("dragend", () => {
        card.classList.remove("cq-dragging");
        this.classList.remove("cq-dragging");
        setDropping(null);
        // A cancelled drag (Esc, dropped outside) rewinds the live preview.
        if (drag && !drag.dropped) drag.from.insertBefore(card, drag.next);
        drag = null;
      });
      card.append(grip);
    }

    #wireColumn(col) {
      col.addEventListener("dragover", (e) => {
        if (drag?.board !== this) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        setDropping(col);
        const before = positionIn(col, e.clientY);
        if (drag.card.parentElement !== col || drag.card.nextElementSibling !== before)
          col.insertBefore(drag.card, before);
      });
      col.addEventListener("drop", (e) => {
        if (drag?.board !== this) return;
        e.preventDefault();
        drag.dropped = true;
        const { card, from, next } = drag;
        if (card.parentElement === from && card.nextElementSibling === next) return;
        const index = [...card.parentElement.querySelectorAll(":scope > cq-card")].indexOf(card);
        sendAction(this, "move", { card: card.id, to: card.parentElement.id, index }).then(
          (ok) => {
            if (ok) toast(`Moved to ${card.parentElement.getAttribute("label")} — sent to Claude`);
            // Unsent means unrecorded: rewind rather than show an edit Claude
            // will never see. (post already toasted the failure.) `next` may have
            // moved by the time the send fails — fall back to appending.
            else from.insertBefore(card, next?.parentElement === from ? next : null);
          },
        );
      });
    }

    // {card, to, index}: card X sits at index i among column C's cards.
    applyAction(action, detail) {
      if (action !== "move") return;
      const card = document.getElementById(detail.card);
      const col = document.getElementById(detail.to);
      if (!card?.matches("cq-card") || !col?.matches("cq-column") || !this.contains(col)) return;
      const rest = [...col.querySelectorAll(":scope > cq-card")].filter((c) => c !== card);
      col.insertBefore(card, rest[detail.index] ?? null);
    }
  },
);
