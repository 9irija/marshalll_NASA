export type Objective = "safest" | "fastest" | "science" | "abort";
export type Hazard = "dust_storm" | "suit_fault" | "solar_particle_event";
export type Mode = "walk" | "rover";

export interface Bounds { west: number; south: number; east: number; north: number }

export interface Segments {
  dist_m: number[]; elev_m: number[]; slope_deg: number[]; t_s: number[]; o2_kg: number[]; batt_wh: number[]; slack_s: number[];
}

export interface RoutePoint { index: number; lat: number; lon: number; t_s: number; slack_s?: number; reason?: string }

export interface DeadZone { start_index: number; end_index: number; t_start_s: number; duration_s: number; lat: number; lon: number }

export interface RouteContext {
  comms: { line_of_sight_fraction: number; dead_zones: DeadZone[]; time_out_of_contact_s: number; longest_dead_zone_s: number;
    habitat_antenna_m: number; suit_antenna_m: number };
  geology: { symbol: string; name: string; t_start_s: number; distance_m: number }[];
  radiation: { gcr_dose_msv: number; dose_rate_msv_per_day: number; career_limit_msv: number; career_fraction: number;
    max_time_to_shelter_s: number; max_shelter_lat: number; max_shelter_lon: number; sep_warning_s: number; shelter_mode: string;
    sep_shelter_ok: boolean; time_beyond_shelter_s: number };
}

export interface Route {
  id: string;
  objective: Objective;
  mode?: Mode;
  context?: RouteContext;
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

export interface RouteResponse {
  routes: Route[]; assumptions_version: string; hazard?: Hazard | null; recommendation?: string;
  shelter?: { time_to_habitat_s: number; warning_s: number; within_warning: boolean };
}

export interface SimilarCandidate {
  lat: number; lon: number; similarity: number; est_round_trip_s: number; geology: { symbol: string; name: string } | null;
  ml_unit: number; science_value: number;
}

export interface Similar {
  query: { lat: number; lon: number; geology: { symbol: string; name: string } | null; ml_unit: number;
    distinctive: { feature: string; robust_z: number }[] };
  candidates: SimilarCandidate[];
  similarity_map: { url: string; bounds: Bounds };
  model: { features: string[]; kmeans_k: number; validation: { nmi_vs_usgs: number; nmi_shuffled: number;
    similarity_lift: { usgs_unit: string; base_rate: number; top5pct_same_unit: number; lift: number }[];
    purity: { ml_unit: number; majority_usgs: string; purity: number }[];
    spatial_holdout?: { east_nmi: number; east_mean_lift: number;
      supervised: Record<string, { balanced_accuracy: number; chance: number; accuracy: number; majority_baseline: number }> } } };
  note: string;
}

export interface SpaceWeather {
  status: "quiet" | "watch"; window: { start: string; end: string }; cache: { fetched?: string };
  mars_cme_impacts: { cme_id: string; cme_start: string; speed_kms: number; predicted_arrival_at_mars: string; glancing_blow: boolean; link: string }[];
  upcoming_mars_impacts: { cme_id: string; predicted_arrival_at_mars: string; speed_kms: number; glancing_blow: boolean; link: string }[];
  sep_events: { id: string; time: string }[]; flares_m_or_x: { class: string; peak: string }[];
  baseline: { gcr_dose_msv_per_day: number; source: string }; rule: string; limits: string; source: { url: string };
}

export interface PovImage { camera: string; sol: number; utc: string; mast_az_deg: number | null; url: string; thumb: string; page: string; title: string; credit: string }
export interface Pov { source: string; credit: string; note: string; stops: Record<string, { name: string; sol: number; images: PovImage[] }> }

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
