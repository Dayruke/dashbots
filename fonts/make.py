#!/usr/bin/env python3
"""Build fonts/Dashbots.ttf from the imp icon.

The Omarchy menu draws a font glyph, not an SVG. Needs fontTools.
Run: python3 fonts/make.py
"""

import math
import os
import re

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

UPM = 1000
BOX = 24.0
HERE = os.path.dirname(os.path.abspath(__file__))
SVG = os.path.join(HERE, "..", "plugin", "icons", "botvaders", "imp.svg")
OUT = os.path.join(HERE, "Dashbots.ttf")
TOKEN = re.compile(r"[MmLlHhVvZzAa]|[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?")


def tokens(path):
    return TOKEN.findall(path)


def arc_points(x1, y1, rx, ry, phi_deg, large, sweep, x2, y2, steps=16):
    if math.isclose(x1, x2) and math.isclose(y1, y2):
        return []
    if rx == 0 or ry == 0:
        return [(x2, y2)]
    phi = math.radians(phi_deg % 360)
    rx, ry = abs(rx), abs(ry)
    cos_p, sin_p = math.cos(phi), math.sin(phi)
    dx, dy = (x1 - x2) / 2.0, (y1 - y2) / 2.0
    x1p = cos_p * dx + sin_p * dy
    y1p = -sin_p * dx + cos_p * dy
    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1:
        scale = math.sqrt(lam)
        rx *= scale
        ry *= scale
    rx_sq, ry_sq = rx * rx, ry * ry
    num = rx_sq * ry_sq - rx_sq * y1p * y1p - ry_sq * x1p * x1p
    den = rx_sq * y1p * y1p + ry_sq * x1p * x1p
    coef = math.sqrt(max(0.0, num / den)) if den else 0.0
    if bool(large) == bool(sweep):
        coef = -coef
    cxp = coef * rx * y1p / ry
    cyp = coef * -ry * x1p / rx
    cx = cos_p * cxp - sin_p * cyp + (x1 + x2) / 2.0
    cy = sin_p * cxp + cos_p * cyp + (y1 + y2) / 2.0

    def angle(ux, uy, vx, vy):
        dot = ux * vx + uy * vy
        norm = math.hypot(ux, uy) * math.hypot(vx, vy)
        ang = math.acos(max(-1.0, min(1.0, dot / norm))) if norm else 0.0
        if ux * vy - uy * vx < 0:
            ang = -ang
        return ang

    theta = angle(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    delta = angle(
        (x1p - cxp) / rx,
        (y1p - cyp) / ry,
        (-x1p - cxp) / rx,
        (-y1p - cyp) / ry,
    )
    if not sweep and delta > 0:
        delta -= 2 * math.pi
    elif sweep and delta < 0:
        delta += 2 * math.pi
    points = []
    for step in range(1, steps + 1):
        t = theta + delta * step / steps
        x = cx + cos_p * rx * math.cos(t) - sin_p * ry * math.sin(t)
        y = cy + sin_p * rx * math.cos(t) + cos_p * ry * math.sin(t)
        points.append((x, y))
    points[-1] = (x2, y2)
    return points


def parse_subpaths(d):
    parts = tokens(d)
    index = 0
    cx = cy = 0.0
    start = (0.0, 0.0)
    subpaths = []
    current = None
    command = None

    def number():
        nonlocal index
        value = float(parts[index])
        index += 1
        return value

    while index < len(parts):
        piece = parts[index]
        if re.fullmatch(r"[MmLlHhVvZzAa]", piece):
            command = piece
            index += 1
        elif command is None:
            raise SystemExit(f"path has a number before a command: {piece}")
        cmd = command
        if cmd in ("M", "m"):
            x, y = number(), number()
            if cmd == "m":
                x, y = cx + x, cy + y
            if current:
                subpaths.append(current)
            current = [(x, y)]
            cx, cy = x, y
            start = (x, y)
            command = "L" if cmd == "M" else "l"
            continue
        if cmd in ("L", "l"):
            x, y = number(), number()
            if cmd == "l":
                x, y = cx + x, cy + y
            current.append((x, y))
            cx, cy = x, y
            continue
        if cmd in ("H", "h"):
            x = number()
            if cmd == "h":
                x = cx + x
            current.append((x, cy))
            cx = x
            continue
        if cmd in ("V", "v"):
            y = number()
            if cmd == "v":
                y = cy + y
            current.append((cx, y))
            cy = y
            continue
        if cmd in ("A", "a"):
            rx, ry = number(), number()
            phi = number()
            large = int(number())
            sweep = int(number())
            x, y = number(), number()
            if cmd == "a":
                x, y = cx + x, cy + y
            current.extend(arc_points(cx, cy, rx, ry, phi, large, sweep, x, y))
            cx, cy = x, y
            continue
        if cmd in ("Z", "z"):
            if current and current[-1] != start:
                current.append(start)
            cx, cy = start
            continue
        raise SystemExit(f"unsupported path command {cmd}")
    if current:
        subpaths.append(current)
    return subpaths


def signed_area(points):
    area = 0.0
    for index, (x1, y1) in enumerate(points):
        x2, y2 = points[(index + 1) % len(points)]
        area += x1 * y2 - x2 * y1
    return area / 2.0


def point_in(x, y, poly):
    inside = False
    j = len(poly) - 1
    for i, (xi, yi) in enumerate(poly):
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            cross = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < cross:
                inside = not inside
        j = i
    return inside


def interior(poly):
    area = signed_area(poly)
    if abs(area) < 1e-9:
        return poly[0]
    for index, (x1, y1) in enumerate(poly):
        x2, y2 = poly[(index + 1) % len(poly)]
        length = math.hypot(x2 - x1, y2 - y1)
        if length < 1e-6:
            continue
        # Left of the edge is inside a positive-area contour.
        nx, ny = -(y2 - y1) / length, (x2 - x1) / length
        if area < 0:
            nx, ny = -nx, -ny
        mx, my = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        for distance in (0.2, 0.05, 0.5):
            px, py = mx + nx * distance, my + ny * distance
            if point_in(px, py, poly):
                return px, py
    return poly[0]


def orient(points, clockwise):
    positive = signed_area(points) > 0
    if clockwise == positive:
        points = list(reversed(points))
    if points and points[0] == points[-1]:
        points = points[:-1]
    return points


def to_font(points):
    scaled = []
    for x, y in points:
        fx = round(x / BOX * UPM)
        fy = round((BOX - y) / BOX * UPM)
        if not scaled or scaled[-1] != (fx, fy):
            scaled.append((fx, fy))
    if len(scaled) > 1 and scaled[0] == scaled[-1]:
        scaled = scaled[:-1]
    return scaled


def glyph_from(subpaths):
    probes = [interior(path) for path in subpaths]
    roles = []
    for index, probe in enumerate(probes):
        depth = 0
        for other, poly in enumerate(subpaths):
            if other == index:
                continue
            if point_in(probe[0], probe[1], poly):
                depth += 1
        roles.append(depth)
    pen = TTGlyphPen(None)
    drawn = 0
    for path, depth in zip(subpaths, roles):
        # Even depth is filled (body, shine). Odd depth is an eye hole.
        # Font y is up, so clockwise there is the opposite of clockwise on screen.
        font_points = to_font(orient(path, clockwise=(depth % 2 == 1)))
        if len(font_points) < 3:
            continue
        pen.moveTo(font_points[0])
        for point in font_points[1:]:
            pen.lineTo(point)
        pen.closePath()
        drawn += 1
    if drawn < 3:
        raise SystemExit(f"imp glyph has {drawn} contours, expected the body and eyes")
    return pen.glyph(), roles


def main():
    with open(SVG, encoding="utf-8") as handle:
        text = handle.read()
    match = re.search(r'\bd="([^"]+)"', text)
    if not match:
        raise SystemExit(f"no path in {SVG}")
    subpaths = parse_subpaths(match.group(1))
    glyph, roles = glyph_from(subpaths)
    empty = TTGlyphPen(None).glyph()
    builder = FontBuilder(UPM, isTTF=True)
    builder.setupGlyphOrder([".notdef", "imp"])
    builder.setupCharacterMap({0xE900: "imp"})
    builder.setupGlyf({".notdef": empty, "imp": glyph})
    builder.setupHorizontalMetrics({".notdef": (UPM, 0), "imp": (UPM, 0)})
    builder.setupHorizontalHeader(ascent=UPM, descent=0)
    builder.setupNameTable(
        {
            "familyName": "Dashbots",
            "styleName": "Regular",
            "uniqueFontIdentifier": "Dashbots Regular",
            "fullName": "Dashbots Regular",
            "version": "Version 1.000",
            "psName": "Dashbots-Regular",
            "typographicFamily": "Dashbots",
            "typographicSubfamily": "Regular",
        }
    )
    builder.setupOS2(
        sTypoAscender=UPM,
        sTypoDescender=0,
        usWinAscent=UPM,
        usWinDescent=0,
        sxHeight=500,
        sCapHeight=800,
    )
    builder.setupPost()
    builder.save(OUT)
    print(f"wrote {OUT} contours={len(roles)} depth={roles}")


if __name__ == "__main__":
    main()
