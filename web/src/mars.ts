import * as Cesium from "cesium";
import { DATA } from "./api";
import type { Bounds } from "./types";

/** Mars 2000 IAU sphere. Set as Cesium's default before any other Cesium object is built. */
export const MARS = new Cesium.Ellipsoid(3396190, 3396190, 3396190);
Cesium.Ellipsoid.default = MARS;
Cesium.Ion.defaultAccessToken = "";

const TREK = "https://trek.nasa.gov/tiles/Mars/EQ";
/** Endpoints discovered from each layer's WMTSCapabilities.xml (default style, default028mm matrix set). */
const TREK_LAYERS = {
  viking: { label: "Mars_Viking_MDIM21_ClrMosaic_global_232m", ext: "jpg", maxLevel: 7, rect: undefined },
  ctx: { label: "JEZ_ctx_B_soc_008_orthoMosaic_6m_Eqc_latTs0_lon0", ext: "png", maxLevel: 15, rect: [77.1604655, 18.2110274, 77.6991776, 18.7211945] },
  hirise: { label: "JEZ_hirise_soc_006_orthoMosaic_25cm_Eqc_latTs0_lon0_first_dd", ext: "png", maxLevel: 19, rect: [77.2229331, 18.3067994, 77.583964, 18.669315] },
} as const;

interface HeightGrid { w: number; h: number; offset: number; scale: number; nodata: number; b: Bounds; q: Uint16Array }

async function loadGrid(name: string): Promise<HeightGrid> {
  const meta = await (await fetch(`${DATA}/${name}.json`)).json();
  const buf = await (await fetch(`${DATA}/${name}.u16`)).arrayBuffer();
  return { w: meta.width, h: meta.height, offset: meta.offset, scale: meta.scale, nodata: meta.nodata, b: meta.bounds, q: new Uint16Array(buf) };
}

/** Bilinear height in metres (areoid) from a grid, or NaN outside / on nodata. */
function sample(g: HeightGrid, lon: number, lat: number): number {
  const x = ((lon - g.b.west) / (g.b.east - g.b.west)) * g.w - 0.5;
  const y = ((g.b.north - lat) / (g.b.north - g.b.south)) * g.h - 0.5;
  if (x < 0 || y < 0 || x > g.w - 1 || y > g.h - 1) return NaN;
  const x0 = Math.floor(x), y0 = Math.floor(y), x1 = Math.min(x0 + 1, g.w - 1), y1 = Math.min(y0 + 1, g.h - 1);
  const fx = x - x0, fy = y - y0;
  const v = [g.q[y0 * g.w + x0], g.q[y0 * g.w + x1], g.q[y1 * g.w + x0], g.q[y1 * g.w + x1]];
  if (v.some((k) => k === g.nodata)) {
    const ok = v.filter((k) => k !== g.nodata);
    return ok.length ? g.offset + g.scale * (ok.reduce((a, b) => a + b, 0) / ok.length) : NaN;
  }
  const top = v[0] * (1 - fx) + v[1] * fx, bot = v[2] * (1 - fx) + v[3] * fx;
  return g.offset + g.scale * (top * (1 - fy) + bot * fy);
}

export interface TerrainHandle { provider: Cesium.CustomHeightmapTerrainProvider; heightAt: (lon: number, lat: number) => number }

/**
 * Terrain from the HiRISE DTM: the AOI at 4 m, the full DTM footprint at 12 m, and a flat plane at the
 * footprint's median height elsewhere. Heights are areoid heights placed on the sphere (a constant
 * vertical offset for the whole scene; documented in docs/ARCHITECTURE.md).
 */
export async function createTerrain(): Promise<TerrainHandle> {
  const [aoi, ctx] = await Promise.all([loadGrid("terrain_aoi"), loadGrid("terrain_context")]);
  const base = -2560;
  const heightAt = (lon: number, lat: number) => {
    const a = sample(aoi, lon, lat);
    if (!Number.isNaN(a)) return a;
    const c = sample(ctx, lon, lat);
    return Number.isNaN(c) ? base : c;
  };
  const N = 65;
  const tiling = new Cesium.GeographicTilingScheme({ ellipsoid: MARS });
  const provider = new Cesium.CustomHeightmapTerrainProvider({
    width: N, height: N, tilingScheme: tiling,
    callback: (x, y, level) => {
      const r = tiling.tileXYToRectangle(x, y, level);
      const w = Cesium.Math.toDegrees(r.west), e = Cesium.Math.toDegrees(r.east);
      const s = Cesium.Math.toDegrees(r.south), n = Cesium.Math.toDegrees(r.north);
      const out = new Float32Array(N * N);
      const touches = !(e < ctx.b.west || w > ctx.b.east || n < ctx.b.south || s > ctx.b.north);
      if (!touches) return out.fill(base);
      for (let j = 0; j < N; j++) {
        const lat = n - ((n - s) * j) / (N - 1);
        for (let i = 0; i < N; i++) out[j * N + i] = heightAt(w + ((e - w) * i) / (N - 1), lat);
      }
      return out;
    },
  });
  return { provider, heightAt };
}

function trek(key: keyof typeof TREK_LAYERS): Cesium.WebMapTileServiceImageryProvider {
  const L = TREK_LAYERS[key];
  return new Cesium.WebMapTileServiceImageryProvider({
    url: `${TREK}/${L.label}/1.0.0//{Style}/{TileMatrixSet}/{TileMatrix}/{TileRow}/{TileCol}.${L.ext}`,
    layer: L.label, style: "default", tileMatrixSetID: "default028mm", format: `image/${L.ext === "jpg" ? "jpeg" : "png"}`,
    tilingScheme: new Cesium.GeographicTilingScheme({ ellipsoid: MARS }), maximumLevel: L.maxLevel,
    rectangle: L.rect ? Cesium.Rectangle.fromDegrees(...L.rect) : undefined,
    credit: new Cesium.Credit("NASA Mars Trek, MRO HiRISE/CTX, Viking"),
  });
}

export async function createViewer(container: HTMLElement, terrain: Cesium.TerrainProvider) {
  const viewer = new Cesium.Viewer(container, {
    globe: new Cesium.Globe(MARS), baseLayer: false, terrainProvider: terrain,
    animation: false, timeline: false, baseLayerPicker: false, geocoder: false, homeButton: false, sceneModePicker: false,
    navigationHelpButton: false, fullscreenButton: false, infoBox: false, selectionIndicator: false,
    skyAtmosphere: new Cesium.SkyAtmosphere(MARS), msaaSamples: 4,
  });
  const scene = viewer.scene;
  scene.globe.showGroundAtmosphere = false;
  scene.globe.baseColor = Cesium.Color.fromCssColorString("#6b4a35");
  scene.globe.depthTestAgainstTerrain = true;
  scene.globe.maximumScreenSpaceError = 1.5;
  scene.verticalExaggeration = 1.5;
  scene.fog.enabled = true;
  scene.fog.density = 1.2e-4;
  // Butterscotch daytime sky of Mars instead of Earth blue.
  if (scene.skyAtmosphere) {
    scene.skyAtmosphere.hueShift = -0.47;
    scene.skyAtmosphere.saturationShift = -0.25;
    scene.skyAtmosphere.brightnessShift = -0.15;
  }
  scene.backgroundColor = Cesium.Color.fromCssColorString("#0f1c27");
  if (scene.sun) scene.sun.show = false;
  if (scene.moon) scene.moon.show = false;

  const layers = viewer.imageryLayers;
  const viking = layers.addImageryProvider(trek("viking"));
  const ctx = layers.addImageryProvider(trek("ctx"));
  const hirise = layers.addImageryProvider(trek("hirise"));
  [viking, ctx, hirise].forEach((l) => { l.brightness = 1.05; l.contrast = 1.1; });
  viking.saturation = 0.7;
  return { viewer, base: { viking, ctx, hirise } };
}

/** Local HiRISE orthoimage as an offline fallback when Trek is unreachable. */
export async function addLocalOrtho(viewer: Cesium.Viewer, bounds: Bounds) {
  const p = await Cesium.SingleTileImageryProvider.fromUrl(`${DATA}/ortho.png`, {
    rectangle: Cesium.Rectangle.fromDegrees(bounds.west, bounds.south, bounds.east, bounds.north),
  });
  const l = viewer.imageryLayers.addImageryProvider(p);
  l.show = false;
  return l;
}

export async function addOverlay(viewer: Cesium.Viewer, file: string, bounds: Bounds, alpha = 0.85) {
  const p = await Cesium.SingleTileImageryProvider.fromUrl(`${DATA}/${file}`, {
    rectangle: Cesium.Rectangle.fromDegrees(bounds.west, bounds.south, bounds.east, bounds.north),
  });
  const l = viewer.imageryLayers.addImageryProvider(p);
  l.alpha = alpha;
  l.show = false;
  return l;
}
