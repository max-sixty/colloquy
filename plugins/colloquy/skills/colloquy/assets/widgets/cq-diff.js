/* cq-diff: upgraded because it parses. The body is a unified diff (data, not
 * prose), rendered as one <details> per file — native disclosure — with add/del
 * tints and per-file +/− counts. The evidence rule mechanized for code changes:
 * paste the real diff instead of paraphrasing it.
 *
 * Syntax colour rides on top, from each file's own path (langForPath): the tints
 * are the widget's statement about a line and the token colours are the file's
 * about its words, and they are a background and an ink, so neither is spending
 * the other's channel. A diff sits beside cq-code on the pages that carry both —
 * pr-walkthrough shows the same four lines twice — and leaving one plain says the
 * evidence is not code.
 *
 * What gets tokenized is a hunk, one side at a time, with the +/−/space column
 * cut off. Each of those is load-bearing; see colorHunks. */
import {
  dataBody,
  failSoft,
  langForPath,
  once,
  settle,
  shadowStage,
  synNodes,
  syntax,
  tokenLines,
} from "/colloquy.js";

// One entry per file: {path, adds, dels, lines: [{kind, text}]} where kind is
// add | del | ctx | hunk | note. Tolerates both `diff --git` and bare ---/+++
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
      expectPlus = true;
      continue;
    }
    if (file === null) throw new Error("not a unified diff (no file header)");
    if (expectPlus && line.startsWith("+++ ")) {
      expectPlus = false;
      const path = line.slice(4).replace(/^b\//, "");
      if (!file.path && path !== "/dev/null") file.path = path;
    } else if (line.startsWith("@@")) {
      file.lines.push({ kind: "hunk", text: line });
    } else if (line.startsWith("+")) {
      file.adds++;
      file.lines.push({ kind: "add", text: line });
    } else if (line.startsWith("-")) {
      file.dels++;
      file.lines.push({ kind: "del", text: line });
    } else if (
      line.startsWith("index ") ||
      line.startsWith("new file") ||
      line.startsWith("deleted file") ||
      line.startsWith("similarity ") ||
      line.startsWith("rename ") ||
      line.startsWith("Binary files ")
    ) {
      continue;
    } else if (line.startsWith("\\ ")) {
      // `\ No newline at end of file` — git remarking on the line above rather than
      // showing one of its own. Shown, because it is something the diff says, but its
      // own kind: read as context it would be a line of the file that isn't there, and
      // the colouring would hand it to the tokenizer as source.
      file.lines.push({ kind: "note", text: line });
    } else {
      file.lines.push({ kind: "ctx", text: line });
    }
  }
  return files;
}

// A file's lines coloured: index into file.lines → the line's tokens, absent where
// nothing coloured it. Three decisions, and the simpler answer to each is wrong in a way
// only a real diff shows:
//
// The hunk is the unit. A hunk's lines are contiguous source; a file's are not, and
// gluing them across an @@ boundary would lex code that never sat together. It also
// bounds the one failure a fragment cannot avoid — a hunk opening inside a docstring
// has no opener to close, so its closing `"""` opens a string that eats the rest — to
// the hunk it happened in.
//
// Each side, separately. A hunk interleaves two versions, so read straight through it
// the deleted `if x:` and the added `if x is None:` are consecutive. The old side is
// ctx+del and the new side ctx+add; each is a version of the file that really existed.
// A context line is written twice and the new side lands last, because the new side is
// the text the user is being asked to approve.
//
// Without the +/−/space column. The prefix is the diff's word about the line, not the
// file's, and a tokenizer reads it as the file's: yaml calls a leading `-` a sequence
// bullet (keyword ink) and a leading `+` a string, so leaving it on paints the deletion
// marker red and the addition marker blue — the widget's own signal, restated wrong.
async function colorHunks(file, lang) {
  const runs = []; // one per (hunk, side): the line indices it covers, in order
  let hunk = [];
  const close = () => {
    if (hunk.length)
      for (const kinds of [
        ["ctx", "del"],
        ["ctx", "add"],
      ])
        runs.push(hunk.filter((i) => kinds.includes(file.lines[i].kind)));
    hunk = [];
  };
  file.lines.forEach((line, i) => {
    // A hunk runs until the diff stops showing the file's lines. git's remark doesn't
    // stop it — the hunk carries on past a `\ No newline` — the remark just isn't one of
    // those lines, so it goes into neither side.
    if (line.kind === "hunk") close();
    else if (line.kind !== "note") hunk.push(i);
  });
  close();

  const colored = new Map();
  for (const run of runs) {
    if (!run.length) continue;
    const source = run.map((i) => file.lines[i].text.slice(1)).join("\n");
    let lines;
    try {
      lines = tokenLines(await syntax(source, lang));
    } catch (err) {
      // The partition promise broke, or the bundle lacks a language $languages names.
      // Either way these tokens can't be trusted to line up, so this run stays plain and
      // says so — the console error is what `version check --render` fails on. Per run rather
      // than per diff, the way highlightBlocks fails per block: the diff itself parsed.
      console.error(`colloquy: cq-diff could not color a ${lang} hunk`, err);
      continue;
    }
    // One array per line and no default: syntax promises the tokens rejoin the source,
    // and the source is these lines joined by newlines, so tokenLines returns exactly
    // this many. Should that ever stop being true, an absent entry leaves the line
    // uncoloured rather than substituting an empty one, which would blank its text.
    run.forEach((i, n) => colored.set(i, lines[n]));
  }
  return colored;
}

function fileNode(file, colored) {
  const details = document.createElement("details");
  details.open = true;
  const summary = document.createElement("summary");
  summary.append(
    Object.assign(document.createElement("code"), {
      textContent: file.path || "(unnamed file)",
    }),
    Object.assign(document.createElement("span"), {
      className: "cq-diff-stat",
      textContent: `+${file.adds} −${file.dels}`,
    }),
  );
  const pre = document.createElement("pre");
  file.lines.forEach(({ kind, text }, i) => {
    const line = Object.assign(document.createElement("span"), { className: kind });
    const tokens = colored.get(i);
    if (tokens) {
      // The prefix goes back exactly as it came, at full ink: where a rendering drops
      // backgrounds it is the only thing left saying the line changed. Colour adds no
      // characters and moves none, so what the page says here is what the file says.
      if (text) line.append(text.slice(0, 1));
      line.append(...synNodes(tokens), "\n");
    } else line.textContent = text + "\n";
    pre.append(line);
  });
  details.append(summary, pre);
  return details;
}

customElements.define(
  "cq-diff",
  class extends HTMLElement {
    connectedCallback() {
      if (!once(this)) return;
      // Registered with settle() so the runtime holds the first anchor pass until the
      // lines are in: the tokenizer loads lazily, and one writer has to finish before
      // another reads.
      settle(this.render());
    }

    async render() {
      // Only blank edge lines are trimmed: diff content is column-sensitive
      // (a leading space means context), so the body is authored at column 0.
      const source = dataBody(this)
        .replace(/^\n+/, "")
        .replace(/\n\s*$/, "");
      try {
        const files = parseDiff(source);
        if (!files.length) throw new Error("empty diff");
        const nodes = [];
        for (const file of files) {
          // A path with no language — a Dockerfile, a .txt, an extension the table
          // doesn't name — is a file that stays plain, the way a cq-code without `language`
          // does. Nothing is guessed from what the lines look like.
          const lang = langForPath(file.path);
          nodes.push(fileNode(file, lang ? await colorHunks(file, lang) : new Map()));
        }
        // Into a shadow root (x-shadow). The runtime's reading follows the composed
        // tree, which is why the lines in here stay as quotable as any paragraph — see
        // textNodesUnder. The authored <pre> goes, exactly as it did when this rendered
        // in place: a host's light children stop rendering the moment it has a shadow
        // root, and markup that is in the file but on nobody's screen is what a copy
        // reports as content it can't show.
        this.replaceChildren();
        shadowStage(this, nodes);
        this.classList.add("cq-rendered");
      } catch (err) {
        failSoft(this, err, source);
      }
    }
  },
);
