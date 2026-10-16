import * as Cesium from "cesium";
import { DATA } from "./api";
import type { Objective, Route, RoutePoint, Site, Target, Validation } from "./types";

export const ROUTE_COLORS: Record<Objective, string> = {
  safest: "#3987e5", fastest: "#c98500", science: "#9085e9", abort: "#e9eef2",
};
const FONT = "600 13px Archivo, system-ui, sans-serif";
const CLAMP = Cesium.HeightReference.CLAMP_TO_GROUND;

function svgPin(fill: string, glyph: string): string {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="34" height="44" viewBox="0 0 34 44">
<path d="M17 43 C17 43 3 27 3 16 A14 14 0 1 1 31 16 C31 27 17 43 17 43Z" fill="${fill}" stroke="#0f1c27" stroke-width="2"/>
<g fill="#0f1c27">${glyph}</g></svg>`;
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}
const GLYPH = {
  habitat: `<path d="M9 21 A8 8 0 0 1 25 21 Z"/><rect x="8" y="21" width="18" height="2.5" rx="1"/>`,
  target: `<circle cx="17" cy="16" r="5.5" fill="none" stroke="#0f1c27" stroke-width="2.4"/><circle cx="17" cy="16" r="1.8"/>`,
  pnr: `<rect x="15.5" y="8" width="3" height="10" rx="1.2"/><circle cx="17" cy="22" r="1.8"/>`,
  tight: `<path d="M17 8 L24 20 L10 20 Z" fill="none" stroke="#0f1c27" stroke-width="2.2"/>`,
};

function label(text: string, offsetY = -48): Cesium.LabelGraphics.ConstructorOptions {
  return {
    text, font: FONT, fillColor: Cesium.Color.fromCssColorString("#e9eef2"), outlineColor: Cesium.Color.fromCssColorString("#0f1c27"),
    outlineWidth: 4, style: Cesium.LabelStyle.FILL_AND_OUTLINE, pixelOffset: new Cesium.Cartesian2(0, offsetY),
    heightReference: CLAMP, disableDepthTestDistance: Number.POSITIVE_INFINITY, showBackground: false,
    distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, 40000),
  };
}

export class SceneLayer {
  private routeEntities = new Map<string, Cesium.Entity[]>();
  private markers: Cesium.Entity[] = [];
  private validation: Cesium.Entity[] = [];
  private traverse?: Cesium.DataSource;
  astronaut: Cesium.Entity;

  constructor(private viewer: Cesium.Viewer) {
    this.astronaut = viewer.entities.add({
      position: Cesium.Cartesian3.fromDegrees(0, 0),
      point: { pixelSize: 14, color: Cesium.Color.fromCssColorString("#e9eef2"), outlineColor: Cesium.Color.fromCssColorString("#0f1c27"),
        outlineWidth: 3, heightReference: CLAMP, disableDepthTestDistance: Number.POSITIVE_INFINITY },
      show: false,
    });
  }

  addSite(site: Site, targets: Target[], onPick: (id: string) => void) {
    const e = this.viewer.entities;
    this.habitat = site.habitat;
    e.add({
      id: "habitat", position: Cesium.Cartesian3.fromDegrees(site.habitat.lon, site.habitat.lat),
      billboard: { image: svgPin("#d9a066", GLYPH.habitat), verticalOrigin: Cesium.VerticalOrigin.BOTTOM, heightReference: CLAMP,
        disableDepthTestDistance: Number.POSITIVE_INFINITY },
      label: label("Habitat"),
    });
    for (const t of targets) {
      e.add({
        id: `target:${t.id}`, position: Cesium.Cartesian3.fromDegrees(t.lon, t.lat),
        billboard: { image: svgPin("#e9eef2", GLYPH.target), verticalOrigin: Cesium.VerticalOrigin.BOTTOM, heightReference: CLAMP,
          disableDepthTestDistance: Number.POSITIVE_INFINITY, scale: 0.85 },
        label: label(t.name.replace(/ \(.*\)$/, ""), -42),
      });
    }
    const handler = new Cesium.ScreenSpaceEventHandler(this.viewer.scene.canvas);
    handler.setInputAction((ev: { position: Cesium.Cartesian2 }) => {
      const picked = this.viewer.scene.pick(ev.position);
      const id = picked?.id?.id as string | undefined;
      if (id?.startsWith("target:")) onPick(id.slice(7));
    }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
  }

  async showTraverse(show: boolean) {
    if (!this.traverse) {
      this.traverse = await Cesium.GeoJsonDataSource.load(`${DATA}/traverse.json`, {
        clampToGround: true, stroke: Cesium.Color.fromCssColorString("#e9eef2").withAlpha(0.55), strokeWidth: 2,
      });
      await this.viewer.dataSources.add(this.traverse);
    }
    this.traverse.show = show;
  }

  setRoutes(routes: Route[], selected: Objective) {
    for (const ents of this.routeEntities.values()) ents.forEach((x) => this.viewer.entities.remove(x));
    this.routeEntities.clear();
    for (const r of routes) {
      const pos = Cesium.Cartesian3.fromDegreesArray(r.geometry.coordinates.flatMap(([lon, lat]) => [lon, lat]));
      const sel = r.objective === selected;
      const under = this.viewer.entities.add({
        polyline: { positions: pos, width: sel ? 9 : 6, clampToGround: true, material: Cesium.Color.fromCssColorString("#0f1c27").withAlpha(0.75), zIndex: sel ? 3 : 1 },
      });
      const line = this.viewer.entities.add({
        id: `route:${r.objective}`,
        polyline: {
          positions: pos, width: sel ? 5 : 3, clampToGround: true, zIndex: sel ? 4 : 2,
          material: r.objective === "abort"
            ? new Cesium.PolylineDashMaterialProperty({ color: Cesium.Color.WHITE, dashLength: 18 })
            : Cesium.Color.fromCssColorString(ROUTE_COLORS[r.objective]).withAlpha(sel ? 1 : 0.6),
        },
      });
      this.routeEntities.set(r.objective, [under, line]);
    }
  }

  setMarkers(pnr: RoutePoint | null | undefined, tight: RoutePoint | null | undefined) {
    this.markers.forEach((m) => this.viewer.entities.remove(m));
    this.markers = [];
    if (pnr) {
      this.markers.push(this.viewer.entities.add({
        position: Cesium.Cartesian3.fromDegrees(pnr.lon, pnr.lat),
        billboard: { image: svgPin("#e34948", GLYPH.pnr), verticalOrigin: Cesium.VerticalOrigin.BOTTOM, heightReference: CLAMP,
          disableDepthTestDistance: Number.POSITIVE_INFINITY },
        label: label("Point of no return"),
      }));
    } else if (tight && tight.index > 0 && !this.nearHabitat(tight)) {
      this.markers.push(this.viewer.entities.add({
        position: Cesium.Cartesian3.fromDegrees(tight.lon, tight.lat),
        billboard: { image: svgPin("#2fd1a6", GLYPH.tight), verticalOrigin: Cesium.VerticalOrigin.BOTTOM, heightReference: CLAMP,
          disableDepthTestDistance: Number.POSITIVE_INFINITY, scale: 0.8 },
        label: label("Tightest margin", -40),
      }));
    }
  }

  habitat?: { lat: number; lon: number };

  private nearHabitat(pt: { lat: number; lon: number }) {
    if (!this.habitat) return false;
    const dy = (pt.lat - this.habitat.lat) * 59274, dx = (pt.lon - this.habitat.lon) * 56230;
    return Math.hypot(dx, dy) < 150;
  }

  moveAstronaut(lon: number, lat: number) {
    this.astronaut.position = new Cesium.ConstantPositionProperty(Cesium.Cartesian3.fromDegrees(lon, lat));
    this.astronaut.show = true;
  }

  showValidation(v: Validation | null) {
    this.validation.forEach((x) => this.viewer.entities.remove(x));
    this.validation = [];
    // while comparing with the rover, hide our EVA routes so the two lines read clearly
    for (const ents of this.routeEntities.values()) ents.forEach((e) => (e.show = !v));
    this.markers.forEach((m) => (m.show = !v));
    this.astronaut.show = !v;
    if (!v) return;
    const mk = (coords: [number, number][], color: string, dashed: boolean) => this.viewer.entities.add({
      polyline: {
        positions: Cesium.Cartesian3.fromDegreesArray(coords.flat()), width: 4, clampToGround: true, zIndex: 6,
        material: dashed ? new Cesium.PolylineDashMaterialProperty({ color: Cesium.Color.fromCssColorString(color), dashLength: 14 })
          : Cesium.Color.fromCssColorString(color),
      },
    });
    this.validation.push(mk(v.actual.coordinates, "#e9eef2", true), mk(v.planned.coordinates, "#d9a066", false));
    const all = [...v.actual.coordinates, ...v.planned.coordinates];
    const lons = all.map((c) => c[0]), lats = all.map((c) => c[1]);
    const pad = 0.004;
    this.flyToBounds(Math.min(...lons) - pad, Math.min(...lats) - pad, Math.max(...lons) + pad, Math.max(...lats) + pad, -55);
  }

  flyToBounds(w: number, s: number, e: number, n: number, pitchDeg = -38) {
    const c = Cesium.Rectangle.center(Cesium.Rectangle.fromDegrees(w, s, e, n));
    const lon = Cesium.Math.toDegrees(c.longitude), lat = Cesium.Math.toDegrees(c.latitude);
    const span = Math.max(e - w, n - s) * 59000;
    this.viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(lon, lat - (span / 59000) * 1.05, -2550 + span * 0.85),
      orientation: { heading: 0, pitch: Cesium.Math.toRadians(pitchDeg), roll: 0 }, duration: 2.2,
    });
  }
}
