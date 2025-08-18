from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont
import random
import os
import sys


@dataclass(frozen=True)
class Config:
    """
    Centralized configuration for the banner GIF renderer.

    All values are deterministic by default to ensure reproducible output.
    """
    # Canvas & styling
    size: Tuple[int, int] = (550, 75)
    padding_x: int = 32
    radius: int = 18
    bg: Tuple[int, int, int] = (24, 24, 26)
    border: Tuple[int, int, int] = (70, 74, 82)

    # Text content & colors
    prompt: str = " "
    text: str = "Hello World, I'm Sergi󰋙 Santiag󰋙   "
    color_main: Tuple[int, int, int, int] = (60, 255, 120, 255)
    color_red: Tuple[int, int, int, int] = (255, 60, 100, 200)
    color_blue: Tuple[int, int, int, int] = (110, 200, 255, 200)

    # Glitch effect
    glitch_intensity: int = 1  # base pixel offset for RGB glitch layers

    # Cursor
    cursor_char: str = "▋"
    cursor_blink_frames: int = 10

    # Timing
    fps: int = 30
    pause_final_seconds: float = 3.5
    pause_empty_frames: int = 30

    # Font
    font_path: str = "assets/fonts/FiraCodeNerdFont-Regular.ttf"
    fit_min_size: int = 14
    fit_max_size: int = 42

    # Output GIF
    out_path: str = "assets/hi_terminal_prompt.gif"
    loop: int = 0
    disposal: int = 2
    optimize: bool = False  # keep a single global palette across frames
    duration_ms: Optional[int] = None  # if None -> 1000 / fps
    master_palette_colors: int = 256  # global palette size (GIF max is 256)

    # Determinism
    seed: int = 137


def _frame_duration_ms(cfg: Config) -> int:
    """Return per-frame duration in milliseconds derived from FPS or override."""
    return cfg.duration_ms if cfg.duration_ms is not None else int(1000 / cfg.fps)


def load_font(size: int, cfg: Config) -> ImageFont.FreeTypeFont:
    """
    Load the bundled font. Fail fast with a clear message if the file is missing.

    Using a bundled font ensures consistent rendering across environments (CI, macOS, Linux).
    """
    if not cfg.font_path or not os.path.exists(cfg.font_path):
        sys.exit(
            f"Font not found at '{cfg.font_path}'. "
            f"Add it to the repo or update Config.font_path."
        )
    return ImageFont.truetype(cfg.font_path, size)


def pick_font_for_width(max_width: int, cfg: Config) -> ImageFont.FreeTypeFont:
    """
    Binary-search the largest font size such that (PROMPT + TEXT) fits in max_width.

    This keeps the layout stable regardless of the chosen message.
    """
    lo, hi = cfg.fit_min_size, cfg.fit_max_size
    best = lo
    scratch = Image.new("RGB", (1, 1))
    d = ImageDraw.Draw(scratch)

    while lo <= hi:
        mid = (lo + hi) // 2
        f = load_font(mid, cfg)
        w = d.textlength(cfg.prompt + cfg.text, font=f)
        if w <= max_width:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1

    return load_font(best, cfg)


def compute_metrics(font: ImageFont.FreeTypeFont, cfg: Config) -> tuple[int, int]:
    """
    Compute layout metrics used across frames.

    Returns:
        (prompt_width, baseline_y)
        - prompt_width: pixel width of the prompt string
        - baseline_y: vertical baseline to vertically center text
    """
    w, h = cfg.size
    scratch = Image.new("RGB", (1, 1))
    d = ImageDraw.Draw(scratch)

    # Cast to int to keep coordinates integral for PIL drawing operations.
    w_prompt = int(d.textlength(cfg.prompt, font=font))

    hg = font.getbbox("Hg")  # use a typical ascent/descender pair
    text_h = hg[3] - hg[1]
    baseline_y = int((h - text_h) // 2)

    return w_prompt, baseline_y


def draw_box(cfg: Config) -> Image.Image:
    """
    Draw the rounded background panel with a subtle inner highlight.

    Returns an RGBA image used as the base layer for each frame.
    """
    w, h = cfg.size
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    d.rounded_rectangle(
        [0, 0, w - 1, h - 1],
        radius=cfg.radius,
        fill=cfg.bg,
        outline=cfg.border,
        width=2,
    )
    d.rounded_rectangle(
        [2, 2, w - 3, h - 3],
        radius=cfg.radius - 2,
        outline=(255, 255, 255, 28),
        width=1,
    )
    return img


def draw_text_frame(
        base: Image.Image,
        typed: str,
        cursor_on: bool,
        red_off: int,
        blue_off: int,
        font: ImageFont.FreeTypeFont,
        prompt_w: int,
        baseline_y: int,
        cfg: Config,
) -> Image.Image:
    """
    Compose a single RGBA frame: prompt, typed text and RGB glitch overlays.

    Args:
        base: Pre-rendered panel image used as the background.
        typed: Current substring of text to display.
        cursor_on: Whether the cursor glyph should be rendered.
        red_off: Horizontal pixel offset for the red glitch layer.
        blue_off: Horizontal pixel offset for the blue glitch layer.
        font: Font object chosen for this render.
        prompt_w: Pixel width of the prompt string.
        baseline_y: Vertical baseline for text alignment.
        cfg: Global configuration object.
    """
    img = base.copy()
    d = ImageDraw.Draw(img)

    x = cfg.padding_x
    y = baseline_y

    # Prompt in main color
    d.text((x, y), cfg.prompt, font=font, fill=cfg.color_main)

    # Glitch overlays (chromatic aberration effect)
    if red_off or blue_off:
        d.text((x + prompt_w + red_off, y), typed, font=font, fill=cfg.color_red)
        d.text((x + prompt_w + blue_off, y), typed, font=font, fill=cfg.color_blue)

    # Main text
    d.text((x + prompt_w, y), typed, font=font, fill=cfg.color_main)

    # Cursor
    if cursor_on:
        w_typed = d.textlength(typed, font=font)
        d.text((x + prompt_w + w_typed, y), cfg.cursor_char, font=font, fill=cfg.color_main)

    return img


def build_sequence(text: str, pause_full_frames: int, pause_empty_frames: int) -> List[int]:
    """
    Build the per-frame text-length sequence:
      - forward range: 0 to len(text) inclusive
      - hold full text (pause_full_frames)
      - delete backward to 0
      - hold empty (pause_empty_frames)
    """
    l = len(text)
    forward = list(range(l + 1))
    pause_full = [l] * pause_full_frames
    backward = list(range(l - 1, -1, -1))
    pause_empty = [0] * pause_empty_frames
    return forward + pause_full + backward + pause_empty


def render(cfg: Config) -> str:
    """
    Render the animated GIF using a single global palette to avoid color drift.

    Returns:
        Output path of the generated GIF.
    """
    # Timing
    frame_ms = _frame_duration_ms(cfg)
    pause_full_frames = int(cfg.fps * cfg.pause_final_seconds)

    # Resources
    w, _ = cfg.size
    font = pick_font_for_width(w - 2 * cfg.padding_x, cfg)
    prompt_w, baseline_y = compute_metrics(font, cfg)
    panel = draw_box(cfg)

    # Build frame sequence (render RGBA frames first)
    random.seed(cfg.seed)
    frames_rgba: List[Image.Image] = []
    sequence = build_sequence(cfg.text, pause_full_frames, cfg.pause_empty_frames)

    typing_end = len(cfg.text) + 1
    pause_end = typing_end + pause_full_frames

    for i, text_len in enumerate(sequence):
        in_pause_full = typing_end <= i < pause_end

        if in_pause_full:
            red_off = blue_off = 0
        else:
            base_off = cfg.glitch_intensity
            red_off = base_off + random.choice([0, 1, 2])
            blue_off = -(base_off + random.choice([0, 1, 2]))

        cursor_on = (i // cfg.cursor_blink_frames) % 2 == 0
        typed = cfg.text[:text_len]

        fr_rgba = draw_text_frame(
            panel, typed, cursor_on, red_off, blue_off, font, prompt_w, baseline_y, cfg
        )
        frames_rgba.append(fr_rgba)

    # Build a global master palette from a representative frame to keep colors stable
    master_full = draw_text_frame(panel, cfg.text, True, 2, -2, font, prompt_w, baseline_y, cfg)
    master_p = master_full.convert("P", palette=Image.Palette.ADAPTIVE, colors=cfg.master_palette_colors)

    # Quantize all frames against the same palette (no dither to avoid noise artifacts)
    frames_p = [
        fr.convert("RGB").quantize(palette=master_p, dither=Image.Dither.NONE)
        for fr in frames_rgba
    ]

    # Save the GIF with a single global palette (optimize=False is key here)
    frames_p[0].save(
        cfg.out_path,
        save_all=True,
        append_images=frames_p[1:],
        loop=cfg.loop,
        duration=frame_ms,
        optimize=cfg.optimize,
        disposal=cfg.disposal,
    )
    return cfg.out_path


if __name__ == "__main__":
    config = Config()
    path = render(config)
    print("GIF saved at", path)
