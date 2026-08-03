/* cq-options: a question the reader answers. The theme draws both of its forms and
 * this module makes them answerable — without it the markup still reads as a decision,
 * and nothing here is load-bearing on the look.
 *
 * Which form a group takes is a fact about its options, decided in CSS and never here:
 * an option leading with a <strong> title argues its own case and is a card, and a
 * group whose options are bare labels is a question *about* the page, drawn as rows.
 * The difference this module sees is only what a row adds — `for`, the id of the block
 * the row names, rendered as a reference the reader can follow. It points and never
 * speaks: the label stays written in the markup, so the file's reading of the page
 * holds every word the page shows.
 *
 * `choose` takes the reader's pick. Every option carries one injected mark that is both
 * the keyboard path and the state — a toggle reading "choose", which becomes "your pick"
 * once this reader picks it, or "chosen" where the document already carries it. One
 * element for both, so nothing hides, nothing moves, and a keyboard pick leaves focus
 * where it was. Which word a mark wears is asked of the option rather than of the call
 * that changed it: picked and authored-chosen reads "chosen", picked otherwise reads
 * "your pick". Outside a `choose` group the same mark renders as a span — the document's
 * state, with nothing to press, and so a passage a user can quote rather than a
 * label anchoring skips.
 *
 * The pick is a set, whatever the group allows. `multiple` lets it hold more than one
 * and clicking toggles each option in or out; without it a click makes that option the
 * only pick and clicking it again empties the set. One shape either way — the action
 * states the whole set, absolutely, so replaying this tab's own pick is a no-op and a
 * second tab converges rather than drifting. Clicks that are really text selections or
 * link follows don't choose.
 *
 * A choose group also carries a box for words (the runtime's `sayBox`). A question can
 * always be answered off its own menu — "none of these", or a pick's why — and without
 * a box that answer costs the reader a hunt for some passage to select. What they type
 * goes back as a comment anchored on the group, so it is a thread beside the question
 * rather than a channel of its own. In a thread the runtime returns no box (the
 * thread's reply box is already the words' home), and a `multiple` group grows a Done
 * press instead: every toggle reaches the agent as it lands, so the press is the one
 * statement that the set is whole, posted as an `answer` action and held as the
 * thread ask's closing condition (x-awaits.until). Answered is paint on the press,
 * never a wider word, and the set can still change after — each later toggle still
 * reaches the agent, who reads the log rather than the moment.
 *
 * The keyboard path: every mark is a press, so Tab reaches it and ⏎ toggles. From a
 * mark, ↑/↓ walk the options (a clamp at the ends, not a wrap) and 1–9 pick outright —
 * each option wears its digit as a corner chip, painted only while a mark holds
 * keyboard focus, so nothing appears on a page nobody is answering, and an armed g
 * leader keeps its own digits (leaderArmed). The rows are declared per mark through
 * keyHint, so the key line and the ? overlay promise what a press does.
 *
 * `settled` retires the decision once it has been made and acted on: the group collapses
 * to one line naming the chosen option, with every option — the chosen one included —
 * behind a disclosure. Nothing is deleted, so the ids, the anchors on them, and check's
 * id-survival rule are all untouched; what's reclaimed is the height. Open or closed is
 * view state for this reader, remembered per browser tab in sessionStorage like a cq-tabs
 * tab: opening a settled group is reading, not editing, so it sends no action and no
 * version carries it. Collapsed options wear hidden="until-found", so find-in-page and
 * the runtime's reveal() (a click on a comment's quote) both open the group rather than
 * jumping to an option nobody can see, and while the version diff is on the row wears a
 * Δ count so a change can't hide behind the collapse. A settled group still takes a pick
 * once opened — settling is a sweep, not a lock, and the summary line follows whatever is
 * chosen, including back to a bare "Settled" when the reader clears it.
 *
 * Inside a <cq-specimen> the group is quoted — exhibited, not offered — so it takes the
 * same path as a group that never declared `choose`: the mark is a span, the click
 * handler is never wired, there is no box for words, and an example decision can't be
 * answered. `settled` still collapses there, because quoting gates the action channel and
 * not presentation.
 *
 * Authored content is never replaced, so there is no failSoft. */
import {
  HIDDEN,
  agentName,
  inChrome,
  keyHelp,
  keyHint,
  leaderArmed,
  offer,
  once,
  quoted,
  relabel,
  sayBox,
  sendAction,
  toast,
  wrote,
} from "/colloquy.js";

// What an option is called, in either form: its title where it leads with one, and its
// own words where the label is all it has. `wrote` rather than `says`, because a picked
// option's mark is the page speaking and belongs to what the reader can point at — not
// to the option's name, which is what every caller here wants. A settled title's answer
// to an option with neither is to say "Settled" rather than name an id nobody wrote.
const label = (option) => wrote(option.querySelector(":scope > strong") ?? option);

const OPEN = "choose"; // the option is pickable
const PICKED = "your pick"; // this reader picked it, this session
const AUTHORED = "chosen"; // the document arrived carrying the pick

const SETTLED_KEY = "cq-settled:";

// The module loads only where the page holds a group, which is the overlay's rule
// for free: these rows appear exactly when there is a group to answer.
keyHelp("In a question's options", [
  ["⇥", "reach an option's mark"],
  ["↑ / ↓", "walk the options"],
  ["1–9", "pick the nth option"],
  ["⏎ / space", "toggle the focused option"],
]);

customElements.define(
  "cq-options",
  class extends HTMLElement {
    connectedCallback() {
      if (!once(this)) return;
      // An authored `chosen` (the honoring version carrying an earlier pick) wears the
      // same mark a live pick wears, so honoring doesn't change the look — but worded as
      // the document's state, not attributed to this reader.
      this.#authored = new Set(
        [...this.#options()].filter((o) => o.hasAttribute("chosen")).map((o) => o.id),
      );
      // Quoted material is exhibited, not offered, so a specimen renders exactly like a
      // group that was never choosable: it shows what a decision looks like without
      // taking one.
      const choosable = this.hasAttribute("choose") && !quoted(this);
      for (const option of this.#options()) this.#reference(option);
      // Without `choose` there is nothing to press: the mark still reports the
      // document's state, as a span.
      for (const option of this.#options())
        if (choosable || this.#authored.has(option.id)) this.#mark(option, choosable);
      if (choosable) {
        this.#say = sayBox(this, "Say something");
        if (this.#say) this.append(this.#say);
        if (this.hasAttribute("multiple") && inChrome(this)) this.#doneRow();
        this.#keys();
      }
      if (this.hasAttribute("settled")) this.#settle();
      if (!choosable) return;
      this.addEventListener("click", (e) => {
        // A click that ends a drag-select is that selection's, not a pick. The runtime
        // guards its own controls (see `offer`); this is the option, which is no control
        // at all — a drag across an option's prose ends here, not on the mark. Same
        // question, so the same test: did this click's mouseup leave the selection where
        // it is (its focus end)? Asking whether the selection contains the option instead
        // answers yes for any selection over the group, and the option stops taking picks
        // until the user clears it.
        const sel = getSelection();
        const card = e.target.closest?.("cq-option");
        if (e.detail !== 0 && sel && !sel.isCollapsed && card?.contains(sel.focusNode))
          return;
        if (e.target.closest("a")) return; // links keep their job
        const option = e.target.closest("cq-option");
        if (!option || option.parentElement !== this) return;
        const was = this.#picked();
        // Toggling is one gesture both ways, so a reader who picked by mistake needn't
        // pick something else to get out of it. Without `multiple` the set the toggle
        // starts from is empty, which is what makes a pick replace rather than join.
        const next = new Set(this.hasAttribute("multiple") ? was : []);
        if (was.has(option)) next.delete(option);
        else next.add(option);
        this.#pick(next);
        const name = label(option) || option.id;
        const said = !next.size
          ? "Cleared your pick"
          : next.has(option)
            ? `Chose “${name}”`
            : `Dropped “${name}”`;
        sendAction(this, "choose", { options: [...next].map((o) => o.id) }).then(
          (ok) => {
            if (ok) toast(`${said} — sent to ${agentName()}`);
            // Unsent means unrecorded: rewind rather than show a pick Claude will never
            // see. (post already toasted the failure.)
            else this.#pick(was);
          },
        );
      });
    }

    #authored = new Set(); // ids the document arrived carrying, so a mark words itself honestly
    #say = null; // the box for words, hidden with the options when the group is settled
    #done = null; // the thread multi-question's submit; null everywhere else

    #options() {
      return this.querySelectorAll(":scope > cq-option");
    }

    #picked() {
      return new Set([...this.#options()].filter((o) => o.hasAttribute("chosen")));
    }

    #marks() {
      return [...this.querySelectorAll(':scope > cq-option > .cq-pick[role="button"]')];
    }

    // The one statement a live channel can't derive: the set is whole. One press,
    // one `answer` action, and the ask this group stands as is discharged
    // (x-awaits.until). One-way — a later toggle still reaches the agent, so there
    // is nothing to take back — and its state is paint on the press, so the
    // pressed control's own line holds still.
    #doneRow() {
      this.#done = offer("button", "cq-btn cq-done", "Done");
      this.#done.setAttribute("aria-label", "Done: my picks here are complete");
      this.#done.setAttribute("aria-pressed", "false");
      this.#done.onclick = () =>
        sendAction(this, "answer", {}).then((ok) => {
          if (!ok) return;
          this.#answered(true);
          toast(`Marked answered — sent to ${agentName()}`);
        });
      this.append(this.#done);
    }

    // Absolute: answered is the whole statement, so replaying this tab's own press
    // is the same call again.
    #answered(on) {
      this.toggleAttribute("answered", on);
      this.#done?.setAttribute("aria-pressed", String(on));
      document.dispatchEvent(new CustomEvent("cq-answered"));
    }

    // The keyboard path past Tab-and-⏎: from a mark, ↑/↓ walk the options and a
    // digit picks outright. Focus-scoped — the handler acts only on a press that
    // lands on this group's own mark, so a digit typed in the box for words stays
    // text and a nested group's marks stay its own — and an armed g leader keeps
    // its digits: the chord's promise holds wherever focus sits, and this handler
    // runs ahead of the dispatcher that owns the window. Each option wears its
    // digit as a corner chip only while a mark holds keyboard focus (the theme's
    // :focus-visible rule), so the address appears exactly when a key could use it.
    #keys() {
      const marks = this.#marks();
      for (const [i, mark] of marks.entries()) {
        if (i < 9) {
          // Chrome like the § reference: a thing to work rather than a word the
          // page says, so the gate, the anchor pass, and paper all read it as the
          // control apparatus it is. The key line speaks the keys; this is the
          // eye's copy, hence aria-hidden.
          // Prepended, so the mark stays the row's last child: the digit is a
          // corner badge wherever it sits in the DOM, and the apparatus keeps
          // ending at the mark.
          const num = offer("span", "cq-pick-num", String(i + 1));
          num.setAttribute("aria-hidden", "true");
          mark.parentElement.prepend(num);
        }
        keyHint(mark, [
          [marks.length > 1 ? `1–${Math.min(9, marks.length)}` : "1", "pick"],
          ["↑ ↓", "walk the options"],
          ["⏎", "toggle"],
        ]);
      }
      this.addEventListener("keydown", (e) => {
        const mark = e.target.closest?.('.cq-pick[role="button"]');
        if (!mark || mark.closest("cq-options") !== this) return;
        const at = marks.indexOf(mark);
        if (e.key === "ArrowDown" || e.key === "ArrowUp") {
          e.preventDefault(); // a clamp at the ends, and the page must not scroll
          marks[at + (e.key === "ArrowDown" ? 1 : -1)]?.focus();
        } else if (/^[1-9]$/.test(e.key) && !leaderArmed()) {
          const target = marks[+e.key - 1];
          if (!target) return;
          e.preventDefault();
          target.focus();
          target.click();
        }
      });
    }

    // The block this option is about. A pointer, not a voice: its text is the id it
    // names, which is the same way the comment panel writes an element anchor, and
    // chrome throughout — a thing to work and nothing else, so paper drops it.
    #reference(option) {
      const target = option.getAttribute("for");
      if (!target) return;
      const ref = offer("a", "cq-ref", `§ ${target}`);
      ref.href = `#${target}`;
      option.append(ref);
    }

    // The keyboard affordance and the state marker, one element — a button whose click
    // bubbles into the group's pick handler where there's a pick to make, and the same
    // mark as a span where there isn't.
    #mark(option, pressable) {
      // A press wears the chrome face and .cq-ui reaches exactly as far as the control
      // does; the other shape holds no control at all, so it needs neither. What each one
      // *says* is a separate question both shapes answer the same way (#label), and the
      // answer is what decides whether a comment can land on it. data-cq-gen either way,
      // since the diff parses the base version unupgraded and would read any mark as text
      // that version lacked.
      const mark = pressable
        ? offer("button", "cq-pick")
        : document.createElement("span");
      if (!pressable) {
        mark.className = "cq-pick";
        mark.dataset.cqGen = "1";
      }
      option.append(mark);
      this.#label(option);
    }

    // An absolute placement: `picked` is the whole answer, so every option is stated,
    // not just the ones that changed.
    #pick(picked) {
      for (const option of this.#options()) {
        option.toggleAttribute("chosen", picked.has(option));
        this.#label(option);
      }
      this.#retitle();
      // A pick is an answer to what this group was asking, and a mark that now reads
      // "your pick" is a word the page didn't have before: the banner's count and the
      // page's marks both follow from the same one signal, here rather than at the
      // sender, so a pick this tab rewound and one another tab made both reach them.
      document.dispatchEvent(new CustomEvent("cq-answered"));
    }

    // Which kind of word the label is travels with it, on both shapes of mark and on
    // every write: "choose" is a thing to do, so it leaves the printed page and no comment
    // lands on it, while a picked option's mark is the only place the page says where the
    // pick sits — paper keeps that one and a user can point at it. Asked of the label
    // rather than of the element, because one mark is both over its life and neither shape
    // is a <button> to tell them apart by.
    //
    // Then what only a control needs: an accessible name saying which option it picks,
    // containing the visible word, and the pressed state.
    #label(option) {
      const mark = option.querySelector(":scope > .cq-pick");
      if (!mark) return;
      const chosen = option.hasAttribute("chosen");
      const word = !chosen ? OPEN : this.#authored.has(option.id) ? AUTHORED : PICKED;
      relabel(mark, word, { says: chosen });
      if (!mark.matches('[role="button"]')) return;
      mark.setAttribute("aria-label", `${word}: ${label(option) || option.id}`);
      mark.setAttribute("aria-pressed", String(chosen));
    }

    // ---------- settled ----------

    #row = null; // the one-line summary a settled group collapses to
    #title = null; // the part of it naming the chosen option

    #settle() {
      // A disclosure is a thing to work, and what it names — the chosen option — the
      // options themselves say once paper opens the group. On screen they do not: the row
      // is the decision's only visible statement while the group stays collapsed, so the
      // part of it naming the option is the page speaking and says so, and the anchor pass
      // reads it over the row's chrome. The count beside it is the runtime talking about
      // the document, which is why the two are separate spans.
      this.#row = offer("button", "cq-settled");
      this.#title = document.createElement("span");
      const options = [...this.#options()];
      const count = document.createElement("span");
      count.className = "cq-settled-count";
      count.textContent = `${options.length} option${options.length === 1 ? "" : "s"}`;
      this.#row.append(this.#title, count);
      this.#row.setAttribute("aria-controls", options.map((o) => o.id).join(" "));
      this.#row.onclick = () => this.#open(!this.hasAttribute("open"), true);
      this.prepend(this.#row);
      for (const option of options) {
        // The browser found something inside (find-in-page, an anchor jump), or the
        // runtime is about to scroll a comment anchor into view: open up.
        option.addEventListener("beforematch", () => this.#open(true, true));
        option.addEventListener("cq-reveal", () => this.#open(true, true));
      }
      this.classList.add("cq-rendered"); // the upgraded marker every widget uses
      this.#retitle();
      let saved = null;
      try {
        saved = sessionStorage.getItem(SETTLED_KEY + this.id);
      } catch {}
      this.#open(saved === "1", false);
      // Δ badges follow the version diff; the runtime announces each toggle.
      document.addEventListener("cq-diff", () => this.#delta());
    }

    #open(open, remember) {
      this.toggleAttribute("open", open);
      // The box for words goes behind the collapse with the options: it belongs to the
      // question, and a settled group asks nothing until the reader opens it again.
      for (const el of [...this.#options(), ...(this.#say ? [this.#say] : [])])
        if (open) el.removeAttribute("hidden");
        else el.setAttribute("hidden", HIDDEN);
      this.#row.setAttribute("aria-expanded", open ? "true" : "false");
      if (remember)
        try {
          sessionStorage.setItem(SETTLED_KEY + this.id, open ? "1" : "0");
        } catch {}
    }

    // The summary carries the decision, so it names whichever options hold it —
    // including after a pick made in an opened group, which would otherwise leave the
    // line contradicting the options it hides.
    #retitle() {
      if (!this.#title) return;
      const names = [...this.#picked()].map(label).filter(Boolean);
      relabel(this.#title, names.length ? `Settled: ${names.join(", ")}` : "Settled", {
        says: true,
      });
    }

    // One Δn chip on the row when the diff marks passages inside, so the toast's count is
    // accounted for even where the marks sit behind the collapse.
    #delta() {
      this.#row.querySelector(".cq-settled-diff")?.remove();
      const n = this.querySelectorAll(".cq-ins-block").length;
      if (!n) return;
      const chip = document.createElement("span");
      chip.className = "cq-settled-diff";
      chip.textContent = `Δ${n}`;
      this.#row.append(chip);
    }

    // {options}: exactly these are this group's picks — an empty list for no pick at
    // all, which is how clearing travels rather than a second verb. `answer` is the
    // Done press's statement that the set is whole; empty detail, because answered
    // is the whole of it.
    applyAction(action, detail) {
      if (action === "answer") return this.#answered(true);
      if (action !== "choose") return;
      this.#pick(
        new Set(
          detail.options
            .map((id) => document.getElementById(id))
            .filter((o) => o?.matches("cq-option") && o.parentElement === this),
        ),
      );
    }
  },
);
