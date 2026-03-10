#!/usr/bin/env python3
"""
Let Me AI That For You (LMAITFY)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
A moderately passive-aggressive desktop app in the spirit of
"Let Me Google That For You" — but for the AI age.

Modes:
  GUI mode (default):   python3 lmaitfy.py
  GIF export mode:      python3 lmaitfy.py --gif "Why is the sky blue?"
  GIF + custom output:  python3 lmaitfy.py --gif "Why is the sky blue?" -o ~/Desktop/sky.gif

All GIFs are saved to ~/Pictures/lmaitfy/ by default.

Requirements:
  GUI mode:   Python 3.10+  (standard library only)
  GIF mode:   Python 3.10+ + Pillow  (pip install Pillow)
"""

from __future__ import annotations

import argparse
import math
import sys
import urllib.parse
import webbrowser
from enum import Enum, auto
from pathlib import Path

# ── Palette ──────────────────────────────────────────────────────────────────
BG_DARK       = "#1a1a2e"
BG_MID        = "#16213e"
BG_CARD       = "#0f3460"
BG_INPUT      = "#1a1a3e"
ACCENT        = "#e94560"
ACCENT_HOVER  = "#ff6b81"
TEXT_PRIMARY   = "#eaeaea"
TEXT_DIM       = "#8892a8"
TEXT_SNARKY    = "#ff9f43"
CURSOR_COLOR  = "#e94560"
BORDER_COLOR  = "#2a2a5e"
SUCCESS_GREEN = "#2ed573"
TITLE_BAR_BG  = "#0d2d52"
DOT_COLORS    = ("#ff5f57", "#febc2e", "#28c840")

CLAUDE_BASE   = "https://claude.ai/new"
GIF_DIR       = Path.home() / "Pictures" / "lmaitfy"

# ── Snarky remarks ──────────────────────────────────────────────────────────
SNARKY_INTROS: list[str] = [
    "Was that so hard?",
    "See? It's not rocket science.",
    "You're welcome.",
    "Magic, right? Almost like you could've done it yourself.",
    "And that… is how the pros do it.",
    "I'll send you my consulting invoice.",
    "Incredible what technology can do when you use it.",
    "Another mystery solved. You're welcome.",
    "That'll be $200/hr. First one's on me.",
    "Wow. Who knew typing was so difficult?",
]


# ╭──────────────────────────────────────────────────────────────────────────╮
# │  Phase state machine                                                     │
# ╰──────────────────────────────────────────────────────────────────────────╯
class Phase(Enum):
    IDLE        = auto()
    STEP_1      = auto()
    STEP_2      = auto()
    STEP_3      = auto()
    LAUNCHING   = auto()
    DONE        = auto()


# ╭──────────────────────────────────────────────────────────────────────────╮
# │  GIF RENDERER  (Pillow-based, headless — no display server needed)       │
# ╰──────────────────────────────────────────────────────────────────────────╯

def generate_gif(question: str, output_path: str, snarky_index: int = 0) -> Path:
    """Render a LMGTFY-style GIF that shows a mouse cursor navigating to
    claude.ai, typing the question into the chat input, and clicking send.

    The entire GIF looks like a screen recording of someone using a browser
    — maximum passive-aggressive energy.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("GIF mode requires Pillow.  Install it:  pip install Pillow", file=sys.stderr)
        sys.exit(1)

    W, H = 780, 560
    FPS = 15
    frame_ms = 1000 // FPS

    # ── Font helpers ─────────────────────────────────────────────────────────
    def _load(size: int, bold: bool = False):
        names = (["DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"]
                 if bold else ["DejaVuSans.ttf", "LiberationSans-Regular.ttf"])
        for n in names:
            try: return ImageFont.truetype(n, size)
            except OSError: pass
        for b in ("/usr/share/fonts", "/usr/local/share/fonts", "/System/Library/Fonts"):
            for n in names:
                for h in Path(b).rglob(n):
                    try: return ImageFont.truetype(str(h), size)
                    except OSError: pass
        return ImageFont.load_default()

    def _load_mono(size: int):
        for n in ("DejaVuSansMono.ttf", "LiberationMono-Regular.ttf"):
            try: return ImageFont.truetype(n, size)
            except OSError: pass
        for b in ("/usr/share/fonts", "/usr/local/share/fonts", "/System/Library/Fonts"):
            for n in ("DejaVuSansMono.ttf", "LiberationMono-Regular.ttf"):
                for h in Path(b).rglob(n):
                    try: return ImageFont.truetype(str(h), size)
                    except OSError: pass
        return ImageFont.load_default()

    f_title   = _load(24, bold=True)
    f_sub     = _load(13)
    f_body    = _load(13)
    f_body_lg = _load(16)
    f_small   = _load(11)
    f_mono    = _load_mono(13)
    f_mono_sm = _load_mono(11)
    f_snark   = _load(18, bold=True)
    f_step    = _load(13, bold=True)

    snarky_remark = SNARKY_INTROS[snarky_index % len(SNARKY_INTROS)]

    # ── Colour shortcuts ─────────────────────────────────────────────────────
    C_BG       = "#1b1b2f"
    C_BROWSER  = "#252545"
    C_TITLEBAR = "#1e1e3a"
    C_URL_BG   = "#13132b"
    C_URL_HL   = "#3a3a6a"     # highlighted URL bar
    C_PAGE_BG  = "#f7f7f8"     # Claude.ai page background (light)
    C_PAGE_DIM = "#b0b0b8"
    C_CHAT_BG  = "#ffffff"
    C_CHAT_BD  = "#d4d4dc"
    C_CHAT_TXT = "#2b2b2b"
    C_SEND_BTN = "#d97706"     # Claude's amber send button
    C_SEND_HOV = "#f59e0b"
    C_SEND_DIS = "#e0e0e0"
    C_OVERLAY  = "#1b1b2f"
    C_ACCENT   = ACCENT

    # ── Layout constants ─────────────────────────────────────────────────────
    BROWSER_X, BROWSER_Y = 20, 60
    BROWSER_W, BROWSER_H = W - 40, H - 80
    TITLEBAR_H = 36
    URL_BAR_Y = BROWSER_Y + TITLEBAR_H + 6
    URL_BAR_H = 28
    URL_BAR_X1 = BROWSER_X + 14
    URL_BAR_X2 = BROWSER_X + BROWSER_W - 14
    URL_BAR_MID = (URL_BAR_X1 + 80, URL_BAR_Y + URL_BAR_H // 2)

    PAGE_Y = URL_BAR_Y + URL_BAR_H + 8
    PAGE_X1 = BROWSER_X + 2
    PAGE_X2 = BROWSER_X + BROWSER_W - 2
    PAGE_H  = BROWSER_Y + BROWSER_H - PAGE_Y - 2

    # Claude.ai chat input position (relative to page)
    CHAT_INPUT_X1 = PAGE_X1 + 80
    CHAT_INPUT_X2 = PAGE_X2 - 80
    CHAT_INPUT_Y  = PAGE_Y + PAGE_H - 80
    CHAT_INPUT_H  = 48
    CHAT_INPUT_Y2 = CHAT_INPUT_Y + CHAT_INPUT_H
    CHAT_TEXT_ORIG = (CHAT_INPUT_X1 + 16, CHAT_INPUT_Y + 14)
    CHAT_CLICK_PT = (CHAT_INPUT_X1 + 60, CHAT_INPUT_Y + CHAT_INPUT_H // 2)

    # Send button (right side of chat input)
    SEND_BTN_R  = CHAT_INPUT_X2 - 12
    SEND_BTN_L  = SEND_BTN_R - 36
    SEND_BTN_T  = CHAT_INPUT_Y + 6
    SEND_BTN_B  = CHAT_INPUT_Y2 - 6
    SEND_BTN_CENTER = ((SEND_BTN_L + SEND_BTN_R) // 2, (SEND_BTN_T + SEND_BTN_B) // 2)

    CURSOR_START = (W // 2, H // 2 - 40)

    # ── Drawing primitives ───────────────────────────────────────────────────
    def _lerp(a: tuple, b: tuple, t: float) -> tuple[int, int]:
        t = max(0.0, min(1.0, t))
        t = 4*t*t*t if t < 0.5 else 1 - (-2*t + 2)**3 / 2  # ease-in-out
        return (int(a[0] + (b[0]-a[0])*t), int(a[1] + (b[1]-a[1])*t))

    def _draw_mouse(draw, x, y, clicking=False):
        c = C_ACCENT if clicking else "#ffffff"
        pts = [(x,y),(x,y+20),(x+5,y+16),(x+9,y+24),(x+12,y+23),(x+9,y+15),(x+14,y+14)]
        draw.polygon(pts, fill=c, outline="#000000")

    def _center_text(draw, text, font, y, fill, x_center=W//2):
        bb = draw.textbbox((0,0), text, font=font)
        tw = bb[2]-bb[0]
        draw.text((x_center - tw//2, y), text, font=font, fill=fill)

    def _draw_browser_chrome(draw, url_text="", url_highlighted=False):
        """Draw browser window chrome: title bar + URL bar."""
        # browser bg
        draw.rounded_rectangle(
            [BROWSER_X, BROWSER_Y, BROWSER_X+BROWSER_W, BROWSER_Y+BROWSER_H],
            radius=10, fill=C_BROWSER, outline="#3a3a5e",
        )
        # title bar
        draw.rounded_rectangle(
            [BROWSER_X, BROWSER_Y, BROWSER_X+BROWSER_W, BROWSER_Y+TITLEBAR_H],
            radius=10, fill=C_TITLEBAR,
        )
        draw.rectangle(
            [BROWSER_X, BROWSER_Y+TITLEBAR_H-8, BROWSER_X+BROWSER_W, BROWSER_Y+TITLEBAR_H],
            fill=C_TITLEBAR,
        )
        # traffic lights
        for i, c in enumerate(DOT_COLORS):
            cx = BROWSER_X + 22 + i*20
            cy = BROWSER_Y + TITLEBAR_H//2
            draw.ellipse([cx-6, cy-6, cx+6, cy+6], fill=c)

        # tab
        tab_x = BROWSER_X + 90
        draw.rounded_rectangle([tab_x, BROWSER_Y+6, tab_x+160, BROWSER_Y+TITLEBAR_H],
                               radius=6, fill=C_BROWSER)
        draw.text((tab_x+10, BROWSER_Y+12), "Claude", font=f_small, fill=TEXT_DIM)

        # URL bar
        url_bg = C_URL_HL if url_highlighted else C_URL_BG
        draw.rounded_rectangle(
            [URL_BAR_X1, URL_BAR_Y, URL_BAR_X2, URL_BAR_Y+URL_BAR_H],
            radius=6, fill=url_bg, outline="#3a3a6a",
        )
        if url_text:
            draw.text((URL_BAR_X1+12, URL_BAR_Y+6), url_text, font=f_mono_sm, fill=TEXT_PRIMARY)

    def _draw_claude_page(draw, chat_text="", show_cursor=False, placeholder=True,
                          send_active=False, send_hover=False):
        """Draw a simplified Claude.ai page inside the browser."""
        # page background
        draw.rectangle([PAGE_X1, PAGE_Y, PAGE_X2, PAGE_Y+PAGE_H], fill=C_PAGE_BG)

        # Claude logo / greeting area
        mid_x = (PAGE_X1 + PAGE_X2) // 2
        _center_text(draw, "Claude", f_title, PAGE_Y + 50, "#c46d30", mid_x)
        _center_text(draw, "How can I help you today?", f_body_lg, PAGE_Y + 86, C_PAGE_DIM, mid_x)

        # Chat input box
        draw.rounded_rectangle(
            [CHAT_INPUT_X1, CHAT_INPUT_Y, CHAT_INPUT_X2, CHAT_INPUT_Y2],
            radius=24, fill=C_CHAT_BG, outline=C_CHAT_BD, width=2,
        )

        # Placeholder or typed text
        if chat_text:
            cursor_str = " ▎" if show_cursor else ""
            draw.text(CHAT_TEXT_ORIG, chat_text + cursor_str, font=f_mono, fill=C_CHAT_TXT)
        elif placeholder:
            draw.text(CHAT_TEXT_ORIG, "Reply to Claude…", font=f_body, fill="#b0b0b8")

        # Send button (arrow)
        btn_color = C_SEND_HOV if send_hover else (C_SEND_BTN if send_active else C_SEND_DIS)
        draw.rounded_rectangle(
            [SEND_BTN_L, SEND_BTN_T, SEND_BTN_R, SEND_BTN_B],
            radius=8, fill=btn_color,
        )
        # arrow icon (triangle pointing up)
        ax, ay = SEND_BTN_CENTER
        arrow_c = "#ffffff" if send_active or send_hover else "#a0a0a0"
        draw.polygon([(ax, ay-8), (ax-7, ay+5), (ax+7, ay+5)], fill=arrow_c)

    # ── Snarky step overlay at bottom ────────────────────────────────────────
    def _draw_step_banner(draw, step_text: str, snarky_text: str):
        """Semi-transparent-looking banner at the top with the step instruction."""
        banner_h = 50
        draw.rectangle([0, 0, W, banner_h], fill=C_OVERLAY)
        draw.line([(0, banner_h), (W, banner_h)], fill=BORDER_COLOR)
        if step_text:
            _center_text(draw, step_text, f_step, 8, TEXT_SNARKY)
        if snarky_text:
            _center_text(draw, snarky_text, f_sub, 28, C_ACCENT)

    # ── Frame accumulator ────────────────────────────────────────────────────
    frames: list[Image.Image] = []
    durations: list[int] = []

    def _add(img: Image.Image, ms: int = frame_ms):
        frames.append(img.quantize(colors=128, method=Image.Quantize.MEDIANCUT))
        durations.append(ms)

    def _frame() -> tuple[Image.Image, ImageDraw.ImageDraw]:
        img = Image.new("RGB", (W, H), C_BG)
        return img, ImageDraw.Draw(img)

    typing_speed = max(35, min(75, 2400 // max(len(question), 1)))

    # ═════════════════════════════════════════════════════════════════════════
    # ACT 1 — Empty browser, cursor moves to URL bar and types claude.ai
    # ═════════════════════════════════════════════════════════════════════════

    # Show empty browser with cursor off to the side
    for _ in range(8):
        img, d = _frame()
        _draw_browser_chrome(d, url_text="")
        draw_area_y = URL_BAR_Y + URL_BAR_H + 8
        d.rectangle([PAGE_X1, draw_area_y, PAGE_X2, BROWSER_Y+BROWSER_H-2], fill="#2a2a4a")
        _center_text(d, "New Tab", f_body_lg, draw_area_y + 80, TEXT_DIM)
        _draw_mouse(d, *CURSOR_START)
        _draw_step_banner(d, "Step 1:  Open your browser and go to claude.ai",
                          "I know, it's a lot. Stay with me.")
        _add(img, frame_ms)

    # Cursor moves to URL bar
    for f in range(12):
        img, d = _frame()
        _draw_browser_chrome(d, url_text="")
        draw_area_y = URL_BAR_Y + URL_BAR_H + 8
        d.rectangle([PAGE_X1, draw_area_y, PAGE_X2, BROWSER_Y+BROWSER_H-2], fill="#2a2a4a")
        _center_text(d, "New Tab", f_body_lg, draw_area_y + 80, TEXT_DIM)
        pos = _lerp(CURSOR_START, URL_BAR_MID, f / 11)
        _draw_mouse(d, *pos)
        _draw_step_banner(d, "Step 1:  Open your browser and go to claude.ai",
                          "I know, it's a lot. Stay with me.")
        _add(img, frame_ms)

    # Click on URL bar
    for _ in range(3):
        img, d = _frame()
        _draw_browser_chrome(d, url_text="", url_highlighted=True)
        draw_area_y = URL_BAR_Y + URL_BAR_H + 8
        d.rectangle([PAGE_X1, draw_area_y, PAGE_X2, BROWSER_Y+BROWSER_H-2], fill="#2a2a4a")
        _center_text(d, "New Tab", f_body_lg, draw_area_y + 80, TEXT_DIM)
        _draw_mouse(d, *URL_BAR_MID, clicking=True)
        _draw_step_banner(d, "Step 1:  Open your browser and go to claude.ai",
                          "I know, it's a lot. Stay with me.")
        _add(img, frame_ms)

    # Type "claude.ai" into URL bar
    url_str = "claude.ai"
    for i in range(1, len(url_str) + 1):
        img, d = _frame()
        _draw_browser_chrome(d, url_text=url_str[:i] + " ▎", url_highlighted=True)
        draw_area_y = URL_BAR_Y + URL_BAR_H + 8
        d.rectangle([PAGE_X1, draw_area_y, PAGE_X2, BROWSER_Y+BROWSER_H-2], fill="#2a2a4a")
        _center_text(d, "New Tab", f_body_lg, draw_area_y + 80, TEXT_DIM)
        _draw_mouse(d, URL_BAR_MID[0] + 20, URL_BAR_MID[1] + 10)
        _draw_step_banner(d, "Step 1:  Open your browser and go to claude.ai",
                          "Type the URL. Yes, the whole thing.")
        _add(img, 90)

    # Pause, then "press Enter" — page loads
    for _ in range(8):
        img, d = _frame()
        _draw_browser_chrome(d, url_text="claude.ai", url_highlighted=True)
        draw_area_y = URL_BAR_Y + URL_BAR_H + 8
        d.rectangle([PAGE_X1, draw_area_y, PAGE_X2, BROWSER_Y+BROWSER_H-2], fill="#2a2a4a")
        _center_text(d, "New Tab", f_body_lg, draw_area_y + 80, TEXT_DIM)
        _draw_mouse(d, URL_BAR_MID[0] + 20, URL_BAR_MID[1] + 10)
        _draw_step_banner(d, "Step 1:  Open your browser and go to claude.ai",
                          "Now press Enter. The big key.")
        _add(img, frame_ms)

    # "Loading" flash — brief white page
    for _ in range(4):
        img, d = _frame()
        _draw_browser_chrome(d, url_text="https://claude.ai")
        d.rectangle([PAGE_X1, PAGE_Y, PAGE_X2, PAGE_Y+PAGE_H], fill="#ffffff")
        _draw_step_banner(d, "Step 1:  Open your browser and go to claude.ai",
                          "Loading… almost there…")
        _add(img, 120)

    # ═════════════════════════════════════════════════════════════════════════
    # ACT 2 — Claude.ai loads, page appears
    # ═════════════════════════════════════════════════════════════════════════

    # Page loaded, hold for a beat
    for _ in range(12):
        img, d = _frame()
        _draw_browser_chrome(d, url_text="https://claude.ai")
        _draw_claude_page(d)
        _draw_mouse(d, W//2, H//2 - 30)
        _draw_step_banner(d, "Step 2:  Find the text box at the bottom",
                          "See that box? That's where the magic happens.")
        _add(img, frame_ms)

    # ═════════════════════════════════════════════════════════════════════════
    # ACT 3 — Cursor moves to chat input and clicks
    # ═════════════════════════════════════════════════════════════════════════

    for f in range(14):
        img, d = _frame()
        _draw_browser_chrome(d, url_text="https://claude.ai")
        _draw_claude_page(d)
        pos = _lerp((W//2, H//2 - 30), CHAT_CLICK_PT, f / 13)
        _draw_mouse(d, *pos)
        _draw_step_banner(d, "Step 2:  Click on the text box",
                          "Move your mouse down there. You can do this.")
        _add(img, frame_ms)

    # Click
    for _ in range(3):
        img, d = _frame()
        _draw_browser_chrome(d, url_text="https://claude.ai")
        _draw_claude_page(d, placeholder=False, show_cursor=True)
        _draw_mouse(d, *CHAT_CLICK_PT, clicking=True)
        _draw_step_banner(d, "Step 2:  Click on the text box",
                          "Click! Nailed it.")
        _add(img, frame_ms)

    # ═════════════════════════════════════════════════════════════════════════
    # ACT 4 — Type the question character by character
    # ═════════════════════════════════════════════════════════════════════════

    cursor_rest = (CHAT_CLICK_PT[0] + 20, CHAT_CLICK_PT[1] + 12)

    # brief pause before typing
    for _ in range(4):
        img, d = _frame()
        _draw_browser_chrome(d, url_text="https://claude.ai")
        _draw_claude_page(d, chat_text="", show_cursor=True, placeholder=False)
        _draw_mouse(d, *cursor_rest)
        _draw_step_banner(d, "Step 3:  Type your question",
                          "One letter at a time. You can do this.")
        _add(img, frame_ms)

    for i in range(1, len(question) + 1):
        img, d = _frame()
        _draw_browser_chrome(d, url_text="https://claude.ai")
        _draw_claude_page(d, chat_text=question[:i], show_cursor=True,
                          placeholder=False, send_active=True)
        _draw_mouse(d, *cursor_rest)
        _draw_step_banner(d, "Step 3:  Type your question",
                          "One letter at a time. You can do this.")
        _add(img, typing_speed)

    # pause after typing
    for _ in range(10):
        img, d = _frame()
        _draw_browser_chrome(d, url_text="https://claude.ai")
        _draw_claude_page(d, chat_text=question, show_cursor=True,
                          placeholder=False, send_active=True)
        _draw_mouse(d, *cursor_rest)
        _draw_step_banner(d, "Step 3:  Type your question",
                          "Look at that. A whole question. Typed by you.")
        _add(img, frame_ms)

    # ═════════════════════════════════════════════════════════════════════════
    # ACT 5 — Move to send button and click
    # ═════════════════════════════════════════════════════════════════════════

    for f in range(14):
        img, d = _frame()
        _draw_browser_chrome(d, url_text="https://claude.ai")
        t = f / 13
        hovering = t > 0.75
        _draw_claude_page(d, chat_text=question, show_cursor=False,
                          placeholder=False, send_active=True, send_hover=hovering)
        pos = _lerp(cursor_rest, SEND_BTN_CENTER, t)
        _draw_mouse(d, *pos)
        _draw_step_banner(d, "Step 4:  Click the send button",
                          "The little arrow. Right there. Almost done.")
        _add(img, frame_ms)

    # Hover
    for _ in range(5):
        img, d = _frame()
        _draw_browser_chrome(d, url_text="https://claude.ai")
        _draw_claude_page(d, chat_text=question, show_cursor=False,
                          placeholder=False, send_active=True, send_hover=True)
        _draw_mouse(d, *SEND_BTN_CENTER)
        _draw_step_banner(d, "Step 4:  Click the send button",
                          "Right there. You see it?")
        _add(img, frame_ms)

    # Click!
    for _ in range(4):
        img, d = _frame()
        _draw_browser_chrome(d, url_text="https://claude.ai")
        _draw_claude_page(d, chat_text=question, show_cursor=False,
                          placeholder=False, send_active=True, send_hover=True)
        _draw_mouse(d, *SEND_BTN_CENTER, clicking=True)
        _draw_step_banner(d, "Step 4:  Click!",
                          "CLICK. There you go.")
        _add(img, frame_ms)

    # ═════════════════════════════════════════════════════════════════════════
    # ACT 6 — "Sent" state — input clears, thinking indicator
    # ═════════════════════════════════════════════════════════════════════════

    for _ in range(15):
        img, d = _frame()
        _draw_browser_chrome(d, url_text="https://claude.ai")
        _draw_claude_page(d, chat_text="", placeholder=True)
        # show user message bubble
        bubble_x = PAGE_X2 - 60
        # user message
        bb = d.textbbox((0,0), question, font=f_body)
        bw = min(bb[2]-bb[0] + 24, CHAT_INPUT_X2 - CHAT_INPUT_X1 - 40)
        bx1 = bubble_x - bw
        by1 = CHAT_INPUT_Y - 70
        d.rounded_rectangle([bx1, by1, bubble_x, by1+36], radius=16, fill="#d97706")
        d.text((bx1+12, by1+9), question[:40] + ("…" if len(question)>40 else ""),
               font=f_small, fill="#ffffff")
        # thinking dots
        _center_text(d, "Claude is thinking…", f_small, by1 + 44, C_PAGE_DIM,
                     (PAGE_X1+PAGE_X2)//2)
        _draw_step_banner(d, "", snarky_remark)
        _add(img, frame_ms)

    # ═════════════════════════════════════════════════════════════════════════
    # ACT 7 — Final snarky hold frame
    # ═════════════════════════════════════════════════════════════════════════

    img, d = _frame()
    _draw_browser_chrome(d, url_text="https://claude.ai")
    _draw_claude_page(d, chat_text="", placeholder=True)
    bb = d.textbbox((0,0), question, font=f_body)
    bw = min(bb[2]-bb[0] + 24, CHAT_INPUT_X2 - CHAT_INPUT_X1 - 40)
    bubble_x = PAGE_X2 - 60
    bx1 = bubble_x - bw
    by1 = CHAT_INPUT_Y - 70
    d.rounded_rectangle([bx1, by1, bubble_x, by1+36], radius=16, fill="#d97706")
    d.text((bx1+12, by1+9), question[:40] + ("…" if len(question)>40 else ""),
           font=f_small, fill="#ffffff")

    # big snarky text overlay
    overlay_y = 4
    d.rectangle([0, 0, W, 54], fill=C_BG)
    _center_text(d, snarky_remark, f_snark, overlay_y + 4, C_ACCENT)
    _center_text(d, "— Let Me AI That For You —", f_small, overlay_y + 32, TEXT_DIM)
    _add(img, 4000)

    # ── Save GIF ────────────────────────────────────────────────────────────
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        out,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=False,
    )

    size_kb = out.stat().st_size / 1024
    print(f"✓ GIF saved to {out}  ({size_kb:.0f} KB, {len(frames)} frames)")
    return out


# ╭──────────────────────────────────────────────────────────────────────────╮
# │  TKINTER GUI  (original interactive app)                                 │
# ╰──────────────────────────────────────────────────────────────────────────╯

def run_gui() -> None:
    """Launch the interactive Tkinter version."""
    import tkinter as tk
    import tkinter.font as tkfont

    class LMAITFY(tk.Tk):

        def __init__(self) -> None:
            super().__init__()

            self.title("Let Me AI That For You")
            self.configure(bg=BG_DARK)
            self.resizable(False, False)

            w, h = 740, 680
            sx = self.winfo_screenwidth()  // 2 - w // 2
            sy = self.winfo_screenheight() // 2 - h // 2
            self.geometry(f"{w}x{h}+{sx}+{sy}")

            self._fn_title   = tkfont.Font(family="Helvetica Neue", size=26, weight="bold")
            self._fn_sub     = tkfont.Font(family="Helvetica Neue", size=13)
            self._fn_body    = tkfont.Font(family="Helvetica Neue", size=12)
            self._fn_input   = tkfont.Font(family="Courier", size=13)
            self._fn_step    = tkfont.Font(family="Helvetica Neue", size=14, weight="bold")
            self._fn_snarky  = tkfont.Font(family="Helvetica Neue", size=15, slant="italic")
            self._fn_btn     = tkfont.Font(family="Helvetica Neue", size=12, weight="bold")
            self._fn_small   = tkfont.Font(family="Helvetica Neue", size=10)
            self._fn_mock    = tkfont.Font(family="Courier", size=12)

            self._phase         = Phase.IDLE
            self._question      = ""
            self._typed_so_far  = ""
            self._char_idx      = 0
            self._snarky_idx    = 0
            self._blink_on      = True
            self._pulse_angle   = 0.0

            self._build_ui()
            self._blink_cursor_loop()
            self._pulse_loop()

        def _build_ui(self) -> None:
            top = tk.Frame(self, bg=BG_DARK)
            top.pack(fill="x", pady=(28, 0))

            self._lbl_title = tk.Label(
                top, text="Let Me AI That For You",
                font=self._fn_title, fg=ACCENT, bg=BG_DARK,
            )
            self._lbl_title.pack()

            self._lbl_subtitle = tk.Label(
                top, text="Because apparently asking an AI is too complicated.",
                font=self._fn_sub, fg=TEXT_DIM, bg=BG_DARK,
            )
            self._lbl_subtitle.pack(pady=(4, 0))

            tk.Frame(self, bg=BORDER_COLOR, height=1).pack(fill="x", padx=60, pady=(18, 18))

            self._frm_input = tk.Frame(self, bg=BG_DARK)
            self._frm_input.pack(fill="x", padx=50, pady=(0, 6))

            tk.Label(
                self._frm_input,
                text="Type the question your friend couldn't figure out:",
                font=self._fn_body, fg=TEXT_DIM, bg=BG_DARK, anchor="w",
            ).pack(fill="x", pady=(0, 8))

            input_border = tk.Frame(self._frm_input, bg=BORDER_COLOR, bd=0, highlightthickness=0)
            input_border.pack(fill="x")
            inner_pad = tk.Frame(input_border, bg=BG_INPUT, bd=0, padx=2, pady=2)
            inner_pad.pack(fill="x", padx=1, pady=1)

            self._entry = tk.Entry(
                inner_pad, font=self._fn_input, bg=BG_INPUT, fg=TEXT_PRIMARY,
                insertbackground=CURSOR_COLOR, relief="flat", bd=8, highlightthickness=0,
            )
            self._entry.pack(fill="x")
            self._entry.bind("<Return>", lambda _e: self._on_go())
            self._entry.focus_set()

            self._btn_go = tk.Label(
                self._frm_input, text="  Show Them How It's Done  ",
                font=self._fn_btn, fg=BG_DARK, bg=ACCENT, cursor="hand2", padx=18, pady=10,
            )
            self._btn_go.pack(pady=(14, 0))
            self._btn_go.bind("<Enter>", lambda _e: self._btn_go.configure(bg=ACCENT_HOVER))
            self._btn_go.bind("<Leave>", lambda _e: self._btn_go.configure(bg=ACCENT))
            self._btn_go.bind("<Button-1>", lambda _e: self._on_go())

            # ── GIF export button ───────────────────────────────────────────
            self._btn_gif = tk.Label(
                self._frm_input, text="  Export as GIF  ",
                font=self._fn_btn, fg=TEXT_PRIMARY, bg=BG_CARD, cursor="hand2", padx=14, pady=8,
            )
            self._btn_gif.pack(pady=(8, 0))
            self._btn_gif.bind("<Enter>", lambda _e: self._btn_gif.configure(bg=BORDER_COLOR))
            self._btn_gif.bind("<Leave>", lambda _e: self._btn_gif.configure(bg=BG_CARD))
            self._btn_gif.bind("<Button-1>", lambda _e: self._on_export_gif())

            # ── Mock browser card ───────────────────────────────────────────
            self._frm_mock = tk.Frame(self, bg=BG_DARK)

            self._card = tk.Frame(
                self._frm_mock, bg=BG_CARD, bd=0,
                highlightthickness=1, highlightbackground=BORDER_COLOR,
            )
            self._card.pack(fill="x", padx=50)

            title_bar = tk.Frame(self._card, bg=TITLE_BAR_BG, height=32)
            title_bar.pack(fill="x")
            title_bar.pack_propagate(False)

            dots_frame = tk.Frame(title_bar, bg=TITLE_BAR_BG)
            dots_frame.pack(side="left", padx=10)
            for c in DOT_COLORS:
                tk.Canvas(dots_frame, width=11, height=11, bg=c,
                          highlightthickness=0, bd=0).pack(side="left", padx=2, pady=8)
            tk.Label(title_bar, text="Claude.ai", font=self._fn_small,
                     fg=TEXT_DIM, bg=TITLE_BAR_BG).pack(side="left", padx=(8, 0))

            url_frame = tk.Frame(self._card, bg=BG_CARD)
            url_frame.pack(fill="x", padx=12, pady=(8, 4))
            url_inner = tk.Frame(url_frame, bg=BG_INPUT, highlightthickness=1,
                                 highlightbackground=BORDER_COLOR)
            url_inner.pack(fill="x")
            self._lbl_url = tk.Label(
                url_inner, text="  https://claude.ai/new",
                font=self._fn_small, fg=TEXT_DIM, bg=BG_INPUT, anchor="w", pady=4,
            )
            self._lbl_url.pack(fill="x", padx=4)

            chat_area = tk.Frame(self._card, bg=BG_MID, height=140)
            chat_area.pack(fill="x", padx=12, pady=(4, 8))
            chat_area.pack_propagate(False)
            tk.Label(
                chat_area, text="How can I help you today?",
                font=self._fn_body, fg=TEXT_DIM, bg=BG_MID, anchor="center",
            ).pack(expand=True)

            mock_input_frame = tk.Frame(self._card, bg=BG_CARD)
            mock_input_frame.pack(fill="x", padx=12, pady=(0, 12))
            mock_input_border = tk.Frame(mock_input_frame, bg=BORDER_COLOR)
            mock_input_border.pack(fill="x")
            mock_input_inner = tk.Frame(mock_input_border, bg=BG_INPUT, padx=1, pady=1)
            mock_input_inner.pack(fill="x", padx=1, pady=1)

            self._lbl_mock_input = tk.Label(
                mock_input_inner, text="", font=self._fn_mock,
                fg=TEXT_PRIMARY, bg=BG_INPUT, anchor="w", padx=8, pady=8, height=1,
            )
            self._lbl_mock_input.pack(fill="x")

            self._lbl_step = tk.Label(
                self._frm_mock, text="", font=self._fn_step, fg=TEXT_SNARKY, bg=BG_DARK,
            )
            self._lbl_step.pack(pady=(14, 0))

            self._lbl_snarky = tk.Label(
                self._frm_mock, text="", font=self._fn_snarky, fg=ACCENT, bg=BG_DARK,
            )
            self._lbl_snarky.pack(pady=(6, 0))

            self._frm_bottom = tk.Frame(self._frm_mock, bg=BG_DARK)
            self._frm_bottom.pack(pady=(14, 0))

            self._btn_copy = tk.Label(
                self._frm_bottom, text="  Copy Link  ",
                font=self._fn_btn, fg=TEXT_PRIMARY, bg=BG_CARD, cursor="hand2", padx=14, pady=8,
            )
            self._btn_again = tk.Label(
                self._frm_bottom, text="  Educate Someone Else  ",
                font=self._fn_btn, fg=BG_DARK, bg=ACCENT, cursor="hand2", padx=14, pady=8,
            )

            self._btn_copy.bind("<Enter>", lambda _e: self._btn_copy.configure(bg=BORDER_COLOR))
            self._btn_copy.bind("<Leave>", lambda _e: self._btn_copy.configure(bg=BG_CARD))
            self._btn_copy.bind("<Button-1>", lambda _e: self._copy_link())
            self._btn_again.bind("<Enter>", lambda _e: self._btn_again.configure(bg=ACCENT_HOVER))
            self._btn_again.bind("<Leave>", lambda _e: self._btn_again.configure(bg=ACCENT))
            self._btn_again.bind("<Button-1>", lambda _e: self._reset())

        # ── helpers ─────────────────────────────────────────────────────────
        def _build_url(self) -> str:
            return f"{CLAUDE_BASE}?{urllib.parse.urlencode({'q': self._question})}"

        def _set_step(self, text: str) -> None:
            self._lbl_step.configure(text=text)

        def _set_snarky(self, text: str) -> None:
            self._lbl_snarky.configure(text=text)

        def _show_mock_input_text(self, text: str, show_cursor: bool = True) -> None:
            display = text + (" ▎" if show_cursor and self._blink_on else "")
            self._lbl_mock_input.configure(text=display)

        def _blink_cursor_loop(self) -> None:
            self._blink_on = not self._blink_on
            if self._phase in (Phase.STEP_2, Phase.STEP_3):
                self._show_mock_input_text(self._typed_so_far)
            self.after(530, self._blink_cursor_loop)

        def _pulse_loop(self) -> None:
            self._pulse_angle += 0.07
            if self._phase == Phase.IDLE:
                val = int(200 + 33 * math.sin(self._pulse_angle))
                try:
                    self._lbl_title.configure(fg=f"#{val:02x}{50:02x}{70:02x}")
                except tk.TclError:
                    pass
            self.after(50, self._pulse_loop)

        # ── transitions ─────────────────────────────────────────────────────
        def _on_go(self) -> None:
            q = self._entry.get().strip()
            if not q or self._phase != Phase.IDLE:
                return
            self._question = q
            self._char_idx = 0
            self._typed_so_far = ""
            self._frm_input.pack_forget()
            self._frm_mock.pack(fill="x", pady=(6, 0))
            self._lbl_title.configure(fg=ACCENT)
            self._lbl_subtitle.configure(text="Pay close attention. This is educational.")
            self._enter_step1()

        def _on_export_gif(self) -> None:
            q = self._entry.get().strip()
            if not q:
                return
            import tkinter.filedialog as fd
            GIF_DIR.mkdir(parents=True, exist_ok=True)
            path = fd.asksaveasfilename(
                defaultextension=".gif",
                filetypes=[("GIF files", "*.gif")],
                initialdir=str(GIF_DIR),
                initialfile="lmaitfy.gif",
                title="Save GIF as…",
            )
            if path:
                self._btn_gif.configure(text="  Generating…  ", fg=TEXT_SNARKY)
                self.update_idletasks()
                generate_gif(q, path, self._snarky_idx)
                self._btn_gif.configure(text="  GIF Saved ✓  ", fg=SUCCESS_GREEN)
                self.after(2500, lambda: self._btn_gif.configure(text="  Export as GIF  ", fg=TEXT_PRIMARY))

        def _enter_step1(self) -> None:
            self._phase = Phase.STEP_1
            self._set_step("Step 1:  Go to claude.ai")
            self._set_snarky("I know, it's a lot. Stay with me.")
            self._show_mock_input_text("", show_cursor=False)
            self.after(2200, self._enter_step2)

        def _enter_step2(self) -> None:
            self._phase = Phase.STEP_2
            self._set_step("Step 2:  Type your question")
            self._set_snarky("One letter at a time. You can do this.")
            self._type_next_char()

        def _type_next_char(self) -> None:
            if self._phase != Phase.STEP_2:
                return
            if self._char_idx < len(self._question):
                self._typed_so_far = self._question[: self._char_idx + 1]
                self._show_mock_input_text(self._typed_so_far)
                self._char_idx += 1
                delay = max(32, min(85, 2800 // max(len(self._question), 1)))
                self.after(delay, self._type_next_char)
            else:
                self.after(900, self._enter_step3)

        def _enter_step3(self) -> None:
            self._phase = Phase.STEP_3
            self._set_step("Step 3:  Press Enter")
            self._set_snarky("The big key. Bottom-right-ish. You've got this.")
            self.after(2200, self._enter_launch)

        def _enter_launch(self) -> None:
            self._phase = Phase.LAUNCHING
            self._set_step("🚀  Launching…")
            self._set_snarky("")
            self._show_mock_input_text(self._typed_so_far, show_cursor=False)
            webbrowser.open(self._build_url())
            self.after(1600, self._enter_done)

        def _enter_done(self) -> None:
            self._phase = Phase.DONE
            remark = SNARKY_INTROS[self._snarky_idx % len(SNARKY_INTROS)]
            self._snarky_idx += 1
            self._set_step("")
            self._set_snarky(remark)
            self._lbl_subtitle.configure(text="Knowledge delivered. You're welcome.")
            self._btn_copy.pack(side="left", padx=(0, 10))
            self._btn_again.pack(side="left")

        def _copy_link(self) -> None:
            self.clipboard_clear()
            self.clipboard_append(self._build_url())
            self._btn_copy.configure(text="  Copied ✓  ", fg=SUCCESS_GREEN)
            self.after(2000, lambda: self._btn_copy.configure(text="  Copy Link  ", fg=TEXT_PRIMARY))

        def _reset(self) -> None:
            self._phase = Phase.IDLE
            self._question = ""
            self._typed_so_far = ""
            self._char_idx = 0
            self._frm_mock.pack_forget()
            self._btn_copy.pack_forget()
            self._btn_again.pack_forget()
            self._lbl_step.configure(text="")
            self._lbl_snarky.configure(text="")
            self._show_mock_input_text("", show_cursor=False)
            self._lbl_subtitle.configure(text="Because apparently asking an AI is too complicated.")
            self._frm_input.pack(fill="x", padx=50, pady=(0, 6))
            self._entry.delete(0, "end")
            self._entry.focus_set()

    app = LMAITFY()
    app.mainloop()


# ╭──────────────────────────────────────────────────────────────────────────╮
# │  CLI entry point                                                         │
# ╰──────────────────────────────────────────────────────────────────────────╯

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="lmaitfy",
        description="Let Me AI That For You — passive-aggressive AI education tool.",
    )
    parser.add_argument(
        "--gif",
        metavar="QUESTION",
        help="Generate a GIF of the animation instead of launching the GUI.",
    )
    parser.add_argument(
        "-o", "--output",
        default=str(GIF_DIR / "lmaitfy.gif"),
        help=f"Output path for the GIF (default: {GIF_DIR / 'lmaitfy.gif'}).",
    )
    args = parser.parse_args()

    if args.gif:
        generate_gif(args.gif, args.output)
    else:
        run_gui()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())