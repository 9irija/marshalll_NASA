"""Printable mission map for one route, in the style of NASA's annotated rover route maps.

Top-down HiRISE orthoimage (2 m grid) with the USGS geologic units and their contacts, the planned route with
T+ time ticks every 30 min, radio dead zones, science stops, the habitat, the point of no return, a scale bar,
a north arrow and a title block whose numbers all come from the planned route.
"""
from __future__ import annotations

import io
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from pipeline.geo import PROCESSED
from planner import awareness
from planner.routes import OBJECTIVE_LABEL, Route
from planner.site import Site

ROUTE = {"safest": (57, 135, 229), "fastest": (201, 133, 0), "science": (144, 133, 233), "abort": (233, 238, 242)}
INK, PAPER, MUTED, CRIT, DEAD, OK = (15, 28, 39), (233, 238, 242), (169, 184, 197), (227, 73, 72), (255, 64, 200), (47, 209, 166)


def _font(size: int, bold: bool = False):
    for name in (("arialbd.ttf", "DejaVuSans-Bold.ttf") if bold else ("arial.ttf", "DejaVuSans.ttf")):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


@lru_cache(maxsize=1)
def _ortho() -> np.ndarray:
    im = Image.open(PROCESSED / "web" / "ortho.png").convert("LA")
    return np.asarray(im)


def _clock(s: float) -> str:
    m = int(round(s / 60))
    return f"{m // 60}:{m % 60:02d}"


def render(site: Site, r: Route, width_px: int = 1800) -> bytes:
    rows, cols = r.rows, r.cols
    H, W = site.grid.shape
    pad = 120                                                     # 240 m margin around the route
    r0, r1 = max(0, rows.min() - pad), min(H, rows.max() + pad + 1)
    c0, c1 = max(0, cols.min() - pad), min(W, cols.max() + pad + 1)
    if (c1 - c0) < 1.4 * (r1 - r0):                                # keep a landscape sheet
        extra = int((1.4 * (r1 - r0) - (c1 - c0)) / 2)
        c0, c1 = max(0, c0 - extra), min(W, c1 + extra)
    s = width_px / (c1 - c0)
    map_w, map_h = width_px, int((r1 - r0) * s)

    o = _ortho()[r0:r1, c0:c1]
    gray = o[..., 0].astype(np.float32)
    rgb = np.stack([gray * 0.95, gray * 0.9, gray * 0.85], -1)
    if awareness.available():
        L = awareness.layers()
        u = L["geo_unit"][r0:r1, c0:c1]
        tint = np.zeros_like(rgb)
        for uid, leg in L["legend"].items():
            tint[u == uid] = leg["colour"]
        m = (u >= 0)[..., None]
        rgb = np.where(m, rgb * 0.72 + tint * 0.28, rgb)
        edge = np.zeros(u.shape, bool)
        edge[1:, :] |= u[1:, :] != u[:-1, :]
        edge[:, 1:] |= u[:, 1:] != u[:, :-1]
        rgb[edge] = (25, 25, 30)
    base = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8)).resize((map_w, map_h), Image.BILINEAR)

    head = 150
    foot = 170
    sheet = Image.new("RGB", (map_w, map_h + head + foot), INK)
    sheet.paste(base, (0, head))
    d = ImageDraw.Draw(sheet)
    xy = lambda rr, cc: ((cc - c0 + 0.5) * s, (rr - r0 + 0.5) * s + head)  # noqa: E731

    pts = [xy(a, b) for a, b in zip(rows, cols)]
    col = ROUTE.get(r.objective, ROUTE["safest"])
    d.line(pts, fill=INK, width=9, joint="curve")
    d.line(pts, fill=col, width=5, joint="curve")
    ctx = awareness.route_context(site, rows, cols, r.seg, r.params, r.mode, r.stop_index) if awareness.available() else {}
    for z in ctx.get("comms", {}).get("dead_zones", []):
        seg = pts[z["start_index"]: z["end_index"] + 1]
        acc, on, run = 0.0, True, [seg[0]] if seg else []
        for a, b in zip(seg[:-1], seg[1:]):                         # dashes of ~14 px along the path
            acc += ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
            run.append(b)
            if acc >= 14:
                if on and len(run) > 1:
                    d.line(run, fill=DEAD, width=8)
                on, acc, run = not on, 0.0, [b]

    t = r.seg["t_s"]
    f_s, f_m, f_b, f_t = _font(18), _font(22), _font(24, True), _font(40, True)
    for tick in np.arange(1800, t[-1], 1800):                       # T+ ticks every 30 min
        k = int(np.searchsorted(t, tick))
        if k >= len(pts):
            break
        x, y = pts[k]
        d.ellipse((x - 6, y - 6, x + 6, y + 6), fill=PAPER, outline=INK, width=2)
        d.text((x + 10, y - 26), f"T+{_clock(tick)}", font=f_s, fill=PAPER, stroke_width=3, stroke_fill=INK)

    hx, hy = xy(site.habitat["row"], site.habitat["col"])
    d.rectangle((hx - 11, hy - 11, hx + 11, hy + 11), fill=(217, 160, 102), outline=INK, width=3)
    d.text((hx + 16, hy - 12), "Habitat", font=f_b, fill=PAPER, stroke_width=3, stroke_fill=INK)
    n = 0
    for st, k in zip([x for x in r.stops if x.kind != "habitat"], r.stop_index):
        n += 1
        x, y = pts[k]
        d.ellipse((x - 15, y - 15, x + 15, y + 15), fill=PAPER, outline=INK, width=3)
        d.text((x, y), str(n), font=f_b, fill=INK, anchor="mm")
        d.text((x + 20, y - 14), f"{st.name.replace(' (delta front)', '')}  T+{_clock(t[k])}", font=f_m, fill=PAPER, stroke_width=3,
               stroke_fill=INK)
    p = r.margins.get("point_of_no_return")
    if p:
        x, y = pts[min(int(p["index"]), len(pts) - 1)]
        d.polygon([(x, y - 18), (x + 16, y + 12), (x - 16, y + 12)], fill=CRIT, outline=INK)
        d.text((x + 20, y - 4), f"Point of no return T+{_clock(p['t_s'])}", font=f_m, fill=CRIT, stroke_width=3, stroke_fill=INK)

    # scale bar (500 m) and north arrow
    bar = 500 / site.grid.res_m * s
    by = head + map_h - 40
    d.rectangle((30, by, 30 + bar, by + 10), fill=PAPER, outline=INK, width=2)
    d.rectangle((30, by, 30 + bar / 2, by + 10), fill=INK)
    d.text((30, by - 30), "0        250       500 m", font=f_s, fill=PAPER, stroke_width=3, stroke_fill=INK)
    nx, ny = map_w - 60, head + 40
    d.polygon([(nx, ny - 26), (nx + 14, ny + 14), (nx, ny + 4), (nx - 14, ny + 14)], fill=PAPER, outline=INK)
    d.text((nx, ny + 32), "N", font=f_b, fill=PAPER, anchor="mm", stroke_width=3, stroke_fill=INK)

    # title block
    tot = r.totals
    label = ("Rover: " if r.mode == "rover" else "") + OBJECTIVE_LABEL.get(r.objective, r.objective)
    dest = " > ".join(x.name.replace(" (delta front)", "") for x in r.stops if x.kind != "habitat") or "habitat"
    d.text((30, 26), f"Marswalk EVA map: Habitat > {dest} > Habitat", font=f_t, fill=PAPER)
    status = "FEASIBLE" if tot["feasible"] else "NOT FEASIBLE"
    d.text((30, 86), f"{label} route   {tot['distance_m'] / 1000:.2f} km   {_clock(tot['duration_s'])} h   O2 {tot['o2_kg']:.3f} kg"
           f"   battery {tot['batt_wh']:.0f} Wh   max slope {tot['max_slope_deg']:.1f} deg   ", font=f_m, fill=MUTED)
    d.text((map_w - 30, 40), status, font=f_t, fill=OK if tot["feasible"] else CRIT, anchor="ra")

    fy = head + map_h + 22
    if ctx:
        cm, rad = ctx["comms"], ctx["radiation"]
        d.text((30, fy), f"Radio line of sight to habitat {cm['line_of_sight_fraction'] * 100:.0f}% of route; longest dead zone "
               f"{_clock(cm['longest_dead_zone_s'])} h.   Worst-case time to shelter {_clock(rad['max_time_to_shelter_s'])} h "
               f"({'meets' if rad['sep_shelter_ok'] else 'exceeds'} the {_clock(rad['sep_warning_s'])} h solar-particle rule).   "
               f"Cosmic-ray dose {rad['gcr_dose_msv']:.3f} mSv.", font=f_m, fill=PAPER)
    lx = 30
    for sw, txt in ((col, "Planned route"), (DEAD, "No radio line of sight"), (PAPER, "Science stop / T+ every 30 min"),
                    ((217, 160, 102), "Habitat"), (CRIT, "Point of no return")):
        d.rectangle((lx, fy + 50, lx + 26, fy + 64), fill=sw, outline=INK)
        d.text((lx + 34, fy + 45), txt, font=f_s, fill=MUTED)
        lx += 40 + d.textlength(txt, font=f_s) + 30
    if awareness.available():
        lx = 30
        units = {g["symbol"]: g["name"] for g in ctx.get("geology", [])}
        for leg in awareness.layers()["legend"].values():
            if leg["symbol"] not in units:
                continue
            d.rectangle((lx, fy + 86, lx + 26, fy + 100), fill=tuple(leg["colour"]), outline=INK)
            txt = f"{leg['name']} ({leg['symbol']})"
            d.text((lx + 34, fy + 81), txt, font=f_s, fill=MUTED)
            lx += 40 + d.textlength(txt, font=f_s) + 30
    d.text((30, fy + 118), "Base: HiRISE PSP_002387_1985 orthoimage, DTM DTEEC_002387_1985_003798_1985_A01.  Geology: USGS SIM 3464.  "
           "Times and consumables: Marswalk planner, model " + r.params.version + ".", font=f_s, fill=MUTED)
    buf = io.BytesIO()
    sheet.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
