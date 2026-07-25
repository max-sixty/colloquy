/* cq-diff: upgraded because it parses. The body is a unified diff (data, not
 * prose), rendered as one <details> per file — native disclosure — with add/del
 * coloring and per-file +/− counts. The evidence rule mechanized for code
 * changes: paste the real diff instead of paraphrasing it. */
import { once, failSoft } from "/colloquy.js";

// One entry per file: {path, adds, dels, lines: [{kind, text}]} where kind is
// add | del | ctx | hunk | meta. Tolerates both `diff --git` and bare ---/+++
// file headers; anything before the first header fails the parse. A `--- ` line
// counts as a header only when `+++ ` follows it — a *deleted* line whose
// content starts with `-- ` (a SQL comment, say) renders as `--- …` too, and
// must stay a deletion.
function parseDiff(text) {
  const files = [];
  let file = null;
  let expectPlus = false;
  const start = (path) => {
    file = { path, adds: 0, dels: 0, lines: [] };
    files.push(file);
  };
  const lines = text.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.startsWith("diff --git ")) {
      start(line.split(" b/").pop());
      expectPlus = false;
      continue;
    }
    if (line.startsWith("--- ") && lines[i + 1]?.startsWith("+++ ")) {
      // A bare ---/+++ pair opens a file unless `diff --git` already did.
      if (!file || file.lines.some((l) => l.kind === "hunk")) start("");
      file.lines.push({ kind: "meta", text: line });
      expectPlus = true;
      continue;
    }
    if (file === null) throw new Error("not a unified diff (no file header)");
    if (expectPlus && line.startsWith("+++ ")) {
      expectPlus = false;
      const path = line.slice(4).replace(/^b\//, "");
      if (!file.path && path !== "/dev/null") file.path = path;
      file.lines.push({ kind: "meta", text: line });
    } else if (line.startsWith("@@")) {
      file.lines.push({ kind: "hunk", text: line });
    } else if (line.startsWith("+")) {
      file.adds++;
      file.lines.push({ kind: "add", text: line });
    } else if (line.startsWith("-")) {
      file.dels++;
      file.lines.push({ kind: "del", text: line });
    } else if (line.startsWith("index ") || line.startsWith("new file") || line.startsWith("deleted file") || line.startsWith("similarity ") || line.startsWith("rename ") || line.startsWith("Binary files ")) {
      file.lines.push({ kind: "meta", text: line });
    } else {
      file.lines.push({ kind: "ctx", text: line });
    }
  }
  return files;
}

function fileNode(file) {
  const details = document.createElement("details");
  details.open = true;
  const summary = document.createElement("summary");
  summary.append(
    Object.assign(document.createElement("code"), { textContent: file.path || "(unnamed file)" }),
    Object.assign(document.createElement("span"), {
      className: "cq-diff-stat",
      textContent: `+${file.adds} −${file.dels}`,
    }),
  );
  const pre = document.createElement("pre");
  for (const { kind, text } of file.lines)
    pre.append(Object.assign(document.createElement("span"), { className: kind, textContent: text + "\n" }));
  details.append(summary, pre);
  return details;
}

customElements.define(
  "cq-diff",
  class extends HTMLElement {
    connectedCallback() {
      if (!once(this)) return;
      // Only blank edge lines are trimmed: diff content is column-sensitive
      // (a leading space means context), so the body is authored at column 0.
      const source = this.textContent.replace(/^\n+/, "").replace(/\n\s*$/, "");
      try {
        const files = parseDiff(source);
        if (!files.length) throw new Error("empty diff");
        this.replaceChildren(...files.map(fileNode));
        this.classList.add("cq-rendered");
      } catch (err) {
        failSoft(this, err, source);
      }
    }
  },
);
