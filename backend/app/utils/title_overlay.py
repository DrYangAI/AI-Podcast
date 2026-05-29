"""Generate title overlay PNG with rounded parallelogram background using Pillow."""

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


# macOS Chinese font paths (try in order)
_FONT_PATHS = [
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
]


def _get_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    for path in _FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _hex_to_rgba(hex_color: str, opacity: float = 1.0) -> tuple[int, int, int, int]:
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return (r, g, b, int(opacity * 255))


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Wrap text to fit within max_width, splitting at natural points."""
    if not text:
        return []

    # Try single line first
    bbox = font.getbbox(text)
    if bbox[2] - bbox[0] <= max_width:
        return [text]

    # Split into two lines at midpoint
    mid = len(text) // 2
    # Find a good split point near the middle
    best = mid
    for offset in range(min(mid, 8)):
        for pos in [mid + offset, mid - offset]:
            if 0 < pos < len(text):
                ch = text[pos]
                if ch in "，。、！？；：,.!?; ":
                    best = pos + 1
                    break
        else:
            continue
        break

    lines = [text[:best].strip(), text[best:].strip()]
    return [l for l in lines if l]


def _draw_rounded_parallelogram(
    draw: ImageDraw.ImageDraw,
    bounds: tuple[int, int, int, int],  # (x0, y0, x1, y1)
    skew_px: int,
    radius: int,
    fill: tuple[int, int, int, int],
):
    """Draw a rounded parallelogram.

    The shape is a parallelogram with the top-right and bottom-left corners
    shifted by skew_px, with rounded corners.
    """
    x0, y0, x1, y1 = bounds
    r = min(radius, (y1 - y0) // 2, (x1 - x0) // 4)

    if r < 2:
        # Fallback to simple polygon
        points = [
            (x0 + skew_px, y0),
            (x1, y0),
            (x1 - skew_px, y1),
            (x0, y1),
        ]
        draw.polygon(points, fill=fill)
        return

    # Draw the main body using a mask approach for clean rounded corners
    # Create a temporary image for the shape
    w = x1 - x0
    h = y1 - y0
    shape_img = Image.new("RGBA", (w + skew_px * 2, h), (0, 0, 0, 0))
    shape_draw = ImageDraw.Draw(shape_img)

    # Draw rounded rectangle first
    shape_draw.rounded_rectangle(
        [skew_px, 0, w + skew_px, h],
        radius=r,
        fill=fill,
    )

    # Apply skew transform (affine)
    if skew_px > 0:
        # Affine transform coefficients for skewX
        # x' = x + skew_factor * (h/2 - y), y' = y
        skew_factor = skew_px / (h / 2) if h > 0 else 0
        shape_img = shape_img.transform(
            shape_img.size,
            Image.AFFINE,
            (1, skew_factor, -skew_px, 0, 1, 0),
            resample=Image.BICUBIC,
        )

    # Paste onto draw's image
    draw._image.paste(shape_img, (x0, y0), shape_img)


def generate_title_overlay(
    title: str,
    sub_title: str | None = None,
    canvas_width: int = 1080,
    bg_color: str = "#FFD700",
    bg_opacity: float = 0.9,
    bg_shape: str = "parallelogram",
    bg_radius: int = 16,
    bg_skew: int = 10,
    title_font_size: int = 52,
    title_color: str = "#000000",
    title_outline_width: int = 0,
    title_outline_color: str = "#000000",
    sub_title_font_size: int = 24,
    sub_title_color: str = "#333333",
    padding: int = 30,
    output_path: Path | None = None,
) -> Image.Image:
    """Generate a title overlay PNG with rounded parallelogram background.

    Returns the PIL Image. If output_path is provided, also saves to disk.
    """
    title_font = _get_font(title_font_size, bold=True)
    sub_font = _get_font(sub_title_font_size, bold=False) if sub_title else None

    # Calculate text dimensions
    max_text_width = canvas_width - padding * 4  # leave margins
    title_lines = _wrap_text(title, title_font, max_text_width)

    line_height = title_font_size + 8
    title_block_h = line_height * len(title_lines)

    sub_lines: list[str] = []
    sub_line_height = 0
    if sub_title and sub_title.strip() and sub_font:
        sub_lines = _wrap_text(sub_title.strip(), sub_font, max_text_width)
        sub_line_height = sub_title_font_size + 6

    sub_block_h = sub_line_height * len(sub_lines)
    gap = 12 if sub_lines else 0

    # Total content height
    content_h = title_block_h + gap + sub_block_h
    bg_h = content_h + padding * 2

    # Calculate max text width for background sizing
    max_line_w = 0
    for line in title_lines:
        bbox = title_font.getbbox(line)
        max_line_w = max(max_line_w, bbox[2] - bbox[0])
    for line in sub_lines:
        if sub_font:
            bbox = sub_font.getbbox(line)
            max_line_w = max(max_line_w, bbox[2] - bbox[0])

    bg_w = max_line_w + padding * 2
    skew_px = int(bg_h * math.tan(math.radians(bg_skew))) if bg_shape == "parallelogram" else 0

    # Canvas size (enough room for skew)
    img_w = bg_w + skew_px * 2 + 40
    img_h = bg_h + 20

    img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background shape position (centered)
    bg_x0 = (img_w - bg_w) // 2
    bg_y0 = 10
    bg_x1 = bg_x0 + bg_w
    bg_y1 = bg_y0 + bg_h

    fill_color = _hex_to_rgba(bg_color, bg_opacity)

    if bg_shape == "parallelogram" and skew_px > 0:
        _draw_rounded_parallelogram(draw, (bg_x0, bg_y0, bg_x1, bg_y1), skew_px, bg_radius, fill_color)
    else:
        draw.rounded_rectangle([bg_x0, bg_y0, bg_x1, bg_y1], radius=bg_radius, fill=fill_color)

    # Draw title text (centered in background)
    text_y = bg_y0 + padding
    for line in title_lines:
        bbox = title_font.getbbox(line)
        line_w = bbox[2] - bbox[0]
        text_x = (img_w - line_w) // 2

        # Outline (draw text in outline color slightly offset in all directions)
        if title_outline_width > 0:
            ow = title_outline_width
            oc = _hex_to_rgba(title_outline_color)
            for dx in range(-ow, ow + 1):
                for dy in range(-ow, ow + 1):
                    if dx == 0 and dy == 0:
                        continue
                    draw.text((text_x + dx, text_y + dy), line, font=title_font, fill=oc)

        draw.text((text_x, text_y), line, font=title_font, fill=_hex_to_rgba(title_color))
        text_y += line_height

    # Draw subtitle
    if sub_lines and sub_font:
        text_y += gap
        for line in sub_lines:
            bbox = sub_font.getbbox(line)
            line_w = bbox[2] - bbox[0]
            text_x = (img_w - line_w) // 2
            draw.text((text_x, text_y), line, font=sub_font, fill=_hex_to_rgba(sub_title_color))
            text_y += sub_line_height

    # Crop to content bounds (remove excess transparent area)
    bbox = img.getbbox()
    if bbox:
        img = img.crop(bbox)

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(output_path), "PNG")

    return img
