#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow>=11", "playwright>=1.52"]
# ///
"""Record docs/demo.gif by driving the shipped runtime through one review round."""

from __future__ import annotations

import argparse
import http.cookiejar
import io
import json
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

from PIL import Image
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
COLLOQUY = ROOT / "plugins" / "colloquy" / "bin" / "colloquy"
PAGE_DIR = ROOT / ".tmp" / "demo-recording"
DEFAULT_OUTPUT = ROOT / "docs" / "demo.gif"
GIF_SIZE = (1120, 700)


def demo_page(version: int) -> str:
    progressed = version == 2
    progress = "3 of 4" if progressed else "2 of 4"
    delta = ' delta="+1" direction="up-good"' if progressed else ""
    shadow_status = "done" if progressed else "active"
    rollback_status = "active" if progressed else "planned"
    shadow_copy = (
        "Backfill stayed online behind a fixed rate limit; read parity held."
        if progressed
        else "Backfill is running behind a fixed rate limit; read parity is being sampled."
    )
    rollback_copy = (
        "Traffic is back on the old service; order counts are being compared."
        if progressed
        else "Return traffic to the old service and compare order counts."
    )
    phase_two = (
        "Backfill history online behind a fixed rate limit, then flip reads to the new store."
        if progressed
        else "Backfill history, then flip reads to the new store."
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Migration plan</title>
<meta name="cq-review" content="sign-off">
<link rel="stylesheet" href="/theme.css">
<script type="module" src="/colloquy.js"></script>
</head>
<body>
<main>
<header id="top">
<p class="eyebrow">demo · migration rehearsal</p>
<h1>Migrating billing to the new service</h1>
<p class="lede" id="demo-lede">The rehearsal is running now. This page follows each
new version as the checks finish.</p>
</header>

<cq-metrics id="demo-metrics">
  <cq-metric id="demo-progress" value="{progress}"{delta}>checks complete</cq-metric>
  <cq-metric id="demo-errors" value="0.08%">error rate</cq-metric>
  <cq-metric id="demo-p95" value="181 ms">p95 latency</cq-metric>
</cq-metrics>

<section id="phases">
<h2>Phases</h2>
<ol class="steps">
  <li id="p1">Dual-write to old and new stores behind a flag.</li>
  <li id="p2">{phase_two}</li>
  <li id="p3">Use an online traffic swap, then retire the old store.</li>
</ol>
</section>

<section id="rehearsal">
<h2>Rehearsal progress</h2>
<cq-milestones id="demo-milestones">
  <cq-milestone id="demo-ms-baseline" status="done" when="14:02">
    <strong>Capture the baseline</strong> Counts and guardrails recorded.
  </cq-milestone>
  <cq-milestone id="demo-ms-shadow" status="{shadow_status}" when="14:08">
    <strong>Shadow and backfill</strong> {shadow_copy}
  </cq-milestone>
  <cq-milestone id="demo-ms-rollback" status="{rollback_status}" when="next">
    <strong>Prove rollback</strong> {rollback_copy}
  </cq-milestone>
  <cq-milestone id="demo-ms-report" status="planned" when="last">
    <strong>Publish the rehearsal report</strong>
  </cq-milestone>
</cq-milestones>
</section>

<section id="work">
<h2>Cutover punch list</h2>
<p id="work-note">Drag a card to change the plan; the move reaches the agent directly.</p>
<cq-board id="punch-list">
  <cq-column id="col-before" label="Before">
    <cq-card id="card-dryrun"><strong>Dry-run the backfill</strong></cq-card>
    <cq-card id="card-oncall"><strong>Staff the on-call rota</strong></cq-card>
  </cq-column>
  <cq-column id="col-during" label="During">
    <cq-card id="card-flip"><strong>Flip reads</strong></cq-card>
  </cq-column>
  <cq-column id="col-after" label="After">
    <cq-card id="card-retire"><strong>Retire the old store</strong></cq-card>
  </cq-column>
</cq-board>
</section>
</main>
</body>
</html>
"""


def run_colloquy(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(COLLOQUY), *args],
        check=True,
        text=True,
        capture_output=True,
    )


def stop_server() -> None:
    """Best-effort cleanup for a prior or partially started recording."""
    subprocess.run(
        [str(COLLOQUY), "server", "stop", str(PAGE_DIR)],
        check=False,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def wait_for_server() -> str:
    """The page's URL, once it answers on it. Probed the way the browser about to
    open it will: the key rides in the query, and a jar carries it through the
    redirect to the latest version, which drops one."""
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            info = json.loads((PAGE_DIR / "server.json").read_text())
            opener = urllib.request.build_opener(
                urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
            )
            opener.open(info["url"], timeout=1).close()
            return info["url"]
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            time.sleep(0.05)
    raise RuntimeError("demo server did not start")


def wait_for_comment() -> str:
    deadline = time.monotonic() + 10
    log = PAGE_DIR / "comments.jsonl"
    while time.monotonic() < deadline:
        events = [
            json.loads(line)
            for line in log.read_text().splitlines()
            if line.strip()
        ]
        comments = [event for event in events if event["kind"] == "comment"]
        if comments:
            return comments[0]["id"]
        time.sleep(0.05)
    raise RuntimeError("the demo comment never reached the event log")


def select_text(page: Page, selector: str, text: str) -> None:
    selected = page.evaluate(
        """([selector, text]) => {
            const walker = document.createTreeWalker(
                document.querySelector(selector), NodeFilter.SHOW_TEXT
            );
            let node;
            while ((node = walker.nextNode())) {
                const at = node.data.indexOf(text);
                if (at < 0) continue;
                const range = document.createRange();
                range.setStart(node, at);
                range.setEnd(node, at + text.length);
                const selection = getSelection();
                selection.removeAllRanges();
                selection.addRange(range);
                return selection.toString();
            }
            return null;
        }""",
        [selector, text],
    )
    if selected != text:
        raise RuntimeError(f"could not select {text!r} in {selector}")
    page.dispatch_event("body", "mouseup")


def start_waiter() -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [str(COLLOQUY), "review", "wait", str(PAGE_DIR)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def record(
    page: Page, waiters: list[subprocess.Popen[bytes]]
) -> tuple[list[Image.Image], list[int]]:
    frames: list[Image.Image] = []
    durations: list[int] = []

    def shot(duration: int) -> None:
        png = page.screenshot(animations="disabled", caret="hide")
        image = Image.open(io.BytesIO(png)).convert("RGB")
        if image.size != GIF_SIZE:
            image = image.resize(GIF_SIZE, Image.Resampling.LANCZOS)
        frames.append(image)
        durations.append(duration)

    page.wait_for_function("() => document.body.dataset.cqUpgraded === '1'")
    page.wait_for_function(
        "() => document.querySelector('.cq-status-text').textContent.includes('is listening')"
    )
    shot(1600)

    select_text(page, "#p2", "Backfill history")
    page.locator(".cq-fab").click()
    page.locator(".cq-composer textarea").fill("Can the backfill stay online?")
    page.wait_for_function(
        """() => document.querySelector('.cq-composer').style.display === 'block'
            && (CSS.highlights.get('cq-pending')?.size ?? 0) > 0
            && document.getElementById('cq-composer-quote').classList.contains('cq-unseen')"""
    )
    shot(2300)

    page.locator(".cq-composer").get_by_role("button", name="Comment").click()
    page.wait_for_selector(".cq-thread")
    shot(1500)

    comment_id = wait_for_comment()
    waiters[0].wait(timeout=10)
    run_colloquy(
        "review",
        "state",
        str(PAGE_DIR),
        "working",
        "answering the backfill question",
    )
    page.wait_for_function(
        "() => document.querySelector('.cq-status-text').textContent.includes('answering')"
    )
    shot(900)

    run_colloquy(
        "review",
        "reply",
        str(PAGE_DIR),
        "--to",
        comment_id,
        "--text",
        "Yes. The fixed rate limit keeps the backfill online.",
    )
    (PAGE_DIR / "versions" / "v2.html").write_text(demo_page(2), encoding="utf-8")
    run_colloquy(
        "version",
        "publish",
        str(PAGE_DIR),
        "--version",
        "2",
        "--text",
        "Backfill stays online; rehearsal progress is now 3 of 4",
    )
    run_colloquy("review", "state", str(PAGE_DIR), "waiting")
    waiters.append(start_waiter())
    page.wait_for_url("**/v2.html", timeout=15_000)
    page.wait_for_function(
        "() => document.body.dataset.cqUpgraded === '1'"
        " && document.querySelectorAll('.cq-thread .cq-msg.claude').length > 0"
    )
    shot(2300)

    page.get_by_role("button", name="Close comments").click()
    page.locator("#top").scroll_into_view_if_needed()
    shot(2100)

    page.locator("#work").scroll_into_view_if_needed()
    shot(1000)
    grip = page.locator("#card-oncall .cq-grip").bounding_box()
    destination = page.locator("#col-during").bounding_box()
    if not grip or not destination:
        raise RuntimeError("the demo board did not render")
    page.mouse.move(grip["x"] + grip["width"] / 2, grip["y"] + grip["height"] / 2)
    page.mouse.down()
    page.mouse.move(
        destination["x"] + destination["width"] / 2,
        destination["y"] + destination["height"] / 2,
        steps=15,
    )
    page.mouse.up()
    page.wait_for_selector("#col-during #card-oncall")
    page.wait_for_function(
        "() => document.querySelector('.cq-toast').classList.contains('show')"
    )
    shot(2400)
    return frames, durations


def write_gif(
    frames: list[Image.Image], durations: list[int], output: Path
) -> None:
    palette_frames = [
        frame.quantize(colors=192, method=Image.Quantize.MEDIANCUT)
        for frame in frames
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    palette_frames[0].save(
        output,
        save_all=True,
        append_images=palette_frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
        disposal=1,
    )
    with Image.open(output) as recorded:
        if recorded.n_frames != len(frames):
            raise RuntimeError(
                f"recorded {recorded.n_frames} frames; expected {len(frames)}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="GIF path (default: docs/demo.gif)",
    )
    args = parser.parse_args()
    output = args.output.resolve()

    PAGE_DIR.parent.mkdir(parents=True, exist_ok=True)
    if PAGE_DIR.exists():
        stop_server()
        shutil.rmtree(PAGE_DIR)
    run_colloquy("page", "init", str(PAGE_DIR))
    (PAGE_DIR / "versions" / "v1.html").write_text(demo_page(1), encoding="utf-8")
    run_colloquy(
        "version",
        "publish",
        str(PAGE_DIR),
        "--version",
        "1",
        "--text",
        "Migration rehearsal started; 2 of 4 checks complete",
    )
    run_colloquy("review", "state", str(PAGE_DIR), "waiting")
    server = subprocess.Popen(
        [str(COLLOQUY), "server", "run", str(PAGE_DIR)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    waiters: list[subprocess.Popen[bytes]] = []
    try:
        url = wait_for_server()
        waiters.append(start_waiter())
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome")
            context = browser.new_context(
                viewport={"width": GIF_SIZE[0], "height": GIF_SIZE[1]},
                color_scheme="light",
                reduced_motion="reduce",
            )
            page = context.new_page()
            page.goto(url)
            frames, durations = record(page, waiters)
            browser.close()
        write_gif(frames, durations, output)
    finally:
        for waiter in waiters:
            if waiter.poll() is None:
                waiter.terminate()
                waiter.wait(timeout=5)
        stop_server()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.terminate()
            server.wait(timeout=5)
        shutil.rmtree(PAGE_DIR)
    try:
        shown = output.relative_to(ROOT)
    except ValueError:
        shown = output
    print(f"Recorded {shown}")


if __name__ == "__main__":
    main()
