/* cq-tree: upgraded because it parses. The body is indent notation — one node
 * per line, children indented further than their parent, a trailing slash (or
 * having children) marking a directory, and trailing +N/-N tokens rendering as
 * change badges. The PR-walkthrough and architecture-map shape. */
import { once, failSoft } from "/colloquy.js";

const BADGE = /^[+-]\d+$/;

// Lines → {name, dir, badges, children}, nesting by indent depth. Any deeper
// indent opens a child level, so 2-space and 4-space bodies both parse.
function parseTree(text) {
  const root = { children: [] };
  const stack = [{ indent: -1, node: root }];
  for (const line of text.split("\n")) {
    if (!line.trim()) continue;
    const indent = line.length - line.trimStart().length;
    const tokens = line.trim().split(/\s+/);
    const badges = [];
    while (tokens.length > 1 && BADGE.test(tokens[tokens.length - 1]))
      badges.unshift(tokens.pop());
    const name = tokens.join(" ");
    const node = {
      name: name.replace(/\/$/, ""),
      dir: name.endsWith("/"),
      badges,
      children: [],
    };
    while (stack[stack.length - 1].indent >= indent) stack.pop();
    stack[stack.length - 1].node.children.push(node);
    stack.push({ indent, node });
  }
  return root.children;
}

function listNode(nodes) {
  const ul = document.createElement("ul");
  for (const node of nodes) {
    const li = document.createElement("li");
    const name = document.createElement("span");
    if (node.dir || node.children.length) name.className = "cq-tree-dir";
    name.textContent = node.name + (node.dir || node.children.length ? "/" : "");
    li.append(name);
    for (const badge of node.badges)
      li.append(
        Object.assign(document.createElement("span"), {
          className: `cq-tree-badge ${badge.startsWith("+") ? "add" : "del"}`,
          textContent: badge,
        }),
      );
    if (node.children.length) li.append(listNode(node.children));
    ul.append(li);
  }
  return ul;
}

customElements.define(
  "cq-tree",
  class extends HTMLElement {
    connectedCallback() {
      if (!once(this)) return;
      const source = this.textContent.replace(/^\n+/, "").replace(/\s+$/, "");
      try {
        const nodes = parseTree(source);
        if (!nodes.length) throw new Error("empty tree");
        this.replaceChildren(listNode(nodes));
        this.classList.add("cq-rendered");
      } catch (err) {
        failSoft(this, err, source);
      }
    }
  },
);
