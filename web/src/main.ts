import "cesium/Build/Cesium/Widgets/widgets.css";
import "./style.css";
import * as Cesium from "cesium";
import * as api from "./api";
import { Charts, fmtClock, interp } from "./charts";
import { Drawer } from "./drawers";
import { EnvelopeLayer } from "./envelope";
import { Hud } from "./hud";
import { addLocalOrtho, addOverlay, createTerrain, createViewer } from "./mars";
import { ROUTE_COLORS, SceneLayer } from "./scene";
import type { Envelope, Hazard, Mode, Objective, Pov, Route, Similar, Site, Target } from "./types";

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const esc = (s: string) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;

const OVERLAYS: { id: string; name: string; alpha: number }[] = [
  { id: "science", name: "Science value (CRISM)", alpha: 0.85 },
  { id: "geology", name: "Geologic units (USGS)", alpha: 0.65 },
  { id: "thermal_night", name: "Night thermal (THEMIS)", alpha: 0.6 },
  { id: "comms", name: "Comms dead zones", alpha: 0.75 },
  { id: "ml_units", name: "ML terrain units", alpha: 0.7 },
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
  point: null as { lat: number; lon: number; name: string } | null,
  mode: "walk" as Mode,
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
  const [terrain, site, targets, meta] = await Promise.all([createTerrain(), api.getSite(), api.getTargets(), api.layersMeta()]);
  app.site = site;
  app.targets = targets;
  const { viewer, base } = await createViewer($("globe"), terrain.provider);
  const ortho = await addLocalOrtho(viewer, site.grid.bounds);
  const scene = new SceneLayer(viewer);
  const env = new EnvelopeLayer(viewer.scene);
  const charts = new Charts($("chart-elev"), $("chart-cons"));
  const hud = new Hud(viewer, () => {
    play(false);
    scene.astronaut.show = true;
    env.visible = $<HTMLInputElement>("ly-envelope").checked;
    scene.flyToBounds(site.grid.bounds.west, site.grid.bounds.south, site.grid.bounds.east, site.grid.bounds.north);
  });
  (window as unknown as { __marswalk: unknown }).__marswalk = { viewer, scene, app, hud };
  scene.addSite(site, targets, (id) => { $<HTMLSelectElement>("target").value = id; app.target = id; app.point = null; showTargetNote(); plan(); });
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
  sel.addEventListener("change", () => { app.target = sel.value; app.point = null; showTargetNote(); renderPov(); });
  const hours = $<HTMLInputElement>("hours");
  hours.addEventListener("input", () => ($("hours-out").textContent = `${hours.value} h`));
  document.querySelectorAll<HTMLInputElement>("input[name=mode]").forEach((r) => r.addEventListener("change", () => {
    app.mode = r.value as Mode;
    void plan();
  }));

  const layerList = $("layer-list");
  const handles = new Map<string, Cesium.ImageryLayer>();
  for (const o of OVERLAYS) {
    const b = o.id === "ml_units" && meta.ml_bounds ? meta.ml_bounds : site.grid.bounds;
    try { handles.set(o.id, await addOverlay(viewer, `${o.id}.png`, b, o.alpha)); } catch { /* layer not built */ }
  }
  const geoLegend = (meta.geology_legend ?? []).filter((u) => u.aoi_fraction > 0.001)
    .map((u) => `<span><i style="background:rgb(${u.colour.join(",")})"></i>${esc(u.name.replace(/ unit$/, ""))}</span>`).join("");
  layerList.innerHTML = [
    `<div class="layer-row"><input type="checkbox" id="ly-hirise" checked><label for="ly-hirise">HiRISE 25 cm imagery</label><span></span></div>`,
    `<div class="layer-row"><input type="checkbox" id="ly-traverse"><label for="ly-traverse">Perseverance traverse</label><span></span></div>`,
    `<div class="layer-row"><input type="checkbox" id="ly-envelope" checked><label for="ly-envelope">Return envelope</label><span></span></div>`,
    ...OVERLAYS.filter((o) => handles.has(o.id)).map((o) => `<div class="layer-row"><input type="checkbox" id="ly-${o.id}"><label for="ly-${o.id}">${o.name}</label>
      <input type="range" min="0" max="1" step="0.05" value="${o.alpha}" id="op-${o.id}" aria-label="${o.name} opacity"></div>`
      + (o.id === "geology" ? `<div class="geo-legend" id="geo-legend" hidden>${geoLegend}</div>` : "")),
    `<div class="layer-row"><input type="checkbox" id="ly-exag" checked><label for="ly-exag">Vertical exaggeration 1.5x</label><span></span></div>`,
  ].join("");
  $<HTMLInputElement>("ly-hirise").addEventListener("change", (e) => (base.hirise.show = (e.target as HTMLInputElement).checked));
  $<HTMLInputElement>("ly-traverse").addEventListener("change", (e) => scene.showTraverse((e.target as HTMLInputElement).checked));
  $<HTMLInputElement>("ly-envelope").addEventListener("change", (e) => (env.visible = (e.target as HTMLInputElement).checked));
  $<HTMLInputElement>("ly-exag").addEventListener("change", (e) => (viewer.scene.verticalExaggeration = (e.target as HTMLInputElement).checked ? 1.5 : 1));
  for (const o of OVERLAYS) {
    if (!handles.has(o.id)) continue;
    $<HTMLInputElement>(`ly-${o.id}`).addEventListener("change", (e) => {
      const on = (e.target as HTMLInputElement).checked;
      handles.get(o.id)!.show = on;
      if (o.id === "geology") $("geo-legend").hidden = !on;
    });
    $<HTMLInputElement>(`op-${o.id}`).addEventListener("input", (e) => (handles.get(o.id)!.alpha = Number((e.target as HTMLInputElement).value)));
  }

  api.getConditions().then((c) => {
    $("conditions").innerHTML = `Weather at Jezero, sol ${c.sol} (${c.terrestrial_date}, MEDA): <strong>${c.temp_c.min ?? "?"} to ${c.temp_c.max ?? "?"} &deg;C</strong>,
      <strong>${c.pressure_pa ?? "?"} Pa</strong>, ${c.season}; sunrise ${c.sunrise}, sunset ${c.sunset}.`;
  }).catch(() => undefined);
  api.spaceWeather().then((w) => {
    const up = w.upcoming_mars_impacts[0];
    const last = w.mars_cme_impacts[w.mars_cme_impacts.length - 1];
    const d = (s: string) => s.replace("T", " ").replace("Z", " UTC");
    $("spacewx").innerHTML = `<span class="wx-status ${w.status}">${w.status === "watch" ? "CME watch" : "Quiet"}</span>
      Space weather (NASA DONKI, ${w.window.start} to ${w.window.end}):
      ${up ? `<strong>CME predicted at Mars ${d(up.predicted_arrival_at_mars)}</strong> (${up.speed_kms} km/s${up.glancing_blow ? ", glancing" : ""}).`
        : last ? `last CME modelled at Mars ${d(last.predicted_arrival_at_mars)} (${last.speed_kms} km/s); none predicted ahead.` : "no CMEs modelled at Mars."}
      ${w.sep_events.length} SEP event(s), ${w.flares_m_or_x.length} M/X flare(s). GCR baseline <strong>${w.baseline.gcr_dose_msv_per_day} mSv/day</strong> (MSL RAD).
      <a href="${esc(w.source.url)}" target="_blank" rel="noopener">DONKI</a>`;
    $("spacewx").title = w.limits;
  }).catch(() => undefined);

  // --- point of view: Perseverance raw images at the destination --------------------------------
  let pov: Pov | null = null;
  async function renderPov() {
    try { pov ??= await api.pov(); } catch { $("pov").innerHTML = ""; return; }
    const id = app.point ? null : app.target;
    const st = id ? pov.stops[id] : null;
    if (!st || !st.images.length) { $("pov").innerHTML = `<p class="cap">No rover images for this point.</p>`; return; }
    $("pov-title").textContent = `What you will see at ${st.name.replace(/ \(.*\)$/, "")}`;
    $("pov").innerHTML = st.images.slice(0, 6).map((im, i) => `<button data-i="${i}" aria-label="${esc(im.title)}"><img loading="lazy" src="${esc(im.thumb)}" alt="${esc(im.title)}"></button>`).join("")
      + `<p class="cap">Perseverance, sol ${st.sol}: ${[...new Set(st.images.map((x) => x.camera))].join(", ")}. Raw images, ${esc(pov.credit)}.</p>`;
    $("pov").querySelectorAll<HTMLButtonElement>("button").forEach((b) => b.addEventListener("click", () => {
      const im = st.images[Number(b.dataset.i)];
      $<HTMLImageElement>("lightbox-img").src = im.url;
      $<HTMLImageElement>("lightbox-img").alt = im.title;
      $("lightbox-cap").innerHTML = `${esc(im.title)}, ${esc(im.utc)} UTC${im.mast_az_deg != null ? `, mast azimuth ${im.mast_az_deg}&deg;` : ""}. ${esc(im.credit)}. <a href="${esc(im.page)}" target="_blank" rel="noopener">NASA page</a>`;
      $("lightbox").hidden = false;
    }));
  }
  $("lightbox").addEventListener("click", (e) => { if ((e.target as HTMLElement).tagName !== "A") $("lightbox").hidden = true; });
  void renderPov();

  // --- routes ------------------------------------------------------------------------------
  const hazard = (): Hazard | null => ($<HTMLInputElement>("hz-dust").checked ? "dust_storm" : $<HTMLInputElement>("hz-leak").checked ? "suit_fault" : null);

  async function plan() {
    const btn = $<HTMLButtonElement>("plan-btn");
    btn.disabled = true;
    btn.textContent = app.mode === "rover" ? "Planning rover drive..." : "Planning on HiRISE terrain...";
    try {
      const res = await api.planRoute(app.point ?? app.target, Number(hours.value), hazard(), app.mode);
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
    scene.setDeadZones(r);
    app.o2Start = r.totals.o2_remaining_kg + r.totals.o2_kg;
    app.battStart = r.totals.batt_remaining_wh + r.totals.batt_wh;
    const t0 = r.segments.t_s[0];
    if (t0 > 0) { app.o2Start += r.segments.o2_kg[0]; app.battStart += r.segments.batt_wh[0]; }
    charts.setRoute(r, 0.6, 800);
    renderTotals(r);
    renderSituation(r);
    ($("cuff") as HTMLAnchorElement).href = api.state.online ? api.checklistUrl(r.id) : "#";
    try {
      app.envelope = await api.getEnvelope(r, app.target + (app.mode === "rover" ? "_rover" : ""));
      env.set(app.envelope.deadline_field.url, app.envelope.deadline_field.bounds, app.envelope.deadline_field.t_max_s);
      scene.setMarkers(r.point_of_no_return, r.tightest_point);
    } catch (e) {
      app.envelope = null;
      env.clear();
      toast(`Envelope unavailable: ${e instanceof Error ? e.message : e}`);
    }
    renderMarks(r);
    setTime(t0);
    if (!reducedMotion && !app.playing && !hud.active) play(true);
  }

  function renderTotals(r: Route) {
    const t = r.totals;
    const pnr = r.point_of_no_return;
    const st = $("status");
    st.className = `status ${t.feasible ? "ok" : "bad"}`;
    const icon = t.feasible
      ? `<svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true"><circle cx="9" cy="9" r="8" fill="#2fd1a6"/><path d="M5 9.3 L7.8 12 L13 6.5" stroke="#0f1c27" stroke-width="2" fill="none"/></svg>`
      : `<svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true"><path d="M9 1 L17 16 H1 Z" fill="#e34948"/><path d="M9 6 V10.5 M9 12.8 V13" stroke="#0f1c27" stroke-width="2"/></svg>`;
    const walkback = r.mode === "rover" ? " Envelope assumes the rover fails and the crew walks home (walkback rule)." : "";
    const msg = r.objective === "abort"
      ? `Head home now on this route: ${(t.distance_m / 1000).toFixed(2)} km, arriving T+${fmtClock(t.duration_s)} with ${t.o2_remaining_kg.toFixed(3)} kg O2.`
      : pnr
      ? `Not safe as planned. Point of no return at T+${fmtClock(pnr.t_s)}: past it, the crew member cannot get home with reserve.${walkback}`
      : t.feasible
        ? `Can get there, do the science and get home. Tightest margin ${fmtClock(r.tightest_point?.slack_s ?? 0)} h before the envelope closes.${walkback}`
        : `Over budget: ${t.within_duration ? "consumables reserve would be broken." : "longer than the EVA time limit."}`;
    const cautions = [
      r.context?.comms && r.context.comms.longest_dead_zone_s > 900 ? "long radio dead zones" : "",
      r.context?.radiation && !r.context.radiation.sep_shelter_ok ? "too far from shelter for a solar particle alert" : "",
    ].filter(Boolean);
    const caution = r.objective !== "abort" && cautions.length ? ` <span style="color:#ffc861">Cautions: ${cautions.join("; ")}.</span>` : "";
    st.innerHTML = `${icon}<span><b>${r.label}.</b> ${msg}${caution}</span>`;
    $("totals").innerHTML = [
      ["Distance", `${(t.distance_m / 1000).toFixed(2)} <small>km</small>`],
      ["Duration", `${fmtClock(t.duration_s)} <small>h</small>`],
      ["O2 used", `${t.o2_kg.toFixed(3)} <small>kg</small>`],
      ["O2 left at habitat", `${t.o2_remaining_kg.toFixed(3)} <small>kg</small>`],
      ["Battery used", `${t.batt_wh.toFixed(0)} <small>Wh</small>`],
      ["Max slope", `${t.max_slope_deg.toFixed(1)} <small>deg</small>`],
    ].map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("");
  }

  const unitColour = new Map((meta.geology_legend ?? []).map((u) => [u.symbol, `rgb(${u.colour.join(",")})`]));
  function renderSituation(r: Route) {
    const c = r.context;
    if (!c?.comms) { $("situation").innerHTML = ""; return; }
    const dur = Math.max(r.totals.duration_s, 1);
    const cm = c.comms, rad = c.radiation;
    const commsCls = cm.longest_dead_zone_s > 900 ? "bad" : cm.dead_zones.length ? "warn" : "ok";
    const shelterCls = rad.sep_shelter_ok ? "ok" : "bad";
    const total = c.geology.reduce((a, g) => a + g.distance_m, 0) || 1;
    const strip = c.geology.map((g) => `<span title="${esc(g.name)}: ${g.distance_m.toFixed(0)} m" style="flex:${g.distance_m / total};background:${unitColour.get(g.symbol) ?? "#888"}"></span>`).join("");
    const names = [...new Map(c.geology.map((g) => [g.symbol, g])).values()]
      .map((g) => `<span><i style="background:${unitColour.get(g.symbol) ?? "#888"}"></i>${esc(g.name.replace(/ unit$/, ""))}</span>`).join("");
    $("situation").innerHTML = `
      <div class="sit ${commsCls}"><span class="ico"></span><span>Radio line of sight to habitat</span><span class="v">${(cm.line_of_sight_fraction * 100).toFixed(0)}% of route</span>
        <span class="d">${cm.dead_zones.length ? `${cm.dead_zones.length} dead zone(s), ${fmtClock(cm.time_out_of_contact_s)} h out of contact, longest ${fmtClock(cm.longest_dead_zone_s)} h. Purple on the route.` : "Always in contact."}
        Mast ${cm.habitat_antenna_m} m, suit ${cm.suit_antenna_m} m, HiRISE DTM with Mars curvature.</span></div>
      <div class="sit ${shelterCls}"><span class="ico"></span><span>Solar particle event: time to shelter</span><span class="v">${fmtClock(rad.max_time_to_shelter_s)} h max</span>
        <span class="d">Worst case ${rad.shelter_mode} vs the ${fmtClock(rad.sep_warning_s)} h planning rule${rad.sep_shelter_ok ? ": OK." : `: ${fmtClock(rad.time_beyond_shelter_s)} h of the EVA is beyond it.${r.mode !== "rover" ? " Try Rover." : ""}`}</span></div>
      <div class="sit ok"><span class="ico"></span><span>Radiation dose (cosmic rays)</span><span class="v">${rad.gcr_dose_msv.toFixed(3)} mSv</span>
        <span class="d">${rad.dose_rate_msv_per_day} mSv/day measured by MSL RAD at Gale, ${(rad.career_fraction * 100).toFixed(3)}% of the ${rad.career_limit_msv} mSv NASA career limit.</span></div>
      <div class="sit ok"><span class="ico" style="background:var(--butterscotch)"></span><span>Geology underfoot (USGS SIM 3464)</span><span class="v">${c.geology.length} stretch(es)</span>
        <span class="d"><div class="geo-strip">${strip}</div><div class="geo-legend">${names}</div></span></div>`;
    void dur;
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
    $("track").querySelectorAll(".dz").forEach((e) => e.remove());
    for (const z of r.context?.comms.dead_zones ?? []) {
      const d = document.createElement("div");
      d.className = "dz";
      d.title = `No radio line of sight for ${fmtClock(z.duration_s)} h`;
      d.style.left = pct(z.t_start_s);
      d.style.width = `${(100 * z.duration_s) / Math.max(t1 - t0, 1)}%`;
      $("track").appendChild(d);
    }
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
    if (hud.active) { scene.astronaut.show = false; hud.update(r, app.t); }
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
  // whole EVA in about 24 s on the map; in the helmet view, one EVA minute per 0.4 s so the walk reads
  const speed = () => (hud.active ? 150 : Math.max((tEnd() - tStart()) / 24, 60));
  function frame(ts: number) {
    if (!app.playing) return;
    const dt = last ? (ts - last) / 1000 : 0;
    last = ts;
    setTime(app.t + dt * speed());
    const r = current();
    const stopAt = hud.active && r ? r.segments.t_s[r.segments.t_s.length - 1] : tEnd();
    if (app.t >= stopAt) { play(false); return; }
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

  // --- helmet HUD ----------------------------------------------------------------------------
  $("hud-btn").addEventListener("click", () => {
    const r = current();
    if (!r) return toast("Plan a route first.");
    play(false);
    env.visible = false;          // the envelope tint would wash out the ground at eye level
    hud.enter(app.o2Start, app.battStart);
    const s = r.segments;
    setTime(app.t >= s.t_s[s.t_s.length - 1] - 60 ? tStart() : app.t);
    if (!reducedMotion) play(true);
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
    const name = { dust_storm: "Dust storm", suit_fault: "Suit leak", solar_particle_event: "Solar particle alert" }[h];
    toast(`${name} declared at T+${fmtClock(app.t)}. Replanning from the current position...`, 3000);
    try {
      const reached = r.stops.filter((x) => x.kind === "target" && x.index != null && s.t_s[x.index] <= app.t).map((x) => x.id);
      const remaining = r.stops.filter((x) => x.kind === "target" && x.id && !reached.includes(x.id)).map((x) => x.id);
      const res = await api.replan(lat, lon, app.t, o2, batt, h, remaining, Number(hours.value));
      for (const x of res.routes) if (x.objective === "safest") x.label = "Continue (safest)";
      if (h === "solar_particle_event") for (const x of res.routes) if (x.objective === "abort") x.label = "Shelter: walk to habitat now";
      app.selected = res.recommendation === "abort" || res.recommendation === "shelter" ? "abort" : (res.routes[1]?.objective ?? "abort");
      await showRoutes(res.routes);
      if (res.shelter) {
        toast(`Shelter now. Walk to the habitat takes ${fmtClock(res.shelter.time_to_habitat_s)} h against a ${fmtClock(res.shelter.warning_s)} h warning rule: ${res.shelter.within_warning ? "inside it." : "exceeds it, the crew is exposed during onset."}`, 9000);
      } else {
        toast(res.recommendation === "abort" ? "Recommendation: abort and walk home on the dashed route." : "Recommendation: continue, margins hold.", 6000);
      }
    } catch (e) {
      toast(`Replan failed: ${e instanceof Error ? e.message : e}`);
    }
  }
  $("inject-dust").addEventListener("click", () => inject("dust_storm"));
  $("inject-leak").addEventListener("click", () => inject("suit_fault"));
  $("inject-sep").addEventListener("click", () => inject("solar_particle_event"));

  const drawer = new Drawer({
    showValidation: (v) => scene.showValidation(v),
    setEnvelopeVisible: (v) => { env.visible = v && $<HTMLInputElement>("ly-envelope").checked; },
    showRoutes: (routes) => { void showRoutes(routes); },
  });

  // --- ML: find similar ground ------------------------------------------------------------------
  let simLayer: Cesium.ImageryLayer | null = null;
  let sim: Similar | null = null;
  const clearSimilar = () => {
    if (simLayer) { viewer.imageryLayers.remove(simLayer, true); simLayer = null; }
    scene.showCandidates(null, []);
    sim = null;
  };
  const featName: Record<string, string> = { olivine: "olivine", fe_mg_smectite: "Fe/Mg smectite", carbonate: "carbonate", hydration: "hydration",
    night_ir: "night temperature", day_ir: "day temperature", albedo: "brightness", slope: "slope", roughness: "roughness", relief: "local relief" };

  function similarIntro() {
    const t = targets.find((x) => x.id === app.target)!;
    const body = drawer.openCustom("similar", `<h2>Find similar ground <span class="ml-tag">ML</span></h2>
      <p>Pick a spot where the science is good. The model finds the places in the crater that look most like it in the data
      (CRISM minerals, THEMIS day and night temperature, HiRISE brightness, slope, roughness, relief), and keeps only those the crew could reach.</p>
      <p class="hint">The model only proposes places. Choosing one plans a real route, so oxygen, battery and the return envelope are computed by the planner, not the model.</p>
      <div class="readout-actions"><button class="cta" id="sim-target" style="width:auto;margin:0">Ground like ${esc(t.name.replace(/ \(.*\)$/, ""))}</button>
      <button class="ghost" id="sim-pick" ${api.state.online ? "" : "disabled title=\"Needs the planner API\""}>Click a spot on the map</button></div>`);
    body.querySelector("#sim-target")!.addEventListener("click", () => runSimilar(t.lat, t.lon, t.id));
    body.querySelector("#sim-pick")?.addEventListener("click", () => {
      document.body.classList.add("picking");
      toast("Click a spot on the map to search for similar ground.", 4000);
      scene.pickHandler = (lat, lon) => { document.body.classList.remove("picking"); void runSimilar(lat, lon); };
    });
  }

  async function runSimilar(lat: number, lon: number, demoTarget?: string) {
    try {
      clearSimilar();
      drawer.openCustom("similar", `<h2>Find similar ground <span class="ml-tag">ML</span></h2><p class="hint">Searching 187,000 cells...</p>`);
      sim = await api.similar(lat, lon, demoTarget);
      const p = await Cesium.SingleTileImageryProvider.fromUrl(sim.similarity_map.url, {
        rectangle: Cesium.Rectangle.fromDegrees(sim.similarity_map.bounds.west, sim.similarity_map.bounds.south, sim.similarity_map.bounds.east, sim.similarity_map.bounds.north),
      });
      simLayer = viewer.imageryLayers.addImageryProvider(p);
      simLayer.alpha = 0.85;
      scene.showCandidates(sim.query, sim.candidates);
      renderSimilar(sim);
    } catch (e) {
      drawer.openCustom("similar", `<h2>Find similar ground</h2><p>${esc(e instanceof Error ? e.message : String(e))}</p>`);
    }
  }

  function renderSimilar(s: Similar) {
    const v = s.model.validation;
    const q = s.query;
    const why = q.distinctive.map((d) => `${d.robust_z > 0 ? "high" : "low"} ${featName[d.feature] ?? d.feature}`).join(", ");
    const body = drawer.openCustom("similar", `<h2>Similar ground <span class="ml-tag">ML</span></h2>
      <p>Query: ${q.geology ? esc(q.geology.name) : "unmapped"}. What stands out there: <strong>${esc(why)}</strong>.
      Yellow on the map = top 20% most similar ground (brighter = closer match).</p>
      ${s.candidates.map((c, i) => `<div class="cand"><span class="n">${i + 1}</span><span>${c.geology ? esc(c.geology.name) : "Unmapped"}
        <span class="meta">top ${(1 - c.similarity) * 100 < 0.1 ? "&lt;0.1" : ((1 - c.similarity) * 100).toFixed(1)}% match, science ${c.science_value.toFixed(2)}, about ${fmtClock(c.est_round_trip_s)} h round trip (screen)</span></span>
        <button class="ghost" data-c="${i}" ${api.state.online ? "" : "disabled title=\"Needs the planner API\""}>Plan route</button></div>`).join("")
        || `<p>No reachable candidates within this EVA limit.</p>`}
      <h3>How good is the model?</h3>
      <p class="hint">Checked against the USGS geologic map (Sun &amp; Stack 2020), which the model never sees. For queries in each mapped unit,
      the share of the 5% most similar ground that falls in the same unit, against that unit's share of the area:</p>
      <div class="lift">${v.similarity_lift.map((l) => `<span>${esc(l.usgs_unit)}</span><b>${(l.top5pct_same_unit * 100).toFixed(0)}% vs ${(l.base_rate * 100).toFixed(0)}% (${l.lift}x)</b>`).join("")}</div>
      <p class="hint">Unsupervised terrain units (k-means, k = ${s.model.kmeans_k}) agree with the USGS map at normalised mutual information ${v.nmi_vs_usgs.toFixed(2)}
      (shuffled labels: ${v.nmi_shuffled.toFixed(2)}). Agreement is partial by design: the USGS map is drawn at 1:75,000 and its contacts can be offset 100-200 m.</p>
      ${v.spatial_holdout ? `<p class="hint"><strong>Spatial hold-out.</strong> Features were chosen on the west half of the site only. On the unseen east half:
      NMI ${v.spatial_holdout.east_nmi.toFixed(2)}, similarity lift ${v.spatial_holdout.east_mean_lift.toFixed(2)}x. A classifier trained on one half
      predicts the USGS units of the other at balanced accuracy ${v.spatial_holdout.supervised["W->E"].balanced_accuracy.toFixed(2)}
      (chance ${v.spatial_holdout.supervised["W->E"].chance.toFixed(2)}) west to east and ${v.spatial_holdout.supervised["E->W"].balanced_accuracy.toFixed(2)}
      (chance ${v.spatial_holdout.supervised["E->W"].chance.toFixed(2)}) east to west.</p>` : ""}
      <p class="hint">${esc(s.note)}</p>`);
    body.querySelectorAll<HTMLButtonElement>("button[data-c]").forEach((b) => b.addEventListener("click", () => planTo(Number(b.dataset.c))));
  }

  function planTo(i: number) {
    if (!sim) return;
    const c = sim.candidates[i];
    app.point = { lat: c.lat, lon: c.lon, name: `Similar site ${i + 1}` };
    $("target-note").textContent = `Similar site ${i + 1}: ${c.geology?.name ?? "unmapped"}, proposed by the ML search. Routes below are verified by the planner.`;
    void renderPov();
    void plan();
  }
  scene.onCandidate = (i) => planTo(i);
  $("similar-btn").addEventListener("click", () => { if (drawer.openKind === "similar") { drawer.close(); clearSimilar(); } else similarIntro(); });

  $("plan-btn").addEventListener("click", plan);
  $("readout-toggle").addEventListener("click", () => $("readout").classList.toggle("show-mobile"));
  await plan();
}

boot().catch((e) => {
  console.error(e);
  toast(`Startup failed: ${e instanceof Error ? e.message : e}`, 15000);
});
