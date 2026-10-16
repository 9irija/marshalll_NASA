"""Apollo-style cuff checklist: one printable card per route."""
from __future__ import annotations

import html

import numpy as np

from planner.routes import Route
from planner.site import Site


def _hm(s: float) -> str:
    s = max(0, int(round(s)))
    return f"{s // 3600}:{(s % 3600) // 60:02d}"


def cuff_html(site: Site, r: Route) -> str:
    p = r.params
    seg = r.seg
    o2_left = p.initial_o2_kg - seg["o2_kg"]
    b_left = p.battery_wh - seg["batt_wh"]
    slack = r.margins["slack_s"]
    rows = []
    points = [(0, r.stops[0].name)] + [(k, s.name) for k, s in zip(r.stop_index, [s for s in r.stops[1:] if s.kind != "habitat"])]
    points.append((len(r.rows) - 1, r.stops[-1].name))
    for i, (k, name) in enumerate(points):
        lon, lat = site.grid.rc_to_lonlat(r.rows[k], r.cols[k])
        leave_by = seg["t_s"][k] + slack[k] if np.isfinite(slack[k]) else None
        rows.append(
            f"<tr><td>{i}</td><td>{html.escape(name)}</td><td>{lat:.5f}N<br>{lon:.5f}E</td><td>{_hm(seg['t_s'][k])}</td>"
            f"<td>{seg['dist_m'][k] / 1000:.2f}</td><td>{o2_left[k]:.3f}</td><td>{b_left[k]:.0f}</td>"
            f"<td>{_hm(leave_by) if leave_by is not None else '&mdash;'}</td></tr>")
    pnr = r.margins.get("point_of_no_return")
    o2_res = p.initial_o2_kg * p.o2_reserve_frac
    b_res = p.battery_wh * p.batt_reserve_frac
    triggers = [
        f"O2 below planned value by more than {0.1 * p.initial_o2_kg:.3f} kg at any stop: ABORT, walk home on the safest route.",
        f"Battery below planned value by more than {0.1 * p.battery_wh:.0f} Wh at any stop: ABORT.",
        "Clock past the 'leave by' time at a stop: ABORT (the return envelope no longer contains you).",
        f"Arrive home with at least {o2_res:.3f} kg O2 and {b_res:.0f} Wh (reserve).",
        "Dust storm or suit fault declared: call Flight Controller for a replan before moving.",
    ]
    if pnr:
        triggers.insert(0, f"POINT OF NO RETURN at T+{_hm(pnr['t_s'])} ({pnr['lat']:.5f}N {pnr['lon']:.5f}E): do not continue past it.")
    t = r.totals
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Cuff checklist {r.id}</title>
<style>
@page {{ size: 148mm 105mm; margin: 6mm; }}
body {{ font: 10.5px/1.35 "IBM Plex Sans", "Segoe UI", sans-serif; color: #111; margin: 0; padding: 8px; }}
h1 {{ font-size: 13px; margin: 0 0 2px; }} .meta {{ color: #444; margin-bottom: 6px; }}
table {{ border-collapse: collapse; width: 100%; }} th, td {{ border: 1px solid #333; padding: 2px 4px; text-align: left; vertical-align: top; }}
th {{ background: #e9e2d6; }} td:nth-child(n+4) {{ font-variant-numeric: tabular-nums; text-align: right; }}
ol {{ margin: 6px 0 0 16px; padding: 0; }} li {{ margin: 1px 0; }}
.card {{ border: 2px solid #111; padding: 6px; max-width: 560px; }}
</style></head><body><div class="card">
<h1>MARSWALK CUFF CARD &middot; {html.escape(r.objective.upper())} &middot; route {r.id}</h1>
<div class="meta">{t['distance_m'] / 1000:.2f} km &middot; {_hm(t['duration_s'])} h &middot; O2 used {t['o2_kg']:.3f} of {p.initial_o2_kg:.2f} kg
&middot; battery used {t['batt_wh']:.0f} of {p.battery_wh:.0f} Wh &middot; max slope {t['max_slope_deg']:.1f}&deg;
&middot; model {html.escape(p.version)}</div>
<table><thead><tr><th>#</th><th>Stop</th><th>Position</th><th>T+</th><th>km</th><th>O2 kg</th><th>Wh</th><th>Leave by</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<ol>{''.join(f'<li>{html.escape(x)}</li>' for x in triggers)}</ol>
</div></body></html>"""
