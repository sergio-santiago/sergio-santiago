from PIL import Image, ImageDraw, ImageFont
import random

# ===== Config =====
W, H = 460, 100
PADDING_X = 32
RADIUS = 18
BG = (24, 24, 26)
BORDER = (70, 74, 82)

PROMPT = "> "
TEXT = "Hi There, I'm Sergio Santiago!"
MAIN = (60, 255, 120, 255)
RED  = (255, 60, 100, 200)
BLUE = (110, 200, 255, 200)

CURSOR_CHAR = "▋"
FPS = 18
FRAME_MS = int(1000/FPS)
PAUSE_FINAL_SECONDS = 3.0
PAUSE_FULL_FRAMES = int(FPS * PAUSE_FINAL_SECONDS)
PAUSE_EMPTY_FRAMES = 8
CURSOR_BLINK_FRAMES = 6

# ===== Font =====
def load_font(size):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except:
            continue
    return ImageFont.load_default()

def pick_font_for_width(max_width):
    lo, hi = 14, 42
    best = lo
    while lo <= hi:
        mid = (lo+hi)//2
        f = load_font(mid)
        test_img = Image.new("RGB", (1,1))
        d = ImageDraw.Draw(test_img)
        w = d.textlength(PROMPT + TEXT, font=f)
        if w <= max_width:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return load_font(best)

font = pick_font_for_width(W - 2*PADDING_X)

# ===== Helpers =====
def draw_box() -> Image.Image:
    img = Image.new("RGBA", (W, H), (0,0,0,0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0,0,W-1,H-1], radius=RADIUS, fill=BG, outline=BORDER, width=2)
    d.rounded_rectangle([2,2,W-3,H-3], radius=RADIUS-2, outline=(255,255,255,28), width=1)
    return img

def draw_text(base, typed, cursor_on, red_off, blue_off):
    img = base.copy()
    d = ImageDraw.Draw(img)
    x = PADDING_X
    text_h = font.getbbox("Hg")[3] - font.getbbox("Hg")[1]
    y = (H - text_h)//2
    d.text((x, y), PROMPT, font=font, fill=MAIN)
    w_prompt = d.textlength(PROMPT, font=font)
    if red_off or blue_off:
        d.text((x + w_prompt + red_off,  y), typed, font=font, fill=RED)
        d.text((x + w_prompt + blue_off, y), typed, font=font, fill=BLUE)
    d.text((x + w_prompt, y), typed, font=font, fill=MAIN)
    if cursor_on:
        w_typed = d.textlength(typed, font=font)
        d.text((x + w_prompt + w_typed, y), CURSOR_CHAR, font=font, fill=MAIN)
    return img

# ===== Build sequence =====
frames = []
L = len(TEXT)
forward = list(range(L+1))
pause_full = [L]*PAUSE_FULL_FRAMES
backward = list(range(L-1, -1, -1))
pause_empty = [0]*PAUSE_EMPTY_FRAMES
sequence = forward + pause_full + backward + pause_empty

panel = draw_box()
random.seed(42)

for i, tlen in enumerate(sequence):
    typing_end = len(forward)
    pause_end = typing_end + len(pause_full)
    in_typing = i < typing_end
    in_pause_full = typing_end <= i < pause_end

    if in_pause_full:
        red_off, blue_off = 0, 0
    else:
        base_off = 2
        red_off  = base_off + random.choice([0,1,2])
        blue_off = -(base_off + random.choice([0,1,2]))

    cursor_on = ((i // CURSOR_BLINK_FRAMES) % 2 == 0)
    typed = TEXT[:tlen]
    frame = draw_text(panel, typed, cursor_on, red_off, blue_off)
    frames.append(frame.convert("P", palette=Image.Palette.ADAPTIVE, colors=64))

out_path = "./hi_terminal_prompt.gif"
frames[0].save(out_path, save_all=True, append_images=frames[1:], loop=0,
               duration=int(1000/FPS), optimize=True, disposal=2)

print("GIF saved at", out_path)
