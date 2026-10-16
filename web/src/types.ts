export type Objective = "safest" | "fastest" | "science" | "abort";
export type Hazard = "dust_storm" | "suit_fault";

export interface Bounds { west: number; south: number; east: number; north: number }

export interface Segments {
  dist_m: number[]; elev_m: number[]; slope_deg: number[]; t_s: number[]; o2_kg: number[]; batt_wh: number[]; slack_s: number[];
}

export interface RoutePoint { index: number; lat: number; lon: number; t_s: number; slack_s?: number; reason?: string }

export interface Route {
  id: string;
  objective: Objective;
  label: string;
  geometry: { type: "LineString"; coordinates: [number, number, number][] };
  segments: Segments;
  stops: { id: string; name: string; kind: string; value: number; lat: number; lon: number; index: number | null }[];
  totals: {
    distance_m: number; duration_s: number; o2_kg: number; batt_wh: number; o2_remaining_kg: number; batt_remaining_wh: number;
    o2_reserve_kg: number; batt_reserve_wh: number; max_slope_deg: number; mean_hazard: number; science_score: number;
    stops: number; feasible: boolean; within_duration: boolean;
  };
  point_of_no_return?: RoutePoint;
  tightest_point?: RoutePoint;
}

export interface RouteResponse { routes: Route[]; assumptions_version: string; hazard?: Hazard | null; recommendation?: string }

export interface Envelope {
  route_id: string;
  frames: { t_s: number; area_km2: number }[];
  point_of_no_return: RoutePoint | null;
  tightest_point: RoutePoint | null;
  deadline_field: { url: string; bounds: Bounds; t_max_s: number };
}

export interface Target {
  id: string; name: string; lat: number; lon: number; science_tags: string[]; note: string; waypoint_sol: number;
  elev_m: number; science_value: number;
}

export interface Site {
  habitat: { name: string; lat: number; lon: number; elev_m: number; snap_note: string };
  grid: { bounds: Bounds; res_m: number };
  dtm_footprint: Bounds;
}

export interface ProvenanceEntry {
  id: string; mission: string; instrument: string; product_id: string; url: string; resolution_m: number | null;
  acquired: string; units: string; processing: string[];
}

export interface Conditions {
  sol: number; terrestrial_date: string; temp_c: { min: number | null; max: number | null }; pressure_pa: number | null;
  season: string; ls_deg: number; sunrise: string; sunset: string; source: { url: string; note: string };
}

export interface Validation {
  sol_from: number; sol_to: number; mean_deviation_m: number; frechet_m: number;
  planned: { coordinates: [number, number][]; length_m: number };
  actual: { coordinates: [number, number][]; length_m: number };
  note: string;
}

export interface Citation { n: number; title: string; url: string; page: number }

export interface AssistantResponse {
  answer: string; citations: Citation[]; routes: Route[]; mode: "live" | "offline";
  verification: { passed: boolean; unverified: { text: string; start: number; end: number }[]; verified_count: number };
  tool_calls: { name: string; input: Record<string, unknown> }[];
  constraints: Record<string, unknown> | null;
}
