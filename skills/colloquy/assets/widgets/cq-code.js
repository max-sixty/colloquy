/* cq-code: upgraded because it splits lines. The body is code verbatim (data);
 * `hi` highlights line ranges; authored cq-note children anchor a remark at a
 * line. Notes are moved, never rewritten, so their text stays quotable — the
 * annotated-walkthrough shape.
 *
 * `lang` colors it. A token can span a newline (a docstring, a block comment)
 * and a line is the unit this widget numbers, so the tokens are cut at each
 * newline (tokenLines) rather than the source being colored a line at a time —
 * coloring line by line would restart the tokenizer inside the docstring and
 * read its second line as code. */
import { once, failSoft, settle, synNodes, syntax, tokenLines } from "/colloquy.js";

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
      // Registered with settle() so the runtime holds the first anchor pass until
      // the lines are in — the tokenizer loads lazily, so even an uncolored block
      // lands a microtask late and one writer has to finish before another reads.
      settle(this.render());
    }

    async render() {
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
        const lang = this.getAttribute("lang");
        // One representation either way: an uncolored block is the whole source as a
        // single roleless token, so the line walk below has one shape to handle.
        const lines = tokenLines(lang ? await syntax(source, lang) : [{ text: source }]);
        const hi = parseRanges(this.getAttribute("hi"));
        const byLine = new Map();
        for (const note of notes) {
          const at = Number(note.getAttribute("at"));
          byLine.set(at, [...(byLine.get(at) ?? []), note]);
        }
        const pre = document.createElement("pre");
        lines.forEach((tokens, i) => {
          const n = i + 1;
          const line = document.createElement("span");
          line.className = `cq-code-line${hi.has(n) ? " hi" : ""}`;
          line.append(...synNodes(tokens), "\n");
          pre.append(line);
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
