/* cq-shot: a before/after pair of screenshots of one view, shown one at a time in one
 * frame.
 *
 * The comparison is a flip, not a wipe. A wipe puts the two states either side of a
 * divider, so it reads a change only where the change happens to cross the divider;
 * anything wholly on one side is a thing the eye has to carry across the seam and hold
 * in memory. Swapping one registered frame for the other leaves the change as the only
 * thing on screen that moves — the blink comparator's trick, and how it found a planet.
 *
 * Everything the flip needs is native: the state is a radio group, the swap a
 * `:has(:checked)` rule in the theme. No handler runs after the upgrade, so a serialized
 * copy of this page — DOM kept, script tags dropped — still flips, and a printed one
 * stacks both frames instead. A dragged slider would have survived neither.
 *
 * Two kinds of word, and they are marked differently on purpose. Each frame's caption
 * names which state it holds, which is the widget's own word and the only thing telling
 * the two frames apart once paper has both of them on the page: data-cq-gen alone, so
 * the version diff looks away and the reviewer can still select it. The radio beside it
 * is a thing to press, so it goes through `offer` with the rest of the chrome. What the
 * page has to say about the change itself is neither — it is prose, written around the
 * element, where a comment can reach it like any other sentence. */
import { once, offer, failSoft, settle } from "/colloquy.js";

customElements.define(
  "cq-shot",
  class extends HTMLElement {
    connectedCallback() {
      if (!once(this)) return;
      const alt = this.getAttribute("alt");
      const shots = [];
      const pick = offer("div", "cq-shotpick");
      pick.role = "radiogroup";
      pick.ariaLabel = `${alt}: which state to show`;

      for (const state of ["before", "after"]) {
        const frame = document.createElement("div");
        frame.className = "cq-shotframe";
        frame.dataset.cqGen = "1";
        frame.dataset.cqState = state;

        const img = document.createElement("img");
        img.src = this.getAttribute(state);
        img.alt = `${state}: ${alt}`;
        shots.push(img);
        const caption = document.createElement("span");
        caption.className = "cq-shotcap";
        caption.dataset.cqGen = "1";
        caption.textContent = state;
        frame.append(img, caption);
        this.append(frame);

        const label = offer("label", "");
        const radio = document.createElement("input");
        radio.type = "radio";
        // Scoped to this element, so two pairs on a page flip independently.
        radio.name = `cq-shot-${this.id}`;
        radio.value = state;
        // The attribute, not the property: a serialized copy of this page keeps
        // attributes and drops properties, and a copy that opened with neither
        // radio checked would show both frames stacked in the one grid cell.
        if (state === "before") radio.setAttribute("checked", "");
        label.append(radio, ` ${state}`);
        pick.append(label);
      }
      this.append(pick);
      settle(this.register(shots));
    }

    // Both frames render at the frame's width, so a pair shot at two different
    // viewports is scaled by two different factors and every line in it lands
    // somewhere new. The flip then says the whole page changed, which is the one
    // failure this widget cannot afford: it is silent, it is convincing, and the
    // reader has no way to tell it from the truth. Heights may differ freely —
    // content reflowing taller is a real thing to see, and it stays registered.
    async register(shots) {
      await Promise.all(shots.map((img) => img.decode().catch(() => {})));
      const [before, after] = shots.map((img) => img.naturalWidth);
      if (before && after && before !== after)
        failSoft(
          this,
          new Error(
            `before is ${before}px wide and after is ${after}px — a pair has to be shot ` +
              `at one viewport, or the flip moves everything`,
          ),
        );
    }
  },
);
