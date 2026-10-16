"""Render a student "copy" page photo (PIL) for the Annoter written viewer.

Produces a realistic-looking page: white paper, horizontal ruling, a red left
margin line, and the student's text in an informal font, with a slight photo
vignette + rotation so it reads as a photographed copy (not a plain text box).
Returns the rendered PIL image + the list of (line_text, y_px) so the caller can
cross-check against ocr_page().
"""
import random
from PIL import Image, ImageDraw, ImageFont, ImageFilter

COMIC = "/usr/share/fonts/opentype/comic-neue/ComicNeue-Regular.otf"
COMIC_B = "/usr/share/fonts/opentype/comic-neue/ComicNeue-Bold.otf"

PAGE_W = 1000
LINE_SPACING = 64          # vertical gap between baseline lines
LEFT_MARGIN = 150          # ruling start x (red margin line just left of this)
RIGHT_MARGIN = 60          # keep ink well inside the right edge (avoid truncation)
TOP_PAD = 150


def _font(size):
    return ImageFont.truetype(COMIC, size)


def wrap(text: str, font, max_width: int) -> list[str]:
    """Greedy word wrap to fit max_width pixels."""
    words = text.split(" ")
    lines, cur = [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if font.getlength(trial) <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def render_page(text: str, rng: random.Random, title: str = "",
                font_size: int = 30) -> tuple[Image.Image, list[dict]]:
    """Return (image, meta). meta lines have y-center for the OCR cross-check.

    The text is word-wrapped onto physical lines; each physical line is drawn on
    its own ruling row.
    """
    font = _font(font_size)
    max_w = PAGE_W - LEFT_MARGIN - RIGHT_MARGIN
    physical = wrap(text, font, max_w)
    if title:
        bfont = _font(font_size + 6)
        physical = [title] + physical
        has_title = True
    else:
        has_title = False

    n_lines = len(physical)
    PAGE_H = TOP_PAD + n_lines * LINE_SPACING + 90
    img = Image.new("RGB", (PAGE_W, PAGE_H), (255, 255, 255))
    d = ImageDraw.Draw(img)

    # horizontal ruling
    rule_color = (205, 214, 224)
    row_y = TOP_PAD
    for i in range(n_lines + 3):
        d.line([(LEFT_MARGIN - 90, row_y), (PAGE_W - 40, row_y)],
               fill=rule_color, width=1)
        row_y += LINE_SPACING
    # red left margin line
    d.line([(LEFT_MARGIN - 90, 40), (LEFT_MARGIN - 90, PAGE_H - 40)],
           fill=(214, 150, 150), width=2)

    # ink color: dark blue ballpoint
    ink = (20, 30, 95)
    line_meta = []
    y = TOP_PAD
    for i, ln in enumerate(physical):
        jx = rng.randint(-3, 3)          # tiny x jitter (hand feel)
        jy = rng.randint(-3, 3)
        use_font = bfont if False else font
        if has_title and i == 0:
            use_font = bfont
            ink = (15, 20, 80)
        d.text((LEFT_MARGIN + jx, y + jy), ln, font=use_font, fill=ink)
        line_meta.append({"i": i, "text": ln, "y": y + font_size // 2})
        y += LINE_SPACING

    # light photo vignette + soft shadow at edges to feel like a scan/photo
    # NOTE: keep this VERY gentle — a heavy vignette/blur/rotation washes out
    # the ink and Tesseract loses the lines entirely (verified: blank page).
    # A slight paper tint + edge shadow only; no blur, no rotation.
    edge = Image.new("RGB", (PAGE_W, PAGE_H), (240, 240, 236))
    mask = Image.new("L", (PAGE_W, PAGE_H), 0)
    md = ImageDraw.Draw(mask)
    # interior (where text is) = white(255) -> keep `img`; only the outermost
    # rim fades to the slightly darker `edge` colour.
    md.rectangle([24, 24, PAGE_W - 24, PAGE_H - 24], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(30))
    img = Image.composite(img, edge, mask)
    return img, line_meta


if __name__ == "__main__":
    import sys
    rng = random.Random(7)
    txt = ("Le texte, « Les réseaux et nous », oppose les avantages et les "
           "inconvénients du numérique à l'école. L'auteur adopte un ton nuancé : "
           "il cite les risques (dépendance, distraction) mais aussi les "
           "bénéfices (accès à l'information, collaboration). Sa thèse finale est "
           "que le numérique doit être encadré.")
    img, meta = render_page(txt, rng, title="Étude de texte — 2G1")
    out = "/tmp/sample_page.png"
    img.save(out)
    print("saved", out, img.size)
    for m in meta:
        print(f"  L{m['i']}: {m['text'][:60]}")
