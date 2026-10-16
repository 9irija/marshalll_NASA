import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";
import type { Route } from "./types";
import { ROUTE_COLORS } from "./scene";

const INK = "#a9b8c5";
const GRID = "rgba(169,184,197,0.12)";
const O2 = "#199e70";
const BATT = "#d95926";
const RESERVE = "#e34948";
const FONT = "12px Archivo, system-ui, sans-serif";

const axis = (label: string, fmt?: (v: number) => string): uPlot.Axis => ({
  stroke: INK, grid: { stroke: GRID, width: 1 }, ticks: { stroke: GRID, width: 1, size: 4 }, font: FONT, labelFont: FONT,
  label, labelSize: 18, size: 52, gap: 4, values: fmt ? (_u, vals) => vals.map(fmt) : undefined,
});

/** Draws a vertical line at the current EVA time (x in the chart's own units). */
function cursorPlugin(getX: () => number | null, getReserve?: () => number | null): uPlot.Plugin {
  return {
    hooks: {
      draw: (u) => {
        const ctx = u.ctx;
        const res = getReserve?.();
        if (res != null) {
          const y = u.valToPos(res, "y", true);
          ctx.save();
          ctx.strokeStyle = RESERVE;
          ctx.setLineDash([6, 5]);
          ctx.lineWidth = 1.5 * devicePixelRatio;
          ctx.beginPath();
          ctx.moveTo(u.bbox.left, y);
          ctx.lineTo(u.bbox.left + u.bbox.width, y);
          ctx.stroke();
          ctx.fillStyle = RESERVE;
          ctx.font = `${11 * devicePixelRatio}px Archivo, system-ui, sans-serif`;
          ctx.fillText("Reserve", u.bbox.left + 6 * devicePixelRatio, y - 5 * devicePixelRatio);
          ctx.restore();
        }
        const x = getX();
        if (x == null) return;
        const px = u.valToPos(x, "x", true);
        ctx.save();
        ctx.strokeStyle = "#d9a066";
        ctx.lineWidth = 2 * devicePixelRatio;
        ctx.beginPath();
        ctx.moveTo(px, u.bbox.top);
        ctx.lineTo(px, u.bbox.top + u.bbox.height);
        ctx.stroke();
        ctx.restore();
      },
    },
  };
}

export class Charts {
  private elev?: uPlot;
  private cons?: uPlot;
  private route?: Route;
  private t: number | null = null;

  constructor(private elevEl: HTMLElement, private consEl: HTMLElement) {
    new ResizeObserver(() => this.resize()).observe(elevEl);
  }

  private width() {
    return Math.max(220, this.elevEl.clientWidth);
  }

  setRoute(r: Route, o2Start: number, battStart: number) {
    this.route = r;
    const s = r.segments;
    const km = s.dist_m.map((d) => d / 1000);
    const h = s.t_s.map((t) => t / 3600);
    const o2pct = s.o2_kg.map((v) => (100 * (o2Start - v)) / o2Start);
    const bpct = s.batt_wh.map((v) => (100 * (battStart - v)) / battStart);
    const reservePct = (100 * r.totals.o2_reserve_kg) / o2Start;
    this.elev?.destroy();
    this.cons?.destroy();
    this.elev = new uPlot({
      width: this.width(), height: 120, legend: { show: true, live: true },
      cursor: { drag: { x: false, y: false }, points: { size: 8 } },
      scales: { x: { time: false } },
      axes: [axis("Distance (km)", (v) => v.toFixed(1)), axis("Elevation (m)", (v) => v.toFixed(0))],
      series: [
        { label: "Distance (km)", value: (_u, v) => (v == null ? "" : v.toFixed(2)) },
        { label: "Elevation", stroke: ROUTE_COLORS[r.objective], width: 2, value: (_u, v) => (v == null ? "" : `${v.toFixed(1)} m`) },
      ],
      plugins: [cursorPlugin(() => (this.t == null ? null : interp(s.t_s, km, this.t)))],
    }, [km, s.elev_m], this.elevEl);
    this.cons = new uPlot({
      width: this.width(), height: 150, legend: { show: true, live: true },
      cursor: { drag: { x: false, y: false }, points: { size: 8 } },
      scales: { x: { time: false }, y: { range: [0, 100] } },
      axes: [axis("EVA time (h)", (v) => v.toFixed(1)), axis("Remaining (%)", (v) => `${v}`)],
      series: [
        { label: "EVA time", value: (_u, v) => (v == null ? "" : `T+${fmtClock(v * 3600)}`) },
        { label: "O2", stroke: O2, width: 2, value: (_u, v) => (v == null ? "" : `${v.toFixed(0)} %`) },
        { label: "Battery", stroke: BATT, width: 2, dash: [8, 4], value: (_u, v) => (v == null ? "" : `${v.toFixed(0)} %`) },
      ],
      plugins: [cursorPlugin(() => (this.t == null ? null : this.t / 3600), () => reservePct)],
    }, [h, o2pct, bpct], this.consEl);
  }

  setTime(t: number) {
    this.t = t;
    this.elev?.redraw(false, false);
    this.cons?.redraw(false, false);
  }

  private resize() {
    const w = this.width();
    this.elev?.setSize({ width: w, height: 120 });
    this.cons?.setSize({ width: w, height: 150 });
  }

  get current() {
    return this.route;
  }
}

export function interp(xs: number[], ys: number[], x: number): number {
  if (x <= xs[0]) return ys[0];
  if (x >= xs[xs.length - 1]) return ys[ys.length - 1];
  let lo = 0, hi = xs.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (xs[mid] <= x) lo = mid; else hi = mid;
  }
  const f = (x - xs[lo]) / (xs[hi] - xs[lo] || 1);
  return ys[lo] + f * (ys[hi] - ys[lo]);
}

export function fmtClock(s: number): string {
  const v = Math.max(0, Math.round(s));
  return `${Math.floor(v / 3600)}:${String(Math.floor((v % 3600) / 60)).padStart(2, "0")}`;
}
