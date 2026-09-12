#!/usr/bin/env python3
"""Normalize an image to a standard Omarchy wallpaper resolution.

Resizes any input image (PNG/JPEG/WebP...) to one of the standard resolutions
using a cover-fit crop (scale to fill, then center-crop), never letterboxing or
stretching, and saves it as lossy WebP (q85). The output is written atomically
and verified: it is re-opened, checked for the exact target size and a non-zero
byte count.

The resolution is the third positional argument ("2K", "4K" or "8K"); when it
is omitted it is inferred from the output filename suffix (e.g.
"omarchy-country-IT-Italy-4K.webp") and finally falls back to 2K.

Usage:
    python3 scripts/convert_image_size.py <input> <output> [2K|4K|8K]
"""

import argparse
import os
import re
import sys

from PIL import Image

RESOLUTIONS = {
    "2K": (2560, 1440),
    "4K": (3840, 2160),
    "8K": (7680, 4320),
}
DEFAULT_RESOLUTION = "2K"
QUALITY = 85
METHOD = 4

SUFFIX_RE = re.compile(r"-(2K|4K|8K)\.[^.]+$", re.IGNORECASE)


def resolve_resolution(output, resolution=None):
    """Return (label, (width, height)) for the requested output.

    An explicit resolution wins; otherwise it comes from the output filename
    suffix, and finally falls back to DEFAULT_RESOLUTION.
    """
    if resolution:
        label = resolution.upper()
        return label, RESOLUTIONS[label]
    match = SUFFIX_RE.search(os.path.basename(output))
    if match:
        label = match.group(1).upper()
        return label, RESOLUTIONS[label]
    return DEFAULT_RESOLUTION, RESOLUTIONS[DEFAULT_RESOLUTION]


def resize_cover(image, width, height):
    """Scale to fill width x height and center-crop, never letterbox."""
    src_w, src_h = image.size
    scale = max(width / src_w, height / src_h)
    new_w, new_h = round(src_w * scale), round(src_h * scale)
    resized = image.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - width) // 2
    top = (new_h - height) // 2
    return resized.crop((left, top, left + width, top + height))


def convert(input_path, output_path, resolution=None):
    label, (width, height) = resolve_resolution(output_path, resolution)
    image = Image.open(input_path).convert("RGB")
    result = resize_cover(image, width, height)

    corners = [
        result.getpixel((0, 0)),
        result.getpixel((width - 1, 0)),
        result.getpixel((0, height - 1)),
        result.getpixel((width - 1, height - 1)),
    ]

    tmp = output_path + ".tmp"
    try:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        result.save(tmp, "WEBP", quality=QUALITY, method=METHOD)
        check = Image.open(tmp)
        check.load()
        if check.size != (width, height):
            raise ValueError(f"written size {check.size} != {width}x{height}")
        size = os.path.getsize(tmp)
        if size <= 0:
            raise ValueError("written file is empty")
        os.replace(tmp, output_path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

    mtime = int(os.path.getmtime(output_path))
    black = sum(1 for corner in corners if corner == (0, 0, 0))
    warning = " corners=black!" if black else ""
    print(
        f"OK {output_path} {label} {width}x{height} {size} bytes "
        f"mtime={mtime}{warning}"
    )
    return size


def main():
    parser = argparse.ArgumentParser(
        description="Normalize an image to a standard Omarchy wallpaper resolution"
    )
    parser.add_argument("input", help="source image (any format)")
    parser.add_argument("output", help="destination WebP path")
    parser.add_argument(
        "resolution",
        nargs="?",
        choices=sorted(RESOLUTIONS),
        help="target resolution label (default: from output name, else 2K)",
    )
    args = parser.parse_args()

    try:
        convert(args.input, args.output, args.resolution)
    except Exception as exc:  # pragma: no cover
        print(f"ERR {args.output}: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
