/* cq-code: upgraded because it splits lines. The body is code verbatim (data);
 * `hi` highlights line ranges; authored cq-note children anchor a remark at a
 * line. Notes are moved, never rewritten, so their text stays quotable — the
 * annotated-walkthrough shape. */
import { once, failSoft } from "/colloquy.js";

// "3-5,8" → Set of line numbers.
function parseRanges(spec) {
  const lines = new Set();
  if (!spec) return lines;
  for (const part of spec.split(",")) {
    const [from, to] = part.split("-").map(Number);
    for (let n = from; n <= (to ?? from); n++) lines.add(n);
  }
  return lines;
}

customElements.define(
  "cq-code",
  class extends HTMLElement {
    connectedCallback() {
      if (!once(this)) return;
      // Split authored content: text nodes are the code, cq-note children are
      // annotations. A note sits on its own authored line, so one newline is
      // swallowed after each to keep line numbers honest.
      const notes = [...this.querySelectorAll(":scope > cq-note")];
      let source = "";
      let afterNote = false;
      for (const node of this.childNodes) {
        if (node.nodeType === Node.TEXT_NODE) {
          source += afterNote ? node.data.replace(/^\n/, "") : node.data;
          afterNote = false;
        } else if (node.tagName === "CQ-NOTE") {
          afterNote = true;
        }
      }
      source = source.replace(/^\n+/, "").replace(/\s+$/, "");
      try {
        const hi = parseRanges(this.getAttribute("hi"));
        const byLine = new Map();
        for (const note of notes) {
          const at = Number(note.getAttribute("at"));
          byLine.set(at, [...(byLine.get(at) ?? []), note]);
        }
        const pre = document.createElement("pre");
        const lines = source.split("\n");
        lines.forEach((text, i) => {
          const n = i + 1;
          pre.append(
            Object.assign(document.createElement("span"), {
              className: `cq-code-line${hi.has(n) ? " hi" : ""}`,
              textContent: text + "\n",
            }),
          );
          for (const note of byLine.get(n) ?? []) pre.append(noteNode(note));
          byLine.delete(n);
        });
        for (const notes of byLine.values()) for (const note of notes) pre.append(noteNode(note));
        this.replaceChildren(pre);
        this.classList.add("cq-rendered");
      } catch (err) {
        failSoft(this, err, source);
      }
    }
  },
);

function noteNode(note) {
  const box = document.createElement("div");
  box.className = "cq-code-note";
  box.append(note); // moved, not copied: the authored element keeps its text and id
  return box;
}
