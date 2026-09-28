#!/usr/bin/env python3
"""Tightly crop dark line art with a small protective margin; no robot access."""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageChops


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--threshold", type=int, default=150, help="dark-pixel threshold (0..255)")
    parser.add_argument("--margin", type=int, default=18, help="extra pixels around the detected ink")
    args = parser.parse_args()
    image = Image.open(args.input).convert("RGB")
    gray = image.convert("L")
    mask = gray.point(lambda value: 255 if value < args.threshold else 0)
    bounds = mask.getbbox()
    if bounds is None:
        raise SystemExit("no dark line art was found")
    left, top, right, bottom = bounds
    left, top = max(0, left - args.margin), max(0, top - args.margin)
    right, bottom = min(image.width, right + args.margin), min(image.height, bottom + args.margin)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    image.crop((left, top, right, bottom)).save(args.output)
    print(f"cropped {image.width}x{image.height} -> {right-left}x{bottom-top}: {args.output}")


if __name__ == "__main__":
    main()
