#!/usr/bin/env python3
"""Extract and preview a small, ordered detail-only subset from a reviewed plan."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw


def distance(a, b):
    return math.dist(a, b)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--x-max", type=float, required=True, help="keep paths entirely left of this local-paper X in mm")
    parser.add_argument("--min-length-mm", type=float, default=2.0)
    parser.add_argument("--max-length-mm", type=float, default=14.0)
    args = parser.parse_args()
    source = json.loads(args.input.expanduser().resolve().read_text(encoding="utf-8"))
    selected = [
        dict(stroke) for stroke in source["strokes"]
        if args.min_length_mm <= float(stroke["length_mm"]) <= args.max_length_mm
        and max(point[0] for point in stroke["points"]) <= args.x_max
    ]
    if not selected:
        raise SystemExit("no detail paths matched; adjust the selection bounds")

    # Order nearby independent details while allowing reversal of open paths.
    ordered, cursor = [], (source["canvas_mm"]["x"][0], source["canvas_mm"]["y"][0])
    while selected:
        choice = min(
            ((distance(cursor, item["points"][endpoint]), index, endpoint) for index, item in enumerate(selected) for endpoint in (0, -1)),
            key=lambda item: item[0],
        )
        travel, index, endpoint = choice
        item = selected.pop(index)
        if endpoint == -1:
            item["points"] = list(reversed(item["points"]))
        item["travel_from_previous_mm"] = round(travel, 3)
        item["order"] = len(ordered) + 1
        ordered.append(item)
        cursor = item["points"][-1]

    args.out.mkdir(parents=True, exist_ok=True)
    plan = {
        "source": str(args.input.expanduser().resolve()),
        "status": "preview_only_no_robot_motion",
        "canvas_mm": source["canvas_mm"],
        "filter": {"detail_only": True, "x_max_mm": args.x_max, "kept_paths": len(ordered)},
        "strokes": ordered,
    }
    (args.out / f"{args.name}_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    canvas = Image.new("RGB", (1200, 820), (255, 253, 248))
    draw = ImageDraw.Draw(canvas)
    for stroke in ordered:
        draw.line([(round(x * 6.4), round(y * 5.45)) for x, y in stroke["points"]], fill=(20, 20, 20), width=3, joint="curve")
    canvas.save(args.out / f"{args.name}_preview.png")
    print(json.dumps({"kept_paths": len(ordered), "draw_length_mm": round(sum(float(s["length_mm"]) for s in ordered), 1)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
