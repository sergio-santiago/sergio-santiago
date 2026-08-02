from __future__ import annotations

from dataclasses import dataclass, replace
from typing import List, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont
import random
import os
import sys


@dataclass(frozen=True)
class Config:
    """
    Centralized configuration for the animated header renderer.

    All values are deterministic by default to ensure reproducible output.
    """
    # Canvas & styling
    size: Tuple[int, int] = (720, 75)
    padding_x: int = 32
    radius: int = 18
    bg: Tuple[int, int, int] = (24, 24, 26)
    border: Tuple[int, int, int] = (70, 74, 82)

    # Text content & colors
    prompt: str = " "
    text: str = "I work on the hard problems of money at scale   "
    color_main: Tuple[int, int, int, int] = (60, 255, 120, 255)
    color_red: Tuple[int, int, int, int] = (255, 60, 100, 200)
    color_blue: Tuple[int, int, int, int] = (110, 200, 255, 200)

    # Glitch effect
    glitch_intensity: int = 1  # base pixel offset for RGB glitch layers

    # Cursor
    cursor_char: str = "▋"
    cursor_blink_frames: int = 10

    # Rendering scale. Everything above is in CSS pixels, the size the header is
    # shown at. The file is rendered this many times larger and displayed with an
    # explicit width, because at 1x on a Retina screen the panel gets one device
    # pixel per image pixel while the text beside it gets four, and it shows.
    scale: int = 2

    # Typing rhythm, in characters per frame. Erasing is faster than typing for
    # the same reason it is in a real terminal, and it also halves the frames:
    # the backspacing was 46 of the 109 frames and the least interesting of them.
    type_step: int = 1
    erase_step: int = 4

    # Timing
    fps: int = 30
    pause_final_seconds: float = 3.5
    pause_empty_frames: int = 12

    # Font
    font_path: str = "assets/fonts/FiraCodeNerdFont-Regular.ttf"
    fit_min_size: int = 14
    fit_max_size: int = 42

    # Output. WebP rather than GIF, for one reason that matters: the panel has
    # rounded corners, and GIF's transparency is one bit, so the pixels outside
    # the curve can only be fully on or fully off. Saving as GIF meant dropping
    # the alpha channel, which left a black square behind every corner. WebP
    # carries real alpha, so the corners sit on whatever colour the page uses.
    #
    # Lossless is also the smaller file here, which looks backwards until you
    # remember this is flat text on a flat panel: lossy adds noise, and noise is
    # exactly what kills the frame-to-frame compression.
    out_path: str = "assets/terminal.webp"
    loop: int = 0
    supersample: int = 4  # the panel is drawn this much larger, then reduced
    duration_ms: Optional[int] = None  # if None -> 1000 / fps

    # Determinism
    seed: int = 137

    def scaled(self) -> "Config":
        """Return this config with every pixel measurement multiplied by scale."""
        s = self.scale
        if s == 1:
            return self
        return replace(
            self,
            size=(self.size[0] * s, self.size[1] * s),
            padding_x=self.padding_x * s,
            radius=self.radius * s,
            fit_min_size=self.fit_min_size * s,
            fit_max_size=self.fit_max_size * s,
            glitch_intensity=self.glitch_intensity * s,
            scale=1,
        )


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

    Drawn at cfg.supersample times the final size and then reduced, because
    PIL's rounded_rectangle barely antialiases: straight from the draw call the
    corner had a single intermediate alpha step, which reads as a staircase.

    Returns an RGBA image used as the base layer for each frame.
    """
    w, h = cfg.size
    s = max(1, cfg.supersample)
    img = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    d.rounded_rectangle(
        [0, 0, w * s - 1, h * s - 1],
        radius=cfg.radius * s,
        fill=cfg.bg,
        outline=cfg.border,
        width=2 * s,
    )
    d.rounded_rectangle(
        [2 * s, 2 * s, w * s - 3 * s, h * s - 3 * s],
        radius=(cfg.radius - 2) * s,
        outline=(255, 255, 255, 28),
        width=1 * s,
    )
    return img.resize((w, h), Image.LANCZOS) if s > 1 else img


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


def build_sequence(
    text: str, pause_full_frames: int, pause_empty_frames: int,
    type_step: int = 1, erase_step: int = 1,
) -> List[int]:
    """
    Build the per-frame text-length sequence:
      - forward range: 0 to len(text), type_step characters at a time
      - hold full text (pause_full_frames)
      - delete backward to 0, erase_step characters at a time
      - hold empty (pause_empty_frames)
    """
    l = len(text)
    forward = list(range(0, l + 1, type_step))
    if forward[-1] != l:
        forward.append(l)
    pause_full = [l] * pause_full_frames
    backward = list(range(l - 1, -1, -erase_step))
    pause_empty = [0] * pause_empty_frames
    return forward + pause_full + backward + pause_empty


def render(cfg: Config) -> str:
    """
    Render the animated header and write it to cfg.out_path.

    Returns:
        Output path of the generated file.
    """
    cfg = cfg.scaled()

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
    sequence = build_sequence(
        cfg.text, pause_full_frames, cfg.pause_empty_frames,
        cfg.type_step, cfg.erase_step,
    )

    typing_end = len(range(0, len(cfg.text) + 1, cfg.type_step))
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

    # Straight to WebP, keeping every frame in RGBA. There is no quantisation
    # step and no master palette any more: both existed to survive GIF's 256
    # colours, and both are what forced the alpha channel to be thrown away.
    frames_rgba[0].save(
        cfg.out_path,
        format="WEBP",
        save_all=True,
        append_images=frames_rgba[1:],
        loop=cfg.loop,
        duration=frame_ms,
        lossless=True,
        method=6,
        exact=True,  # do not touch RGB under transparent pixels
    )
    return cfg.out_path


if __name__ == "__main__":
    config = Config()
    path = render(config)
    print("Header saved at", path)
