import argparse
import colorsys
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path

import keyboard
import mouse
import mss
import numpy as np
import pyautogui
import pydirectinput
import pygetwindow
import win32gui
from PIL import Image, ImageDraw
from requests import get

pyautogui.FAILSAFE = False
__version__ = "vDEV"


def check_git_version_match():
    try:
        git_version = get(
            "https://api.github.com/repos/thefrozenfishy/exedra-sa-recorder/releases/latest",
            timeout=10,
        )
        if git_version.status_code == 200:
            data = git_version.json()
            version = data["tag_name"].lstrip("version-")
            if f"v{version}" != __version__:
                logger.warning(
                    "New version available: v%s, you are on %s", version, __version__
                )
    except Exception:
        logger.error("Failed to get git version")


def parse_args():
    parser = argparse.ArgumentParser(description="SA Player")
    parser.add_argument(
        "-r",
        "--record",
        action="store_true",
        help="Start directly in record mode",
    )
    parser.add_argument(
        "-e",
        "--execute",
        type=str,
        metavar="SEQ",
        help="Execute a specific sequence (without .txt)",
    )
    return parser.parse_args()


click_boxes = {}

TARGET_RUN = "default"
STEP_IDX = 0
DEBUG = True
LAST_CLICK_TIME = None
RECORD_FILE = None


def get_game_window():
    wins = pygetwindow.getWindowsWithTitle("MadokaExedra")
    if not wins:
        raise RuntimeError("Game window not found")
    return wins[0]


def take_debug_screenshot() -> None:
    client_left, client_top, *_ = click_boxes["screen"]
    img = grab_region(click_boxes["screen"])
    draw = ImageDraw.Draw(img)
    for name, coords in click_boxes.items():
        if len(coords) == 4:
            x1, y1, x2, y2 = coords
            x1 -= client_left
            x2 -= client_left
            y1 -= client_top
            y2 -= client_top
            x = (x1 + x2) // 2
            y = (y1 + y2) // 2
            colour = "magenta"
            draw.rectangle((x1, y1, x2, y2), outline=colour, width=2)
        else:
            x, y = coords
            x -= client_left
            y -= client_top
            colour = "cyan"
            r = 5
            draw.ellipse((x - r, y - r, x + r, y + r), outline=colour, width=10)

        draw.text((x + 4, y + 4), name, fill=colour)
    img.save("debug/full_screencap.png")


def on_click_event():
    global LAST_CLICK_TIME

    if not LAST_CLICK_TIME or not RECORD_FILE:
        return

    name = click_in_box(*mouse.get_position())
    now = time.monotonic()
    delta = now - LAST_CLICK_TIME
    LAST_CLICK_TIME = now
    if isinstance(name, str):
        line = f"{name}, {delta:.2f}\n"
    else:
        logger.warning("Clicked outside of defined boxes at %s, %s", *name)
        return

    RECORD_FILE.write(line)
    RECORD_FILE.flush()

    logger.debug("Recorded: %s", line.strip())


def on_write_event(button):
    global LAST_CLICK_TIME

    if not LAST_CLICK_TIME or not RECORD_FILE:
        return

    now = time.monotonic()
    delta = now - LAST_CLICK_TIME
    LAST_CLICK_TIME = now
    line = f"{button}, {delta:.2f}\n"

    RECORD_FILE.write(line)
    RECORD_FILE.flush()

    logger.debug("Recorded: %s", line.strip())


keyboard.add_hotkey("ctrl+shift+x", lambda: os._exit(0))
keyboard.add_hotkey("ctrl+shift+p", take_debug_screenshot)
mouse.on_click(on_click_event)
keyboard.on_press_key("e", lambda _: on_write_event("e"))
keyboard.on_press_key("q", lambda _: on_write_event("q"))

log_formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - %(message)s", "%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("sa_player")
logger.setLevel(logging.DEBUG if DEBUG else logging.INFO)

console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
logger.addHandler(console_handler)

if DEBUG:
    os.makedirs("debug/logs", exist_ok=True)
    file_handler = logging.FileHandler(
        f"debug/logs/{datetime.today().strftime('%Y-%m-%dT%H-%M-%S')}.txt",
        encoding="utf-8",
    )
    file_handler.setFormatter(log_formatter)
    logger.addHandler(file_handler)


def click(pos: str, sleep: str):
    global STEP_IDX
    if len(click_boxes[pos]) == 4:
        x = (click_boxes[pos][0] + click_boxes[pos][2]) / 2
        y = (click_boxes[pos][1] + click_boxes[pos][3]) / 2
    else:
        x = click_boxes[pos][0]
        y = click_boxes[pos][1]

    img = grab_region(click_boxes["screen"])
    draw = ImageDraw.Draw(img)

    r = 5
    client_left, client_top, *_ = click_boxes["screen"]
    draw.ellipse(
        (
            x - client_left - r,
            y - client_top - r,
            x - client_left + r,
            y - client_top + r,
        ),
        outline="cyan",
        width=10,
    )

    if DEBUG:
        os.makedirs(f"debug/steps/{TARGET_RUN}/", exist_ok=True)
        img.save(f"debug/steps/{TARGET_RUN}/{STEP_IDX:03}_{pos}.png")

    pyautogui.sleep(float(sleep))
    curr = pyautogui.position()
    pydirectinput.click(int(x), int(y))
    pyautogui.moveTo(curr)
    STEP_IDX += 1


def grab_region(bbox):
    x1, y1, x2, y2 = bbox
    with mss.mss() as sct:
        monitor = {
            "left": x1,
            "top": y1,
            "width": x2 - x1,
            "height": y2 - y1,
        }
        img = sct.grab(monitor)
        return Image.frombytes("RGB", img.size, img.rgb)


def click_in_box(x, y) -> str | tuple[int, int]:
    for name, (x1, y1, x2, y2) in [
        (x, y) for x, y in click_boxes.items() if len(y) == 4 and x != "screen"
    ]:
        if x1 <= x <= x2 and y1 <= y <= y2:
            return name
    return x, y


def setup_text_locations(focus: bool):
    win = get_game_window()
    try:
        if focus:
            win.activate()
    except Exception as e:
        logger.exception(
            """Could not activate window!
This is not a major issue, just be sure that no application is hiding Exedra from view. 
The OCR has to 'see' the content of the game to determine what to do.""",
            exc_info=e,
        )
    hwnd = win._hWnd
    client_rect = win32gui.GetClientRect(hwnd)
    (client_left, client_top) = win32gui.ClientToScreen(hwnd, (0, 0))
    (client_right, client_bottom) = win32gui.ClientToScreen(
        hwnd, (client_rect[2], client_rect[3])
    )
    client_width = client_right - client_left
    client_height = client_bottom - client_top

    for i in range(5):
        click_boxes[f"u{i}s"] = (
            int(client_left + (0.9 + i) * client_width // 9),
            int(client_bottom - 0.35 * client_height),
            int(client_left + (1.6 + i) * client_width // 9),
            int(client_bottom - 0.1 * client_height),
        )
    for i in range(5):
        click_boxes[f"u{i}alive"] = (
            int(client_left + (1.1 + i) * client_width // 9),
            int(client_bottom - 0.25 * client_height),
            int(client_left + (1.5 + i) * client_width // 9),
            int(client_bottom - 0.15 * client_height),
        )
    for i in range(5):
        click_boxes[f"u{i}u"] = (
            int(client_left + (1.5 + i) * client_width // 9),
            int(client_bottom - 0.24 * client_height),
            int(client_left + (1.7 + i) * client_width // 9),
            int(client_bottom - 0.20 * client_height),
        )
    for i in range(5):
        for j in range(4):
            click_boxes[f"u{i}a{j}"] = (
                int(client_left + (0.095 + 0.018 * j + 0.113 * i) * client_width),
                int(client_bottom - 0.1 * client_height),
                int(client_left + (0.11 + 0.018 * j + 0.113 * i) * client_width),
                int(client_bottom - 0.08 * client_height),
            )

    for i in range(5):
        click_boxes[f"u{i}hp"] = (
            int(client_left + (0.1 + 0.113 * i) * client_width),
            int(client_bottom - 0.13 * client_height),
            int(client_left + (0.11 + 0.113 * i) * client_width),
            int(client_bottom - 0.12 * client_height),
        )
    click_boxes["bs"] = (
        client_left + 0.89 * client_width,
        client_top + 0.65 * client_height,
        client_left + 0.96 * client_width,
        client_top + 0.78 * client_height,
    )
    click_boxes["ba"] = (
        client_left + 0.77 * client_width,
        client_top + 0.7 * client_height,
        client_left + 0.88 * client_width,
        client_top + 0.9 * client_height,
    )

    click_boxes["retry_after_win"] = (
        client_left + 0.9 * client_width,
        client_top + 0.85 * client_height,
    )
    click_boxes["retry_in_pause"] = (
        client_left + 0.49 * client_width,
        client_top + 0.80 * client_height,
    )
    click_boxes["retry_in_pause_ok"] = (
        client_left + 0.6 * client_width,
        client_top + 0.8 * client_height,
    )
    click_boxes["pause"] = (
        client_left + 0.95 * client_width,
        client_top + 0.06 * client_height,
    )
    click_boxes["screen"] = (client_left, client_top, client_right, client_bottom)
    if DEBUG:
        take_debug_screenshot()


def is_curr_hp_colour(user_idx: str, colour: str) -> bool:
    colour_img = grab_region(click_boxes[f"u{user_idx}hp"])
    arr = np.array(colour_img).astype(float) / 255.0
    avg_rgb = arr.mean(axis=(0, 1))  # [R, G, B] normalized
    r, g, b = avg_rgb
    logger.debug("HP colour for user %s: R=%.2f, G=%.2f, B=%.2f", user_idx, r, g, b)
    if DEBUG:
        os.makedirs(f"debug/hp/{colour}", exist_ok=True)
        colour_img.save(f"debug/hp/{colour}_{r:.2f}_{g:.2f}_{b:.2f}.png")
    if colour == "red" and r > 0.8 and g < 0.4 and b < 0.4:
        return True
    if colour == "red" and r < 0.2 and g < 0.2 and b < 0.2:
        # Consider dead or almost dead for red
        return True
    if colour == "yellow" and r > 0.7 and g > 0.6 and b < 0.4:
        return True
    if colour == "green" and r < 0.7 and g > 0.7 and b < 0.4:
        return True
    return False


def is_aliment(user_idx: str, stat_idx: int, ailment: str) -> bool:
    colour_img = grab_region(click_boxes[f"u{user_idx}a{stat_idx}"])
    arr = np.array(colour_img).astype(float) / 255.0
    avg_rgb = arr.mean(axis=(0, 1))  # [R, G, B] normalized
    r, g, b = avg_rgb
    ailment_char = "_"
    if ailment == "curse" and 0.45 < r < 0.55 and 0.40 < g < 0.55 and 0.45 < b < 0.60:
        ailment_char = "c"
    if DEBUG:
        os.makedirs(f"debug/ailments/{ailment_char}", exist_ok=True)
        colour_img.save(f"debug/ailments/{ailment_char}_{r:.2f}_{g:.2f}_{b:.2f}.png")

    return ailment_char != "_"


def has_ult(user_idx):
    colour_img = grab_region(click_boxes[f"u{user_idx}u"])
    arr = np.array(colour_img).astype(float) / 255.0
    avg_rgb = arr.mean(axis=(0, 1))  # [R, G, B] normalized
    r, g, b = avg_rgb
    h, s, v = colorsys.rgb_to_hsv(r, g, b)

    has_ultimate = v > 0.85
    if DEBUG:
        os.makedirs("debug/has_ult", exist_ok=True)
        colour_img.save(f"debug/has_ult/{has_ultimate}_{h:.2f}_{s:.2f}_{v:.2f}.png")

    return has_ultimate


def is_alive(user_idx):
    colour_img = grab_region(click_boxes[f"u{user_idx}alive"])
    arr = np.array(colour_img).astype(float) / 255.0
    avg_rgb = arr.mean(axis=(0, 1))
    r, g, b = avg_rgb
    h, s, v = colorsys.rgb_to_hsv(r, g, b)

    _is_alive = v > 0.5
    if DEBUG:
        os.makedirs("debug/is_alive", exist_ok=True)
        colour_img.save(f"debug/is_alive/{_is_alive}_{h:.2f}_{s:.2f}_{v:.2f}.png")
    return _is_alive


_AILMENT_RE = re.compile(r"^(curse|poison)(\d+)(<)(\d+)$")
_ULT_RE = re.compile(r"^ult(\d+)$")
_ALIVE_RE = re.compile(r"^alive(\d+)$")
_HP_RE = re.compile(r"^hp(\d+)(red|yellow|green)$")


def is_cond_true(cond: str) -> bool:
    cond = cond.strip()

    if m := _AILMENT_RE.match(cond):
        ailment, char_idx, comparator, amount = (
            m.group(1),
            m.group(2),
            m.group(3),
            int(m.group(4)),
        )
        if comparator == "<":
            applied = sum(is_aliment(char_idx, i, ailment) for i in range(4))
            if applied >= amount:
                logger.info(
                    "Cond is false (ailment): %s — applied=%d, threshold=%d",
                    cond,
                    applied,
                    amount,
                )
                return False
            return True
        else:
            logger.error("Unknown comparator '%s' in condition: %s", comparator, cond)
            return False

    if m := _ULT_RE.match(cond):
        char_idx = m.group(1)
        if not has_ult(char_idx):
            logger.info("Cond is false (ult): %s", cond)
            return False
        return True

    if m := _ALIVE_RE.match(cond):
        char_idx = m.group(1)
        if not is_alive(char_idx):
            logger.info("Cond is false (alive): %s", cond)
            return False
        return True

    if m := _HP_RE.match(cond):
        char_idx, colour = m.group(1), m.group(2)
        if not is_curr_hp_colour(char_idx, colour):
            logger.info("Cond is false (hp): %s", cond)
            return False
        return True

    logger.error("Unknown condition format: '%s'", cond)
    return False


def execute_seq(seq) -> tuple[bool, bool]:
    """Returns true if should halt"""
    logger.info("Starting sequence execution")
    setup_text_locations(True)
    pyautogui.sleep(1)

    for i, line in enumerate(seq):
        l = line.split("#", 1)
        if len(l) == 2:
            line, comment = [s.strip() for s in line.split("#", 1)]
        else:
            line = line.strip()
            comment = ""
        if not line:
            logger.debug("Comment%3d: %s", i + 1, comment)
            # Use # for comments
            continue
        if "," in line:
            action, wait, *other = [a.strip() for a in line.split(",")]
        else:
            action, wait, other = line, "5", []
        action = action.lower()
        logger.debug("Action %3d: %4s - %5s %s", i + 1, action, wait, comment)
        match action:
            case "stop":
                logger.info("Found stop, stopping")
                return True, False
            case "sc":
                img = grab_region(click_boxes["screen"])
                os.makedirs(f"{TARGET_RUN}_scores/{other[0]}", exist_ok=True)
                i = 0
                for j in range(1000):
                    if not Path(f"{TARGET_RUN}_scores/{other[0]}/{j:03}.png").is_file():
                        i = j
                        break
                img.save(f"{TARGET_RUN}_scores/{other[0]}/{i:03}.png")
                logger.info("Took screenshot in %s, nr %d", other[0], i)
            case "pause":
                input("Sequence paused. Press Enter to continue...")
                logger.info("Continuing after pause")
            case "bss":
                # Shorthand for bs bs if done manually
                click("bs", wait)
                click("bs", "0.3")
            case "u0s" | "u1s" | "u2s" | "u3s" | "u4s" | "ba" | "bs":
                # Select action (uX is ult use)
                click(action, wait)
            case "u0" | "u1" | "u2" | "u3" | "u4":
                # Shorthand for uXs ba if done manually
                click(f"{action}s", wait)
                click("ba", "3")
            case "e" | "q":
                pyautogui.sleep(float(wait))
                pydirectinput.press(action)
            case "cond":
                pyautogui.sleep(float(wait))
                if any(not is_cond_true(cond) for cond in other):
                    return False, False
            case _:
                logger.error("unknown action [%s]", action)
    return False, True


def reset_after_run(take_pic: bool):
    logger.info("Resetting")
    pyautogui.sleep(15)
    if take_pic:
        img = grab_region(click_boxes["screen"])
        os.makedirs(f"{TARGET_RUN}_scores", exist_ok=True)
        i = 0
        for j in range(1000):
            if not Path(f"{TARGET_RUN}_scores/{j:03}.png").is_file():
                i = j
                break
        img.save(f"{TARGET_RUN}_scores/{i:03}.png")
    click("retry_after_win", "1")
    click("retry_after_win", "1")
    click("pause", "1")
    click("retry_in_pause", "1")
    click("retry_in_pause_ok", "1")
    click("retry_in_pause_ok", "10")
    pyautogui.sleep(10)


def get_state() -> str:
    logger.info("What would you like to do?")
    logger.info("[E] Execute a sequence")
    logger.info("[R] Record a new sequence")
    while True:
        choice = input("Enter choice (E/R): ").strip().lower()[0]
        if choice == "e":
            return "execute"
        if choice == "r":
            return "record"
        logger.error("Invalid input. Please enter 'E' to execute or 'R' to record.")
        input()
        raise RuntimeError("Invalid input, should have been caught in loop")


def fetch_target_run() -> str:
    sequences_dir = Path("recorded_sequences")
    sequences_dir.mkdir(exist_ok=True)

    files = sorted(sequences_dir.glob("*.txt"))
    if not files:
        logger.error("No recorded sequences found in 'recorded_sequences/'.")
        input()
        raise RuntimeError("No recorded sequences found.")

    logger.info("\nAvailable sequences:")
    for idx, f in enumerate(files, 1):
        logger.info(f"  [{idx}] {f.stem}")

    while True:
        raw = input(f"Select sequence (1–{len(files)}) or type a name: ").strip()
        if raw.isdigit():
            choice = int(raw)
            if 1 <= choice <= len(files):
                selected = files[choice - 1].stem
                logger.info("Selected sequence: %s", selected)
                return selected
            logger.error(f"Please enter a number between 1 and {len(files)}.")
        elif raw:
            # Allow typing a name directly; warn if it doesn't exist
            candidate = sequences_dir / f"{raw}.txt"
            if candidate.is_file():
                logger.info("Selected sequence: %s", raw)
                return raw
            logger.error(f"'{raw}.txt' not found in recorded_sequences/")
        else:
            logger.error("Input cannot be empty.")


def main():
    global LAST_CLICK_TIME, RECORD_FILE, STEP_IDX, TARGET_RUN

    setup_text_locations(False)

    args = parse_args()
    if args.record:
        state = "record"
    elif args.execute:
        state = "execute"
        TARGET_RUN = args.execute
    else:
        state = get_state()

    if DEBUG:
        take_debug_screenshot()

    logger.info(
        "Setup complete, ready to execute or record sequences. At any moment press ctrl+shift+q to quit"
    )

    while True:
        if state == "execute":
            STEP_IDX = 0

            if not args.execute:
                TARGET_RUN = fetch_target_run()

            path = Path(f"recorded_sequences/{TARGET_RUN}.txt")
            if not path.is_file():
                logger.error("Sequence '%s.txt' not found.", TARGET_RUN)
                return

            while True:
                with open(path, "r", encoding="utf-8") as f:
                    seq = f.readlines()
                stop, take_pic = execute_seq(seq)
                if stop:
                    break
                reset_after_run(take_pic)

        elif state == "record":
            file_name = (
                f"recorded_sequences/{datetime.now().strftime('%Y-%m-%dT%H-%M-%S')}.txt"
            )
            logger.info("Starting recording. Recording will be saved as %s.", file_name)

            LAST_CLICK_TIME = time.monotonic()
            RECORD_FILE = open(file_name, "w", encoding="utf-8")

            while True:
                pyautogui.sleep(1)
        state = get_state()


if __name__ == "__main__":
    main()
