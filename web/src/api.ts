import type { AssistantResponse, Conditions, Envelope, Hazard, ProvenanceEntry, Route, RouteResponse, Site, Target, Validation } from "./types";

/** API base. With the API down, everything falls back to precomputed files in /data/demo. */
export const API = ((import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8000").replace(/\/$/, "");
export const DATA = "/data";

export const state = { online: false };

async function json<T>(url: string, init?: RequestInit, timeoutMs = 60000): Promise<T> {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const r = await fetch(url, { ...init, signal: ctl.signal });
    if (!r.ok) throw new Error(`${r.status} ${(await r.text()).slice(0, 200)}`);
    return (await r.json()) as T;
  } finally {
    clearTimeout(t);
  }
}

const post = <T>(path: string, body: unknown) =>
  json<T>(`${API}${path}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });

export async function probe(): Promise<boolean> {
  try {
    await json(`${API}/health`, undefined, 2500);
    state.online = true;
  } catch {
    state.online = false;
  }
  return state.online;
}

const demo = <T>(name: string) => json<T>(`${DATA}/demo/${name}`);

export const getSite = () => (state.online ? json<Site>(`${API}/site`) : demo<Site>("site.json"));
export const getTargets = () => (state.online ? json<Target[]>(`${API}/targets`) : demo<Target[]>("targets.json"));
export const getManifest = () =>
  (state.online ? json<{ layers: ProvenanceEntry[] }>(`${API}/manifest`) : demo<{ layers: ProvenanceEntry[] }>("manifest.json"));
export const getAssumptions = () =>
  (state.online ? json<Record<string, unknown>>(`${API}/assumptions`) : demo<Record<string, unknown>>("assumptions.json"));
export const getConditions = (sol?: number) =>
  (state.online ? json<Conditions>(`${API}/conditions${sol ? `?sol=${sol}` : ""}`) : demo<Conditions>("conditions.json"));

export async function planRoute(target: string, hours: number, hazard: Hazard | null): Promise<RouteResponse> {
  if (!state.online) return demo<RouteResponse>(`route_${target}.json`);
  return post<RouteResponse>("/route", { targets: [target], objective: "all", hazard, params: { max_duration_s: hours * 3600 } });
}

export async function getEnvelope(route: Route, target: string): Promise<Envelope> {
  if (!state.online || route.id.startsWith("demo")) {
    const e = await demo<Envelope>(`envelope_${target}_${route.objective}.json`);
    e.deadline_field.url = `${DATA}/${e.deadline_field.url}`;
    return e;
  }
  const e = await post<Envelope>("/envelope", { route_id: route.id, timestep_s: 300, polygons: false });
  e.deadline_field.url = `${API}${e.deadline_field.url}`;
  return e;
}

export function replan(lat: number, lon: number, t_s: number, o2_kg: number, batt_wh: number, hazard: Hazard, targets: string[], hours: number) {
  return post<RouteResponse>("/replan", {
    current_position: { lat, lon }, t_s, remaining: { o2_kg, batt_wh }, hazard, objective: "safest", targets,
    params: { max_duration_s: hours * 3600 },
  });
}

export const validate = () => (state.online ? post<Validation>("/validate", {}) : demo<Validation>("validate.json"));

export const assistant = (messages: { role: "user" | "assistant"; content: string }[]) =>
  post<AssistantResponse>("/assistant", { messages });

export const checklistUrl = (routeId: string) => `${API}/checklist/${routeId}`;
