"""Compose PNG and editable SVG from the same slide layout."""

from base64 import b64encode
from functools import lru_cache
from html import escape
from io import BytesIO
from math import pi, sin
from pathlib import Path
import os

from PIL import Image, ImageColor, ImageDraw, ImageFont, ImageOps


WIDTH = 1080
HEIGHTS = (1080, 1350, 1440)
LAYOUTS = ("editorial", "photo", "panorama")
FONT_DEFAULT = "System Sans"
MARGIN = 84


@lru_cache(maxsize=96)
def load_font(path, size, bold):
    if path:
        return ImageFont.truetype(str(path), size)
    windows = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    mac = Path("/System/Library/Fonts/Supplemental")
    arial = "arialbd.ttf" if bold else "arial.ttf"
    for candidate in (
        windows / arial,
        mac / ("Arial Bold.ttf" if bold else "Arial.ttf"),
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "LiberationSans-Bold.ttf" if bold else "LiberationSans-Regular.ttf",
    ):
        try:
            return ImageFont.truetype(str(candidate), size)
        except OSError:
            continue
    raise ValueError("Brak fontu systemowego Arial, DejaVu Sans lub Liberation Sans. Dodaj jeden z nich albo wskaż plik fontu marki.")


def luminance(color):
    values = [value / 255 for value in ImageColor.getrgb(color)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in values]
    return sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


def contrast(first, second):
    low, high = sorted((luminance(first), luminance(second)))
    return (high + 0.05) / (low + 0.05)


def wrap(text, font, width):
    lines = []
    for paragraph in text.splitlines():
        line = ""
        for word in paragraph.split():
            if font.getlength(word) > width:
                return None
            candidate = f"{line} {word}".strip()
            if font.getlength(candidate) > width:
                lines.append(line)
                line = word
            else:
                line = candidate
        lines.append(line)
    return lines


class Artwork:
    def __init__(self, height, background):
        self.height = height
        self.image = Image.new("RGB", (WIDTH, height), background)
        self.draw = ImageDraw.Draw(self.image)
        self.svg = [f'<rect width="{WIDTH}" height="{height}" fill="{background}"/>']

    def rectangle(self, box, fill):
        x, y, width, height = box
        self.draw.rectangle((x, y, x + width - 1, y + height - 1), fill=fill)
        self.svg.append(f'<rect x="{x}" y="{y}" width="{width}" height="{height}" fill="{fill}"/>')

    def line(self, points, fill, stroke=2):
        self.draw.line(points, fill=fill, width=stroke, joint="curve")
        coordinates = " ".join(f"{x},{y}" for x, y in points)
        self.svg.append(f'<polyline points="{coordinates}" fill="none" stroke="{fill}" stroke-width="{stroke}"/>')

    def text(self, text, box, fill, font_path=None, bold=False, size=40, minimum=32):
        x, y, width, height = box
        for font_size in range(size, minimum - 1, -1):
            font = load_font(font_path, font_size, bold)
            lines = wrap(text, font, width)
            leading = round(font_size * 1.22)
            ascent, descent = font.getmetrics()
            if lines and ascent + descent + (len(lines) - 1) * leading <= height:
                break
        else:
            raise ValueError(f"Tekst nie mieści się w układzie. Skróć go: {text[:80]}")
        family, variant = font.getname()
        weight = 700 if "bold" in variant.lower() else 400
        slant = ' font-style="italic"' if any(word in variant.lower() for word in ("italic", "oblique")) else ""
        for index, line in enumerate(lines):
            baseline = y + ascent + index * leading
            self.draw.text((x, baseline), line, font=font, fill=fill, anchor="ls")
            self.svg.append(
                f'<text x="{x}" y="{baseline}" fill="{fill}" font-family="{escape(family)}" '
                f'font-size="{font_size}" font-weight="{weight}"{slant}>{escape(line)}</text>'
            )

    def picture(self, path, box, crop):
        x, y, width, height = box
        with Image.open(path) as original:
            if original.format not in {"PNG", "JPEG", "WEBP"} or getattr(original, "is_animated", False):
                raise ValueError("Zdjęcie lub logo musi być statycznym plikiem PNG, JPEG albo WebP.")
            prepared = ImageOps.exif_transpose(original).convert("RGBA")
        if crop:
            prepared = ImageOps.fit(prepared, (width, height), Image.Resampling.LANCZOS, centering=crop)
        else:
            prepared.thumbnail((width, height), Image.Resampling.LANCZOS)
            y += (height - prepared.height) // 2
        self.image.paste(prepared, (x, y), prepared)
        image_file = BytesIO()
        prepared.save(image_file, format="PNG")
        encoded = b64encode(image_file.getvalue()).decode("ascii")
        self.svg.append(
            f'<image x="{x}" y="{y}" width="{prepared.width}" height="{prepared.height}" '
            f'href="data:image/png;base64,{encoded}"/>'
        )

    def save(self, png, svg):
        self.image.save(png)
        markup = "\n".join(self.svg)
        svg.write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{self.height}" '
            f'viewBox="0 0 {WIDTH} {self.height}">\n{markup}\n</svg>\n',
            encoding="utf-8",
        )


def panorama_path(art, index, count, accent):
    start = index * WIDTH
    path = [
        (x, round(art.height - 212 + 58 * sin(2 * pi * (start + x) / (count * WIDTH) - pi / 3)))
        for x in range(-8, WIDTH + 9)
    ]
    art.line(path, accent, 8)
    art.line([(x, y + 27) for x, y in path], accent, 2)


def compose(brand, style, slide, index, count, paths):
    height = style["canvas"]["height"]
    colors = style["color_roles"]
    paper, ink, accent = (colors[role] for role in ("background", "text", "accent"))
    layout = style["layout"]
    dark = layout == "editorial" and slide["role"] in {"hook", "cta"}
    background, foreground = (ink, paper) if dark else (paper, ink)
    mark = accent if contrast(accent, background) >= 1.5 else foreground
    art = Artwork(height, background)
    inner = WIDTH - 2 * MARGIN
    heading_font, body_font = paths["heading_font"], paths["body_font"]
    art.line([(MARGIN, 163), (WIDTH - MARGIN, 163)], foreground)
    art.rectangle((MARGIN, 163, 112, 7), mark)
    if paths["logo"]:
        art.picture(paths["logo"], (MARGIN, MARGIN, 240, 58), crop=None)
    else:
        art.text(brand["name"], (MARGIN, MARGIN, inner - 170, 56), foreground, body_font, size=29, minimum=22)
    art.text(f"{index + 1:02d} / {count:02d}", (WIDTH - MARGIN - 120, MARGIN, 120, 52), foreground, size=27, minimum=23)

    if paths["photo"]:
        image_height = round(height * 0.34)
        art.picture(paths["photo"], (MARGIN, 190, inner, image_height), slide["crop"])
        title_top = 190 + image_height + 35
        title_height = round(height * 0.18)
        body_end = height - 130
    else:
        title_top = round(height * 0.205)
        title_height = round(height * 0.29)
        body_end = height - (315 if layout == "panorama" else 240)

    art.text(slide["headline"], (MARGIN, title_top, inner, title_height), foreground, heading_font,
             bold=True, size=93 if slide["role"] == "hook" and not paths["photo"] else 77, minimum=56)
    if slide["body"]:
        body_top = title_top + title_height + 14
        art.text(slide["body"], (MARGIN, body_top, inner - 22, body_end - body_top), foreground, body_font,
                 size=46, minimum=34)

    if layout == "panorama":
        panorama_path(art, index, count, mark)
    elif not paths["photo"]:
        art.rectangle((MARGIN, height - 206, 156, 10), mark)
        art.rectangle((MARGIN, height - 177, 104, 4), foreground)
    if index < count - 1:
        x, y = WIDTH - MARGIN - 64, height - MARGIN - 20
        art.line([(x, y), (x + 60, y)], foreground, 4)
        art.line([(x + 41, y - 17), (x + 60, y), (x + 41, y + 17)], foreground, 4)
    return art


def contact_sheet(files, destination):
    columns = min(len(files), 5)
    rows = (len(files) + columns - 1) // columns
    with Image.open(files[0]) as first:
        thumb_size = (252, round(252 * first.height / first.width))
    gap = 14
    cell_width, cell_height = (size + gap for size in thumb_size)
    sheet = Image.new("RGB", (columns * cell_width + gap, rows * cell_height + gap), "#deddd9")
    for index, file in enumerate(files):
        with Image.open(file) as slide:
            slide.thumbnail(thumb_size, Image.Resampling.LANCZOS)
            sheet.paste(slide, (gap + index % columns * cell_width, gap + index // columns * cell_height))
    sheet.save(destination)
