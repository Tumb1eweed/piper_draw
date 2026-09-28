#!/usr/bin/env python3
"""Turn Trazor's raw centreline document into a reviewable Piper drawing plan.

No Piper SDK is imported here.  This script only filters, samples, maps and
orders geometry so that the user can approve the exact pen-down trajectories.
"""
from __future__ import annotations

import json
import math
import argparse
from pathlib import Path

from PIL import Image, ImageDraw

def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def cubic(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float], d: tuple[float, float]) -> list[tuple[float, float]]:
    steps = max(3, min(24, math.ceil((distance(a, b) + distance(b, c) + distance(c, d)) / 5)))
    points = []
    for index in range(1, steps + 1):
        t = index / steps
        u = 1 - t
        points.append((
            u**3 * a[0] + 3*u*u*t*b[0] + 3*u*t*t*c[0] + t**3*d[0],
            u**3 * a[1] + 3*u*u*t*b[1] + 3*u*t*t*c[1] + t**3*d[1],
        ))
    return points


def split_and_sample(commands: list[dict]) -> list[list[tuple[float, float]]]:
    """Expand Trazor M/L/C commands into separate continuous polylines."""
    paths: list[list[tuple[float, float]]] = []
    points: list[tuple[float, float]] = []
    current = (0.0, 0.0)
    for command in commands:
        kind = command["type"]
        if kind == "M":
            if len(points) > 1:
                paths.append(points)
            current = (float(command["x"]), float(command["y"]))
            points = [current]
        elif kind == "L":
            current = (float(command["x"]), float(command["y"]))
            points.append(current)
        elif kind == "C":
            end = (float(command["x"]), float(command["y"]))
            points.extend(cubic(current, (float(command["x1"]), float(command["y1"])), (float(command["x2"]), float(command["y2"])), end))
            current = end
        else:
            raise RuntimeError(f"unsupported curve command in centreline document: {kind}")
    if len(points) > 1:
        paths.append(points)
    return paths


def rdp(points: list[tuple[float, float]], epsilon: float = 1.25) -> list[tuple[float, float]]:
    if len(points) < 3:
        return points
    a, b = points[0], points[-1]
    vx, vy = b[0] - a[0], b[1] - a[1]
    denom = vx*vx + vy*vy
    farthest, index = -1.0, 0
    for i, point in enumerate(points[1:-1], 1):
        value = distance(a, point) if denom == 0 else abs(vx*(a[1]-point[1]) - (a[0]-point[0])*vy) / math.sqrt(denom)
        if value > farthest:
            farthest, index = value, i
    if farthest > epsilon:
        return rdp(points[:index+1], epsilon)[:-1] + rdp(points[index:], epsilon)
    return [a, b]


def path_length(points: list[tuple[float, float]]) -> float:
    return sum(distance(a, b) for a, b in zip(points, points[1:]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Trazor *.svg.document.json")
    parser.add_argument("--out", type=Path, required=True, help="output folder for plan and preview")
    parser.add_argument("--name", default="drawing", help="output file prefix")
    parser.add_argument("--x-min", type=float, default=15.0)
    parser.add_argument("--x-max", type=float, default=165.0)
    parser.add_argument("--y-min", type=float, default=15.0)
    parser.add_argument("--y-max", type=float, default=150.0)
    parser.add_argument("--min-length-mm", type=float, default=2.4)
    args = parser.parse_args()
    if args.x_max <= args.x_min or args.y_max <= args.y_min or args.min_length_mm <= 0:
        raise SystemExit("invalid canvas bounds or minimum length")
    source_path = args.source.expanduser().resolve()
    out = args.out.expanduser().resolve()
    x0, x1, y0, y1 = args.x_min, args.x_max, args.y_min, args.y_max
    source = json.loads(source_path.read_text(encoding="utf-8"))
    width, height = float(source["width"]), float(source["height"])
    sx, sy = (x1-x0)/width, (y1-y0)/height
    candidates: list[dict] = []
    for shape_index, shape in enumerate(source["shapes"]):
        for sub_index, raw in enumerate(split_and_sample(shape["commands"])):
            points = rdp(raw, 0.9)
            mapped = [(x0 + x*sx, y0 + y*sy) for x, y in points]
            # Reject a one-node graph fork that leaves the image boundary then
            # immediately returns to the same contour.  This is a known
            # skeletonisation artefact, not a drawable reference line.
            cleaned = [mapped[0]]
            for previous, point, following in zip(mapped, mapped[1:], mapped[2:]):
                outside = point[0] < x0 or point[0] > x1 or point[1] < y0 or point[1] > y1
                if outside and distance(previous, following) < 5.0:
                    continue
                cleaned.append(point)
            cleaned.append(mapped[-1])
            mapped = cleaned
            # A valid fitted path must remain inside the source image mapped
            # rectangle.  Retaining a component that still crosses an edge
            # after spike cleanup would create a visibly false long segment.
            if any(point[0] < x0 or point[0] > x1 or point[1] < y0 or point[1] > y1 for point in mapped):
                continue
            length = path_length(mapped)
            if length < args.min_length_mm:
                continue
            candidates.append({
                "id": f"shape-{shape_index:03d}-{sub_index}",
                "points": mapped,
                "length_mm": length,
                "source_stroke_px": float(shape.get("strokeWidth", 1.0)),
            })

    # Keep structure (long silhouette lines) before fine detail, then minimise
    # pen-up travel within each tier.  We may reverse an open path but never
    # join unrelated path endpoints.
    long = [item for item in candidates if item["length_mm"] >= 12.0]
    detail = [item for item in candidates if item["length_mm"] < 12.0]
    ordered: list[dict] = []
    cursor = (x0, y0)
    for tier in (long, detail):
        remaining = list(tier)
        while remaining:
            best_index, reverse, best_distance = 0, False, float("inf")
            for index, item in enumerate(remaining):
                first, last = item["points"][0], item["points"][-1]
                for should_reverse, endpoint in ((False, first), (True, last)):
                    candidate_distance = distance(cursor, endpoint)
                    if candidate_distance < best_distance:
                        best_index, reverse, best_distance = index, should_reverse, candidate_distance
            item = remaining.pop(best_index)
            if reverse:
                item["points"] = list(reversed(item["points"]))
            item["travel_from_previous_mm"] = round(best_distance, 3)
            ordered.append(item)
            cursor = item["points"][-1]

    out.mkdir(parents=True, exist_ok=True)
    plan = {
        "source": str(source_path),
        "status": "preview_only_no_robot_motion",
        "canvas_mm": {"x": [x0, x1], "y": [y0, y1]},
        "filter": {"minimum_path_length_mm": args.min_length_mm, "source_paths": len(source["shapes"]), "kept_paths": len(ordered)},
        "strokes": [{
            "order": index + 1,
            "id": item["id"],
            "length_mm": round(item["length_mm"], 3),
            "travel_from_previous_mm": item["travel_from_previous_mm"],
            # A later physical executor will only use this after a separate
            # feedback gate and user confirmation.
            "recommended_contact_depth_mm": round(min(1.15, 0.72 + 0.035*item["source_stroke_px"]), 3),
            "points": [[round(x, 3), round(y, 3)] for x, y in item["points"]],
        } for index, item in enumerate(ordered)],
    }
    (out / f"{args.name}_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    canvas = Image.new("RGB", (1200, 820), (255, 253, 248))
    draw = ImageDraw.Draw(canvas)
    for item in ordered:
        points = [(round(x*6.4), round(y*5.45)) for x, y in item["points"]]
        draw.line(points, fill=(20, 20, 20), width=3, joint="curve")
    canvas.save(out / f"{args.name}_preview.png")
    total = sum(item["length_mm"] for item in ordered)
    travel = sum(item["travel_from_previous_mm"] for item in ordered)
    print(json.dumps({"kept_paths": len(ordered), "draw_length_mm": round(total, 1), "pen_up_travel_mm": round(travel, 1)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
