/* cq-diagram: renders a mermaid-source body, upgraded because it parses. The body is
 * data, not prose — the theme shows it as source until the SVG replaces it, so a page
 * degrades readably if rendering fails (the source stays visible in the error box).
 * The vendored mermaid bundle loads lazily, once, and only on pages that use it. */
import { once, failSoft, settle } from "/colloquy.js";

let mermaidReady;
const loadMermaid = () =>
  (mermaidReady ??= new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "/vendor/mermaid.min.js";
    s.onload = () => {
      globalThis.mermaid.initialize({
        startOnLoad: false,
        theme: matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "neutral",
        fontFamily: "system-ui, sans-serif",
      });
      resolve(globalThis.mermaid);
    };
    s.onerror = () => reject(new Error("couldn't load /vendor/mermaid.min.js"));
    document.head.append(s);
  }));

let seq = 0;
customElements.define(
  "cq-diagram",
  class extends HTMLElement {
    connectedCallback() {
      if (!once(this)) return;
      // Registered with settle() so the runtime holds the view restore and the
      // first anchor pass until the SVG is in and the page's geometry is final.
      settle(this.render());
    }

    async render() {
      const source = this.textContent.trim();
      const renderId = `cq-mermaid-${++seq}`;
      try {
        const mermaid = await loadMermaid();
        const { svg } = await mermaid.render(renderId, source);
        this.innerHTML = svg;
        this.classList.add("cq-rendered");
      } catch (err) {
        // mermaid leaves its temp node (id "d" + renderId) in the body on failure.
        document.getElementById(`d${renderId}`)?.remove();
        failSoft(this, err, source);
      }
    }
  },
);
