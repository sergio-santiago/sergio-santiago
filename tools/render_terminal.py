from __future__ import annotations

from dataclasses import dataclass, replace
from typing import List, Optional, Tuple
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont
import math
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
    size: Tuple[int, int] = (900, 75)
    # Keeps the panel off the canvas edge. Its border used to sit on the very
    # first and last rows, so any downscale by the browser could resample them
    # away and leave the panel looking cropped along the bottom.
    margin: int = 2
    padding_x: int = 32
    radius: int = 18
    bg: Tuple[int, int, int] = (24, 24, 26)
    border: Tuple[int, int, int] = (70, 74, 82)

    # Text content & colors
    prompt: str = "sergio-santiago  "  # a real shell prompt names its user
    # && rather than |: a pipe only wires stdout to stdin, so it would ship
    # whether or not the tests passed. This line is true if you run it.
    text: str = "solve --deterministic && test && ship"
    color_main: Tuple[int, int, int, int] = (60, 255, 120, 255)
    color_red: Tuple[int, int, int, int] = (255, 60, 100, 200)
    color_blue: Tuple[int, int, int, int] = (110, 200, 255, 200)

    # Window chrome: the three macOS traffic lights, and the room they need
    # before the prompt starts.
    dots: Tuple[Tuple[int, int, int], ...] = (
        (255, 95, 86),   # close
        (255, 189, 46),  # minimise
        (39, 201, 63),   # zoom
    )
    dot_radius: int = 8
    dot_gap: int = 13
    left_gutter: int = 100

    # How the panel catches light. See _light_from_above() and _sheen().
    top_light: int = 26              # peak alpha of the wash, at the top edge
    top_light_falloff: float = 0.55  # fraction of the height it fades over
    rim_light: int = 110             # alpha of the lit top edge
    sheen: int = 20                  # alpha of the diagonal highlight
    sheen_x: int = 430               # where it rests, clear of the traffic lights
    sheen_width: int = 130
    sheen_blur: int = 20

    # The reflection can drift the whole way round the glass and settle back
    # where it started, once per loop, while the line rests. It is the only
    # thing besides the text that moves, and moving is what costs bytes here,
    # so it is bounded on purpose. See _sheen_drift().
    sheen_steps: int = 30            # distinct positions along the drift, 0 parks it
    sheen_hold: int = 3              # frames each position is held for
    sheen_delay: int = 12            # frames of stillness before it sets off
    sheen_span: int = 0              # how far it drifts and back, 0 goes all the way round

    # Glitch effect
    glitch_intensity: int = 1  # base pixel offset for RGB glitch layers

    # Cursor. The gap is a little air between the last character and the block,
    # the way a terminal cell leaves some: butted straight up against the text it
    # reads as part of the word rather than as a caret waiting for the next one.
    cursor_char: str = "▋"
    cursor_blink_frames: int = 10
    cursor_gap: int = 5

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
    # Lossless was once the smaller file too, back when nothing on the panel
    # moved. It is not any more: with the reflection travelling, quality 90 comes
    # out 185 KB lighter. It also puts noise right where the glyphs meet the
    # background, and rendering at 2x was all about keeping those edges clean, so
    # the 185 KB is the price of being consistent about it.
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
            margin=self.margin * s,
            padding_x=self.padding_x * s,
            radius=self.radius * s,
            fit_min_size=self.fit_min_size * s,
            fit_max_size=self.fit_max_size * s,
            glitch_intensity=self.glitch_intensity * s,
            dot_radius=self.dot_radius * s,
            dot_gap=self.dot_gap * s,
            left_gutter=self.left_gutter * s,
            sheen_x=self.sheen_x * s,
            sheen_width=self.sheen_width * s,
            sheen_blur=self.sheen_blur * s,
            sheen_span=self.sheen_span * s,
            cursor_gap=self.cursor_gap * s,
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
    Binary-search the largest font size such that the whole line fits in max_width.

    The cursor counts. It used to fit by accident, on the back of three trailing
    spaces in the message, which also left it stranded three characters past the
    last word once the line was fully typed.

    This keeps the layout stable regardless of the chosen message.
    """
    lo, hi = cfg.fit_min_size, cfg.fit_max_size
    best = lo
    scratch = Image.new("RGB", (1, 1))
    d = ImageDraw.Draw(scratch)

    while lo <= hi:
        mid = (lo + hi) // 2
        f = load_font(mid, cfg)
        w = d.textlength(cfg.prompt + cfg.text + cfg.cursor_char, font=f) + cfg.cursor_gap
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

    # Centre the ink, not the line box. getbbox returns offsets measured from the
    # ascender line, which is also what d.text() takes as its origin, so the two
    # have to be combined rather than subtracted from each other: doing the
    # latter left the text nine pixels below the panel's centre, and next to the
    # traffic lights, which really are centred, it read as the dots being off.
    #
    # Measured on the full string so the baseline holds steady while it types.
    top, bottom = font.getbbox(cfg.prompt + cfg.text + cfg.cursor_char)[1::2]
    baseline_y = int((h - (top + bottom)) // 2)

    return w_prompt, baseline_y


def draw_box(cfg: Config) -> Image.Image:
    """
    Draw the panel: rounded, edged and lit from above, but with no reflection.

    Everything here is drawn at cfg.supersample times the final size and then
    reduced, because PIL antialiases almost nothing. Straight from the draw call
    the corner had a single intermediate alpha step and read as a staircase, and
    the three traffic lights were worse.

    None of it ever changes, which is the whole reason it can afford to be this
    involved, and it is why the reflection is added afterwards rather than here:
    that one can move. See _sheen_drift().

    Returns an RGBA image used as the base layer for each frame.
    """
    w, h = cfg.size
    s = max(1, cfg.supersample)
    img = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # The border first and all the way round, so the panel always has an edge.
    # The rim light goes on top of it: it fades to a tenth of its strength at the
    # bottom, so on its own the panel looked cut off down there.
    mg = cfg.margin * s
    bounds = [mg, mg, w * s - 1 - mg, h * s - 1 - mg]
    d.rounded_rectangle(
        bounds, radius=cfg.radius * s, fill=cfg.bg, outline=cfg.border, width=2 * s
    )
    img = Image.alpha_composite(img, _rim(img.size, bounds, cfg, s))
    d = ImageDraw.Draw(img)

    r, cy = cfg.dot_radius * s, (h * s) // 2
    step = (2 * cfg.dot_radius + cfg.dot_gap) * s
    for i, colour in enumerate(cfg.dots):
        cx = cfg.padding_x * s + r + i * step
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=colour + (255,))

    img = img.resize((w, h), Image.LANCZOS) if s > 1 else img
    return _light_from_above(img, cfg)


def _rim(size: tuple[int, int], bounds: list[int], cfg: Config, s: int) -> Image.Image:
    """
    Trace the edge once and fade it downwards, bright on top and faint below.

    The first version drew two rounded rectangles, the second one three pixels
    tall with an eighteen pixel radius. PIL cannot round a box shorter than its
    own corners, so it laid the top edge of that box down as a straight line
    running the full width of the canvas, straight through the transparent
    corners. It showed up as a stray line under the panel.
    """
    rim = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(rim).rounded_rectangle(
        bounds, radius=cfg.radius * s, outline=(255, 255, 255, 255), width=2 * s
    )

    height = size[1]
    top, bottom = cfg.rim_light, cfg.rim_light // 4
    fade = Image.new("L", (1, height))
    for y in range(height):
        fade.putpixel((0, y), int(top + (bottom - top) * y / height))

    rim.putalpha(ImageChops.multiply(rim.split()[3], fade.resize(size)))
    return rim


def _streak(panel: Image.Image, x: int, cfg: Config) -> Image.Image:
    """
    Lay the soft diagonal band of light over the panel and clip it to the glass.

    The band leans by exactly the panel height, so it reads as one plane of light
    crossing at 45 degrees rather than as a vertical bar.
    """
    w, h = panel.size
    streak = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(streak).polygon(
        [(x, 0), (x + cfg.sheen_width, 0), (x + cfg.sheen_width - h, h), (x - h, h)],
        fill=(255, 255, 255, cfg.sheen),
    )
    streak = streak.filter(ImageFilter.GaussianBlur(cfg.sheen_blur))
    streak.putalpha(
        Image.composite(streak.split()[3], Image.new("L", (w, h), 0), panel.split()[3])
    )
    return Image.alpha_composite(panel, streak)


def _sheen_period(panel: Image.Image, cfg: Config) -> int:
    """
    The distance the reflection travels to come back to where it started.

    Panel width plus the band's own lean plus its width: everything it needs to
    leave by one edge and arrive at the other with nothing showing in between.
    """
    return panel.size[0] + panel.size[1] + cfg.sheen_width


def _sheen(panel: Image.Image, cfg: Config, offset: int = 0) -> Image.Image:
    """
    Place the reflection, offset pixels along from its resting position.

    Kept clear of the traffic lights when parked: the first attempt put it right
    over them and it looked like a smudge rather than a reflection.

    Two bands are laid down, one period apart, so that whatever leaves by the
    right edge is already arriving at the left one. Only one of them is ever over
    the glass, and at offset zero the other is well off the canvas, which is why
    a parked reflection costs exactly what it always did.
    """
    if not cfg.sheen:
        return panel

    period = _sheen_period(panel, cfg)
    for x in (cfg.sheen_x + offset, cfg.sheen_x + offset - period):
        panel = _streak(panel, x, cfg)
    return panel


def _sheen_drift(panel: Image.Image, cfg: Config) -> List[Image.Image]:
    """
    Pre-render the reflection's round trip, one panel per position.

    Takes the panel without a reflection and returns it with one, moved a little
    further along each time. This is the expensive half of the header, and the
    only thing besides the text that changes between frames, so it is bounded on
    purpose: it runs during the rest pause and nowhere else. While the line is
    typing there is already something to look at, and a highlight moving under
    changing text is the worst case there is for inter-frame compression, because
    the two changed regions never coincide.

    The travel is eased at both ends. Light on a surface does not start and stop
    at full speed, and a linear pass reads as a wipe rather than a reflection.
    The easing also means the drift is at its slowest right where it hands back
    to the parked panel, so the two meet without a visible step.

    What the budget really buys is positions, not distance: every distinct one is
    a frame the encoder has to spend around ten kilobytes on, whether the band
    moved a hundred pixels or ten. That is why sheen_span exists. Going all the
    way round is twenty two hundred pixels, and covering that smoothly needs more
    positions than the file can afford, so the alternative is a shorter drift out
    and back, which the same number of positions can cover without stepping.
    """
    if not cfg.sheen or cfg.sheen_steps <= 0:
        return []

    if cfg.sheen_span:
        # Out and back. A cosine turns around smoothly at both ends and returns
        # to exactly zero, so the loop closes on the parked panel by itself.
        offsets = [
            int(cfg.sheen_span * (1 - math.cos(2 * math.pi * i / cfg.sheen_steps)) / 2)
            for i in range(cfg.sheen_steps)
        ]
    else:
        # All the way round, smoothstepped. Deliberately not steps - 1: the last
        # position stops just short of home, because home is the frame the
        # animation returns to on its own.
        period = _sheen_period(panel, cfg)
        offsets = [
            int(period * (t * t * (3 - 2 * t)))
            for t in (i / cfg.sheen_steps for i in range(cfg.sheen_steps))
        ]

    return [_sheen(panel, cfg, off) for off in offsets]


def _light_from_above(panel: Image.Image, cfg: Config) -> Image.Image:
    """
    Wash a little light across the top of the panel so it reads as lit, not flat.

    Deliberately the only glow in here. A halo around the text was the obvious
    idea and it was the wrong one: it grows as the line types, so it differs on
    every frame, and inter-frame compression collapsed. That cost 151 KB for
    something invisible at display size. This is drawn once into the panel and
    never changes, which costs 27 KB for the whole animation.
    """
    if not cfg.top_light:
        return panel

    w, h = panel.size
    fade = max(1.0, h * cfg.top_light_falloff)
    column = Image.new("L", (1, h))
    for y in range(h):
        column.putpixel((0, y), int(cfg.top_light * max(0.0, 1 - y / fade)))

    wash = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    wash.putalpha(
        Image.composite(column.resize((w, h)), Image.new("L", (w, h), 0), panel.split()[3])
    )
    return Image.alpha_composite(panel, wash)


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

    x = cfg.padding_x + cfg.left_gutter
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
        d.text(
            (x + prompt_w + w_typed + cfg.cursor_gap, y),
            cfg.cursor_char, font=font, fill=cfg.color_main,
        )

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


def build_frames(cfg: Config) -> List[Image.Image]:
    """
    Render every frame of the animation as RGBA, in order.

    Expects an already-scaled config.
    """
    pause_full_frames = int(cfg.fps * cfg.pause_final_seconds)

    # Resources
    w, _ = cfg.size
    font = pick_font_for_width(w - 2 * cfg.padding_x - cfg.left_gutter, cfg)
    prompt_w, baseline_y = compute_metrics(font, cfg)
    bare = draw_box(cfg)
    panel = _sheen(bare, cfg)          # the reflection at rest
    drift = _sheen_drift(bare, cfg)    # and every position of its round trip

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

        # The highlight only travels while the line rests, so most frames still
        # share the one panel that was drawn up front.
        # Every distinct position is a frame the encoder cannot share with its
        # neighbour, so holding each one for a couple of frames buys back most of
        # the cost without making the trip any quicker.
        since = i - typing_end - cfg.sheen_delay
        step = since // max(1, cfg.sheen_hold)
        base = (
            drift[step]
            if in_pause_full and since >= 0 and step < len(drift)
            else panel
        )

        fr_rgba = draw_text_frame(
            base, typed, cursor_on, red_off, blue_off, font, prompt_w, baseline_y, cfg
        )
        frames_rgba.append(fr_rgba)

    return frames_rgba


def render(cfg: Config) -> str:
    """
    Render the animated header and write it to cfg.out_path.

    Returns:
        Output path of the generated file.
    """
    cfg = cfg.scaled()
    frames = build_frames(cfg)

    # Straight to WebP, keeping every frame in RGBA. There is no quantisation
    # step and no master palette any more: both existed to survive GIF's 256
    # colours, and both are what forced the alpha channel to be thrown away.
    #
    # kmin/kmax at zero tell libwebp never to insert a keyframe. Its default is
    # one every so often, and here every one of them is a full re-encode of a
    # panel that has not changed.
    frames[0].save(
        cfg.out_path,
        format="WEBP",
        save_all=True,
        append_images=frames[1:],
        loop=cfg.loop,
        duration=_frame_duration_ms(cfg),
        lossless=True,
        method=6,
        exact=True,  # do not touch RGB under transparent pixels
        minimize_size=True,
        kmin=0,
        kmax=0,
    )
    return cfg.out_path


if __name__ == "__main__":
    config = Config()
    path = render(config)
    print("Header saved at", path)
