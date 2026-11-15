import * as Cesium from "cesium";
import { fmtClock, interp } from "./charts";
import type { Route } from "./types";

/**
 * Helmet heads-up display: first-person camera on the planned route with a visor overlay.
 * Every figure shown comes from the route returned by the planner (segments, stops, envelope slack, context);
 * the HUD only interpolates along it at the EVA clock time.
 */
export class Hud {
  active = false;
  private el = document.getElementById("hud")!;
  private savedExag = 1.5;
  private lastH = 0;
  private o2Start = 0.6;
  private battStart = 800;

  constructor(private viewer: Cesium.Viewer, private onExit: () => void) {
    document.getElementById("hud-exit")!.addEventListener("click", () => this.exit());
    document.addEventListener("keydown", (e) => { if (this.active && e.key === "Escape") this.exit(); });
  }

  enter(o2Start: number, battStart: number) {
    this.active = true;
    this.o2Start = o2Start;
    this.battStart = battStart;
    this.savedExag = this.viewer.scene.verticalExaggeration;
    this.viewer.scene.verticalExaggeration = 1;
    this.viewer.scene.screenSpaceCameraController.enableInputs = false;
    document.body.classList.add("hud-on");
    this.el.hidden = false;
  }

  exit() {
    if (!this.active) return;
    this.active = false;
    this.viewer.scene.verticalExaggeration = this.savedExag;
    this.viewer.scene.screenSpaceCameraController.enableInputs = true;
    document.body.classList.remove("hud-on");
    this.el.hidden = true;
    this.onExit();
  }

  update(r: Route, t: number) {
    if (!this.active) return;
    const s = r.segments;
    const lons = r.geometry.coordinates.map((c) => c[0]), lats = r.geometry.coordinates.map((c) => c[1]);
    const lon = interp(s.t_s, lons, t), lat = interp(s.t_s, lats, t);
    // heading from the path ~25 m ahead (look-ahead in time at walking pace)
    let tAhead = t + 30;
    const k0 = idx(s.t_s, t);
    for (let k = k0; k < s.t_s.length; k++) { if (s.dist_m[k] - interp(s.t_s, s.dist_m, t) > 25) { tAhead = s.t_s[k]; break; } }
    const lon2 = interp(s.t_s, lons, tAhead), lat2 = interp(s.t_s, lats, tAhead);
    const dx = (lon2 - lon) * Math.cos((lat * Math.PI) / 180), dy = lat2 - lat;
    const heading = Math.hypot(dx, dy) > 1e-9 ? Math.atan2(dx, dy) : this.headingPrev;
    this.headingPrev = heading;
    const h = this.viewer.scene.globe.getHeight(Cesium.Cartographic.fromDegrees(lon, lat));
    if (h !== undefined) this.lastH = h;
    this.viewer.camera.setView({
      destination: Cesium.Cartesian3.fromDegrees(lon, lat, this.lastH + 1.8),
      orientation: { heading, pitch: Cesium.Math.toRadians(-6), roll: 0 },
    });

    // --- readouts -----------------------------------------------------------------------------
    const deg = ((Cesium.Math.toDegrees(heading) % 360) + 360) % 360;
    this.compass(deg);
    const o2 = this.o2Start - interp(s.t_s, s.o2_kg, t);
    const batt = this.battStart - interp(s.t_s, s.batt_wh, t);
    const res = r.totals.o2_reserve_kg, bres = r.totals.batt_reserve_wh;
    bar("hud-o2", o2 / this.o2Start, o2 <= res * 1.2);
    bar("hud-batt", batt / this.battStart, batt <= bres * 1.2);
    set("hud-o2-v", `${o2.toFixed(3)} kg`);
    set("hud-batt-v", `${batt.toFixed(0)} Wh`);
    set("hud-clock", `T+${fmtClock(t)}`);

    const next = r.stops.find((x) => x.index != null && s.t_s[x.index] > t + 1) ?? r.stops[r.stops.length - 1];
    const ni = next.index ?? s.t_s.length - 1;
    const distLeft = Math.max(s.dist_m[ni] - interp(s.t_s, s.dist_m, t), 0);
    const brg = Math.atan2((next.lon - lon) * Math.cos((lat * Math.PI) / 180), next.lat - lat);
    const rel = Cesium.Math.toDegrees(brg - heading);
    set("hud-next", next.kind === "habitat" ? "Habitat" : next.name.replace(/ \(.*\)$/, ""));
    set("hud-next-d", distLeft >= 1000 ? `${(distLeft / 1000).toFixed(2)} km` : `${distLeft.toFixed(0)} m`);
    set("hud-next-eta", `ETA T+${fmtClock(s.t_s[ni])}`);
    (document.getElementById("hud-arrow") as unknown as SVGElement).style.transform = `rotate(${rel}deg)`;

    const slack = s.slack_s[Math.min(idx(s.t_s, t), s.slack_s.length - 1)];
    const pnr = r.point_of_no_return;
    const warn = document.getElementById("hud-warn")!;
    if (pnr && t >= pnr.t_s) { warn.textContent = "PAST POINT OF NO RETURN: TURN BACK"; warn.className = "hud-warn crit"; }
    else if (pnr) { warn.textContent = `Point of no return in ${fmtClock(pnr.t_s - t)}`; warn.className = "hud-warn amber"; }
    else { warn.textContent = slack < -1e8 ? "" : `Return margin ${fmtClock(Math.max(slack, 0))} h`; warn.className = "hud-warn"; }

    const ctx = r.context;
    const dz = ctx?.comms?.dead_zones.find((z) => t >= z.t_start_s && t <= z.t_start_s + z.duration_s);
    const nextDz = ctx?.comms?.dead_zones.find((z) => z.t_start_s > t);
    const comm = document.getElementById("hud-comms")!;
    if (dz) { comm.textContent = `NO LOS TO HABITAT: ${fmtClock(dz.t_start_s + dz.duration_s - t)} to reacquire`; comm.className = "hud-pill crit"; }
    else { comm.textContent = nextDz ? `COMMS LOS: dead zone in ${fmtClock(nextDz.t_start_s - t)}` : "COMMS LOS"; comm.className = "hud-pill ok"; }
    const geo = ctx?.geology?.filter((g) => g.t_start_s <= t).pop();
    set("hud-geo", geo ? `${geo.name} (${geo.symbol})` : "");
    if (ctx?.radiation) {
      const dose = (ctx.radiation.dose_rate_msv_per_day / 86400) * (t - s.t_s[0]);
      set("hud-rad", `${(dose * 1000).toFixed(0)} µSv GCR`);
    }
    const slopeNow = interp(s.t_s, s.slope_deg, t);
    set("hud-slope", `${slopeNow.toFixed(0)}° slope`);
  }

  private headingPrev = 0;

  private compass(deg: number) {
    const tape = document.getElementById("hud-tape")!;
    const names: Record<number, string> = { 0: "N", 45: "NE", 90: "E", 135: "SE", 180: "S", 225: "SW", 270: "W", 315: "NW" };
    let html = "";
    for (let d = Math.floor((deg - 60) / 15) * 15; d <= deg + 60; d += 15) {
      const n = ((d % 360) + 360) % 360;
      const x = 50 + ((d - deg) / 120) * 100;
      html += `<span style="left:${x}%" class="${names[n] ? "maj" : ""}">${names[n] ?? n}</span>`;
    }
    tape.innerHTML = html + `<b>${deg.toFixed(0).padStart(3, "0")}</b>`;
  }
}

function idx(ts: number[], t: number) {
  const k = ts.findIndex((x) => x >= t);
  return k < 0 ? ts.length - 1 : k;
}
function set(id: string, v: string) { const e = document.getElementById(id); if (e) e.textContent = v; }
function bar(id: string, f: number, low: boolean) {
  const e = document.getElementById(id) as HTMLElement;
  e.style.setProperty("--f", `${Math.max(0, Math.min(1, f)) * 100}%`);
  e.classList.toggle("low", low);
}
