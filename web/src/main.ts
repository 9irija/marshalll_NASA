import "cesium/Build/Cesium/Widgets/widgets.css";
import "./style.css";
import * as Cesium from "cesium";
import * as api from "./api";
import { Charts, fmtClock, interp } from "./charts";
import { Drawer } from "./drawers";
import { EnvelopeLayer } from "./envelope";
import { addLocalOrtho, addOverlay, createTerrain, createViewer } from "./mars";
import { ROUTE_COLORS, SceneLayer } from "./scene";
import type { Envelope, Hazard, Objective, Route, Site, Target } from "./types";

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;

const OVERLAYS: { id: string; name: string; alpha: number; on?: boolean }[] = [
  { id: "science", name: "Science value (CRISM)", alpha: 0.85 },
  { id: "slope", name: "Slope", alpha: 0.75 },
  { id: "hazard", name: "Rock hazard (proxy)", alpha: 0.75 },
  { id: "olivine", name: "Olivine", alpha: 0.85 },
  { id: "fe_mg_smectite", name: "Fe/Mg smectite", alpha: 0.85 },
  { id: "carbonate", name: "Carbonate", alpha: 0.9 },
  { id: "hydration", name: "Hydration", alpha: 0.85 },
];

const app = {
  site: null as Site | null,
  targets: [] as Target[],
  routes: [] as Route[],
  selected: "safest" as Objective,
  envelope: null as Envelope | null,
  target: "wildcat_ridge",
  t: 0,
  playing: false,
  o2Start: 0.6,
  battStart: 800,
};

function toast(msg: string, ms = 5000) {
  const el = $("toast");
  el.textContent = msg;
  el.hidden = false;
  setTimeout(() => (el.hidden = true), ms);
}

async function boot() {
  await api.probe();
  const badge = $("mode-badge");
  if (!api.state.online) {
    badge.hidden = false;
    badge.textContent = "Demo data: planner API offline";
    $<HTMLInputElement>("hours").disabled = true;
  }
  const [terrain, site, targets] = await Promise.all([createTerrain(), api.getSite(), api.getTargets()]);
  app.site = site;
  app.targets = targets;
  const { viewer, base } = await createViewer($("globe"), terrain.provider);
  const ortho = await addLocalOrtho(viewer, site.grid.bounds);
  const scene = new SceneLayer(viewer);
  const env = new EnvelopeLayer(viewer.scene);
  const charts = new Charts($("chart-elev"), $("chart-cons"));
  (window as unknown as { __marswalk: unknown }).__marswalk = { viewer, scene, app };
  scene.addSite(site, targets, (id) => { $<HTMLSelectElement>("target").value = id; app.target = id; showTargetNote(); plan(); });
  scene.flyToBounds(site.grid.bounds.west, site.grid.bounds.south, site.grid.bounds.east, site.grid.bounds.north);

  // offline imagery fallback: if Trek tiles fail, show the local HiRISE orthoimage
  let trekErrors = 0;
  base.hirise.imageryProvider.errorEvent.addEventListener(() => { if (++trekErrors === 8) { ortho.show = true; toast("NASA Trek imagery unreachable, showing local HiRISE orthoimage."); } });

  // --- plan panel ---------------------------------------------------------------------------
  const sel = $<HTMLSelectElement>("target");
  sel.innerHTML = targets.map((t) => `<option value="${t.id}">${t.name}</option>`).join("");
  sel.value = app.target;
  const showTargetNote = () => {
    const t = targets.find((x) => x.id === sel.value)!;
    $("target-note").textContent = `${t.note} Science value ${t.science_value.toFixed(2)} (CRISM, 0 to 1).`;
  };
  showTargetNote();
  sel.addEventListener("change", () => { app.target = sel.value; showTargetNote(); });
  const hours = $<HTMLInputElement>("hours");
  hours.addEventListener("input", () => ($("hours-out").textContent = `${hours.value} h`));

  const layerList = $("layer-list");
  const handles = new Map<string, Cesium.ImageryLayer>();
  for (const o of OVERLAYS) handles.set(o.id, await addOverlay(viewer, `${o.id}.png`, site.grid.bounds, o.alpha));
  layerList.innerHTML = [
    `<div class="layer-row"><input type="checkbox" id="ly-hirise" checked><label for="ly-hirise">HiRISE 25 cm imagery</label><span></span></div>`,
    `<div class="layer-row"><input type="checkbox" id="ly-traverse"><label for="ly-traverse">Perseverance traverse</label><span></span></div>`,
    `<div class="layer-row"><input type="checkbox" id="ly-envelope" checked><label for="ly-envelope">Return envelope</label><span></span></div>`,
    ...OVERLAYS.map((o) => `<div class="layer-row"><input type="checkbox" id="ly-${o.id}"><label for="ly-${o.id}">${o.name}</label>
      <input type="range" min="0" max="1" step="0.05" value="${o.alpha}" id="op-${o.id}" aria-label="${o.name} opacity"></div>`),
    `<div class="layer-row"><input type="checkbox" id="ly-exag" checked><label for="ly-exag">Vertical exaggeration 1.5x</label><span></span></div>`,
  ].join("");
  $<HTMLInputElement>("ly-hirise").addEventListener("change", (e) => (base.hirise.show = (e.target as HTMLInputElement).checked));
  $<HTMLInputElement>("ly-traverse").addEventListener("change", (e) => scene.showTraverse((e.target as HTMLInputElement).checked));
  $<HTMLInputElement>("ly-envelope").addEventListener("change", (e) => (env.visible = (e.target as HTMLInputElement).checked));
  $<HTMLInputElement>("ly-exag").addEventListener("change", (e) => (viewer.scene.verticalExaggeration = (e.target as HTMLInputElement).checked ? 1.5 : 1));
  for (const o of OVERLAYS) {
    $<HTMLInputElement>(`ly-${o.id}`).addEventListener("change", (e) => (handles.get(o.id)!.show = (e.target as HTMLInputElement).checked));
    $<HTMLInputElement>(`op-${o.id}`).addEventListener("input", (e) => (handles.get(o.id)!.alpha = Number((e.target as HTMLInputElement).value)));
  }

  api.getConditions().then((c) => {
    $("conditions").innerHTML = `Weather at Jezero, sol ${c.sol} (${c.terrestrial_date}, MEDA): <strong>${c.temp_c.min ?? "?"} to ${c.temp_c.max ?? "?"} &deg;C</strong>,
      <strong>${c.pressure_pa ?? "?"} Pa</strong>, ${c.season}; sunrise ${c.sunrise}, sunset ${c.sunset}.`;
  }).catch(() => undefined);

  // --- routes ------------------------------------------------------------------------------
  const hazard = (): Hazard | null => ($<HTMLInputElement>("hz-dust").checked ? "dust_storm" : $<HTMLInputElement>("hz-leak").checked ? "suit_fault" : null);

  async function plan() {
    const btn = $<HTMLButtonElement>("plan-btn");
    btn.disabled = true;
    btn.textContent = "Planning on HiRISE terrain...";
    try {
      const res = await api.planRoute(app.target, Number(hours.value), hazard());
      await showRoutes(res.routes);
    } catch (e) {
      toast(`Planning failed: ${e instanceof Error ? e.message : e}`);
    } finally {
      btn.disabled = false;
      btn.textContent = "Plan routes";
    }
  }

  async function showRoutes(routes: Route[]) {
    app.routes = routes;
    const first = routes.find((r) => r.objective === app.selected) ?? routes[0];
    renderRouteList();
    await select(first.objective);
  }

  function renderRouteList() {
    $("route-list").innerHTML = app.routes.map((r) => {
      const t = r.totals;
      return `<button class="route" role="radio" data-objective="${r.objective}" aria-checked="${r.objective === app.selected}">
        <span class="sw" style="background:${ROUTE_COLORS[r.objective]}"></span>
        <span><span class="name">${r.label}</span><span class="sub">${(t.distance_m / 1000).toFixed(2)} km, ${fmtClock(t.duration_s)} h, ${t.o2_kg.toFixed(3)} kg O2</span></span>
        <span class="flag">${t.feasible ? "" : "Not feasible"}</span></button>`;
    }).join("");
    document.querySelectorAll<HTMLButtonElement>(".route").forEach((b) => b.addEventListener("click", () => select(b.dataset.objective as Objective)));
  }

  async function select(obj: Objective) {
    app.selected = obj;
    const r = app.routes.find((x) => x.objective === obj)!;
    document.querySelectorAll<HTMLButtonElement>(".route").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.objective === obj)));
    scene.setRoutes(app.routes, obj);
    app.o2Start = r.totals.o2_remaining_kg + r.totals.o2_kg;
    app.battStart = r.totals.batt_remaining_wh + r.totals.batt_wh;
    const t0 = r.segments.t_s[0];
    if (t0 > 0) { app.o2Start += r.segments.o2_kg[0]; app.battStart += r.segments.batt_wh[0]; }
    charts.setRoute(r, 0.6, 800);
    renderTotals(r);
    ($("cuff") as HTMLAnchorElement).href = api.state.online ? api.checklistUrl(r.id) : "#";
    try {
      app.envelope = await api.getEnvelope(r, app.target);
      env.set(app.envelope.deadline_field.url, app.envelope.deadline_field.bounds, app.envelope.deadline_field.t_max_s);
      scene.setMarkers(r.point_of_no_return, r.tightest_point);
    } catch (e) {
      app.envelope = null;
      env.clear();
      toast(`Envelope unavailable: ${e instanceof Error ? e.message : e}`);
    }
    renderMarks(r);
    setTime(t0);
    if (!reducedMotion && !app.playing) play(true);
  }

  function renderTotals(r: Route) {
    const t = r.totals;
    const pnr = r.point_of_no_return;
    const st = $("status");
    st.className = `status ${t.feasible ? "ok" : "bad"}`;
    const icon = t.feasible
      ? `<svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true"><circle cx="9" cy="9" r="8" fill="#2fd1a6"/><path d="M5 9.3 L7.8 12 L13 6.5" stroke="#0f1c27" stroke-width="2" fill="none"/></svg>`
      : `<svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true"><path d="M9 1 L17 16 H1 Z" fill="#e34948"/><path d="M9 6 V10.5 M9 12.8 V13" stroke="#0f1c27" stroke-width="2"/></svg>`;
    const msg = r.objective === "abort"
      ? `Walk home now on this route: ${(t.distance_m / 1000).toFixed(2)} km, arriving T+${fmtClock(t.duration_s)} with ${t.o2_remaining_kg.toFixed(3)} kg O2.`
      : pnr
      ? `Not safe as planned. Point of no return at T+${fmtClock(pnr.t_s)}: past it, the crew member cannot get home with reserve.`
      : t.feasible
        ? `Can get there, do the science and get home. Tightest margin ${fmtClock(r.tightest_point?.slack_s ?? 0)} h before the envelope closes.`
        : `Over budget: ${t.within_duration ? "consumables reserve would be broken." : "longer than the EVA time limit."}`;
    st.innerHTML = `${icon}<span><b>${r.label}.</b> ${msg}</span>`;
    $("totals").innerHTML = [
      ["Distance", `${(t.distance_m / 1000).toFixed(2)} <small>km</small>`],
      ["Duration", `${fmtClock(t.duration_s)} <small>h</small>`],
      ["O2 used", `${t.o2_kg.toFixed(3)} <small>kg</small>`],
      ["O2 left at habitat", `${t.o2_remaining_kg.toFixed(3)} <small>kg</small>`],
      ["Battery used", `${t.batt_wh.toFixed(0)} <small>Wh</small>`],
      ["Max slope", `${t.max_slope_deg.toFixed(1)} <small>deg</small>`],
    ].map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("");
  }

  /** Timeline runs to the EVA time limit (envelope horizon), not just to arrival at the habitat. */
  const tEnd = () => {
    const r = current();
    const arrive = r ? r.segments.t_s[r.segments.t_s.length - 1] : 1;
    return Math.max(arrive, app.envelope?.deadline_field.t_max_s ?? arrive);
  };
  const tStart = () => current()?.segments.t_s[0] ?? 0;
  const current = () => app.routes.find((x) => x.objective === app.selected);

  function renderMarks(r: Route) {
    const s = r.segments;
    const t0 = s.t_s[0], t1 = tEnd();
    const pct = (t: number) => `${(100 * (t - t0)) / Math.max(t1 - t0, 1)}%`;
    const marks = r.stops.filter((x) => x.kind !== "habitat" && x.index != null && x.kind === "target")
      .map((x) => `<div class="mark" style="left:${pct(s.t_s[x.index!])}"><span>${x.name.replace(/ \(.*\)$/, "")}</span></div>`);
    if (r.point_of_no_return) marks.push(`<div class="mark pnr" style="left:${pct(r.point_of_no_return.t_s)}"><span>No return</span></div>`);
    marks.push(`<div class="mark" style="left:${pct(s.t_s[s.t_s.length - 1])}"><span>Home</span></div>`);
    $("marks").innerHTML = marks.join("");
    $("track").style.setProperty("--safe", r.point_of_no_return ? pct(r.point_of_no_return.t_s) : "100%");
  }

  function setTime(t: number) {
    const r = current();
    if (!r) return;
    const s = r.segments;
    app.t = Math.min(Math.max(t, tStart()), tEnd());
    $<HTMLInputElement>("scrubber").value = String(Math.round((1000 * (app.t - tStart())) / Math.max(tEnd() - tStart(), 1)));
    $("clock").textContent = fmtClock(app.t);
    const k = Math.min(s.t_s.findIndex((x) => x >= app.t) < 0 ? s.t_s.length - 1 : s.t_s.findIndex((x) => x >= app.t), s.t_s.length - 1);
    const lon = interp(s.t_s, r.geometry.coordinates.map((c) => c[0]), app.t);
    const lat = interp(s.t_s, r.geometry.coordinates.map((c) => c[1]), app.t);
    scene.moveAstronaut(lon, lat);
    env.setTime(app.t);
    charts.setTime(app.t);
    const o2 = 0.6 - interp(s.t_s, s.o2_kg, app.t);
    $("o2-now").textContent = `${o2.toFixed(3)} kg`;
    const slack = app.t > s.t_s[s.t_s.length - 1] ? (app.envelope?.deadline_field.t_max_s ?? app.t) - app.t : s.slack_s[k];
    $("slack-now").textContent = slack < -1e8 ? "outside" : slack < 0 ? `-${fmtClock(-slack)} h` : `${fmtClock(slack)} h`;
    $("slack-now").style.color = slack < 0 ? "var(--critical)" : "";
    if (app.envelope) {
      const f = app.envelope.frames;
      $("area").textContent = `${interp(f.map((x) => x.t_s), f.map((x) => x.area_km2), app.t).toFixed(2)} km²`;
    }
  }

  // --- timeline ----------------------------------------------------------------------------
  let last = 0;
  const speed = () => Math.max((tEnd() - tStart()) / 24, 60); // whole EVA in about 24 s
  function frame(ts: number) {
    if (!app.playing) return;
    const dt = last ? (ts - last) / 1000 : 0;
    last = ts;
    setTime(app.t + dt * speed());
    if (app.t >= tEnd()) { play(false); return; }
    requestAnimationFrame(frame);
  }
  function play(on: boolean) {
    app.playing = on;
    $("play-icon").setAttribute("d", on ? "M6 4 H10 V20 H6 Z M14 4 H18 V20 H14 Z" : "M7 4 L20 12 L7 20 Z");
    $("play").setAttribute("aria-label", on ? "Pause" : "Play");
    if (on) {
      if (app.t >= tEnd()) setTime(tStart());
      last = 0;
      requestAnimationFrame(frame);
    }
  }
  $("play").addEventListener("click", () => play(!app.playing));
  $<HTMLInputElement>("scrubber").addEventListener("input", (e) => {
    play(false);
    setTime(tStart() + (Number((e.target as HTMLInputElement).value) / 1000) * (tEnd() - tStart()));
  });
  document.addEventListener("keydown", (e) => {
    if ((e.target as HTMLElement).tagName === "TEXTAREA" || (e.target as HTMLElement).tagName === "INPUT") return;
    if (e.code === "Space") { e.preventDefault(); play(!app.playing); }
  });

  // --- hazard injection mid-EVA ------------------------------------------------------------
  async function inject(h: Hazard) {
    const r = current();
    if (!r) return;
    if (!api.state.online) return toast("Live replanning needs the planner API (make dev).");
    play(false);
    const s = r.segments;
    if (r.objective !== "abort" && app.t >= s.t_s[s.t_s.length - 1] - 120) {
      return toast("The crew member is already back at the habitat at this time. Scrub back to a point on the route first.");
    }
    const lon = interp(s.t_s, r.geometry.coordinates.map((c) => c[0]), app.t);
    const lat = interp(s.t_s, r.geometry.coordinates.map((c) => c[1]), app.t);
    const o2 = 0.6 - interp(s.t_s, s.o2_kg, app.t), batt = 800 - interp(s.t_s, s.batt_wh, app.t);
    toast(`${h === "dust_storm" ? "Dust storm" : "Suit leak"} declared at T+${fmtClock(app.t)}. Replanning from the current position...`, 3000);
    try {
      const reached = r.stops.filter((x) => x.kind === "target" && x.index != null && s.t_s[x.index] <= app.t).map((x) => x.id);
      const remaining = r.stops.filter((x) => x.kind === "target" && x.id && !reached.includes(x.id)).map((x) => x.id);
      const res = await api.replan(lat, lon, app.t, o2, batt, h, remaining, Number(hours.value));
      for (const x of res.routes) if (x.objective === "safest") x.label = "Continue (safest)";
      app.selected = res.recommendation === "abort" ? "abort" : (res.routes[1]?.objective ?? "abort");
      await showRoutes(res.routes);
      toast(res.recommendation === "abort" ? "Recommendation: abort and walk home on the dashed route." : "Recommendation: continue, margins hold.", 6000);
    } catch (e) {
      toast(`Replan failed: ${e instanceof Error ? e.message : e}`);
    }
  }
  $("inject-dust").addEventListener("click", () => inject("dust_storm"));
  $("inject-leak").addEventListener("click", () => inject("suit_fault"));

  new Drawer({
    showValidation: (v) => scene.showValidation(v),
    setEnvelopeVisible: (v) => { env.visible = v && $<HTMLInputElement>("ly-envelope").checked; },
    showRoutes: (routes) => { void showRoutes(routes); },
  });

  $("plan-btn").addEventListener("click", plan);
  $("readout-toggle").addEventListener("click", () => $("readout").classList.toggle("show-mobile"));
  await plan();
}

boot().catch((e) => {
  console.error(e);
  toast(`Startup failed: ${e instanceof Error ? e.message : e}`, 15000);
});
