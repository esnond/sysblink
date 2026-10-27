#!/usr/bin/env python3
"""sysblink preview: watch a patch drive a fake led in the terminal.

the patch is built against a fake brightness file and the daemon runs for
real, the screen shows the level it writes. this is a sanity tool, the
headless checks in tests/ are the evidence, this window is for looking.
"""

import argparse
import curses
import subprocess
import sys
import time

import sysblink

POLL_SEC = 0.05
BAR_WIDTH = 40
RUN_TICKS = 3


def read_level(path):
    try:
        return int(path.read_text().strip() or 0)
    except (OSError, ValueError):
        return 0


def bar(level):
    filled = round(BAR_WIDTH * level / 100)
    return "#" * filled + " " * (BAR_WIDTH - filled)


def draw(scr, patch, hz, level):
    scr.erase()
    _, width = scr.getmaxyx()
    try:
        scr.addstr(0, 0, f" {patch} {hz} hz  {level:3d}  [{bar(level)}]"[: width - 1])
        scr.addstr(2, 0, " q: quit"[: width - 1])
        scr.refresh()
    except curses.error:
        pass  # a terminal too small to draw is not worth crashing over


def run_preview(scr, binary, led_file, patch, hz):
    proc = subprocess.Popen([str(binary)])
    try:
        while True:
            draw(scr, patch, hz, read_level(led_file))
            scr.timeout(int(POLL_SEC * 1000))
            if scr.getch() == ord("q"):
                return
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def build_for_preview(patch, hz, t):
    """build the patch against a fake led file under build/."""
    fake = sysblink.BUILD_DIR / "preview" / "brightness"
    fake.parent.mkdir(parents=True, exist_ok=True)
    fake.write_text("0")
    led = {"name": f"preview_{patch[:-2]}", "path": str(fake.parent), "max": "100"}
    return sysblink.build_daemon([led], patch, hz, t)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="sysblink preview", description="watch a patch drive a fake led",
    )
    parser.add_argument("patch", help="patch to preview, with or without .c")
    parser.add_argument("--hz", type=int, default=30,
                        help=f"daemon frequency in hz, {sysblink.MIN_HZ} to {sysblink.MAX_HZ}")
    parser.add_argument("--once", action="store_true",
                        help="run a few ticks, print one bar and exit")
    args = parser.parse_args(argv)

    patch = sysblink.normalize_patch(args.patch)
    if patch not in sysblink.find_patches():
        print(f"[!] unknown patch: {args.patch}")
        return 1
    hz = max(sysblink.MIN_HZ, min(sysblink.MAX_HZ, args.hz))

    binary = build_for_preview(patch, hz, sysblink.load_texts("en"))
    if binary is None:
        return 1
    led_file = sysblink.BUILD_DIR / "preview" / "brightness"

    if args.once:
        proc = subprocess.Popen([str(binary)])
        time.sleep(RUN_TICKS / hz + 0.05)
        # read before stopping, the daemon turns the led off on its way out
        level = read_level(led_file)
        proc.terminate()
        proc.wait(timeout=5)
        print(f"{patch} {hz} hz  {level:3d}  [{bar(level)}]")
        return 0

    curses.wrapper(run_preview, binary, led_file, patch, hz)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        sys.exit(130)
