/* cq-diagram: renders a mermaid-source body, upgraded because it parses. The body is
 * data, not prose — the theme shows it as source until the SVG replaces it, so a page
 * degrades readably if rendering fails (the source stays visible in the error box).
 * The vendored mermaid bundle loads lazily, once, and only on pages that use it. */
import { dataBody, once, failSoft, settle } from "/colloquy.js";

/* A diagram paints its own boxes, which makes it the one widget that can hold a
 * palette of its own — and it did: mermaid's stock "neutral" is a cool grey, so
 * every diagram sat on the page as a slab of a different theme. The tokens are the
 * page's answer to what a surface, a rule and a label look like, so the diagram
 * takes them too, read off the document rather than restated here. `base` is the
 * theme that accepts them; the named themes derive their own and ignore most of
 * what you pass. `darkMode` is the one thing the tokens can't say, because it tells
 * mermaid which way to derive the variables it wasn't given.
 *
 * Read once, at load. A page whose OS flips scheme mid-read keeps the palette it
 * started in until reload — the same as the vendored highlight table, and unlike
 * the rest of the theme, which is tokens and follows live. Re-rendering every
 * diagram on a media-query change would be the alternative, and it buys a case
 * (the OS theme changing while a reviewer reads) that costs a reload to fix. */
const token = (name) => getComputedStyle(document.body).getPropertyValue(name).trim();

let mermaidReady;
const loadMermaid = () =>
  (mermaidReady ??= new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "/vendor/mermaid.min.js";
    s.onload = () => {
      globalThis.mermaid.initialize({
        startOnLoad: false,
        theme: "base",
        // A diagram's node labels are apparatus, so they take the apparatus face.
        fontFamily: token("--sans"),
        themeVariables: {
          darkMode: matchMedia("(prefers-color-scheme: dark)").matches,
          background: token("--paper"),
          mainBkg: token("--card"),
          primaryColor: token("--card"),
          primaryTextColor: token("--ink"),
          primaryBorderColor: token("--border-2"),
          secondaryColor: token("--field"),
          tertiaryColor: token("--chip"),
          lineColor: token("--muted"),
          textColor: token("--ink"),
          nodeBorder: token("--border-2"),
          clusterBkg: token("--field"),
          clusterBorder: token("--rule"),
          titleColor: token("--ink"),
          edgeLabelBackground: token("--paper"),
        },
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
      const source = dataBody(this).trim();
      const renderId = `cq-mermaid-${++seq}`;
      try {
        const mermaid = await loadMermaid();
        const { svg } = await mermaid.render(renderId, source);
        this.innerHTML = svg;
        // Mermaid sizes to fit: the svg is width 100%, capped at its natural size, so
        // a diagram wider than the column scales down whole, glyphs first — a
        // five-node flowchart arrived at 63% with its labels below legibility.
        // Legibility outranks fit: state the natural size and let the element's own
        // box scroll sideways (the theme's answer for a wide table or pre). The
        // viewBox is how every diagram type declares that size, so none is named.
        const drawn = this.querySelector("svg");
        const natural = drawn.viewBox.baseVal.width;
        if (natural) {
          drawn.setAttribute("width", natural);
          drawn.style.maxWidth = "";
        }
        this.classList.add("cq-rendered");
      } catch (err) {
        // mermaid leaves its temp node (id "d" + renderId) in the body on failure.
        document.getElementById(`d${renderId}`)?.remove();
        failSoft(this, err, source);
      }
    }
  },
);
