import * as Cesium from "cesium";
import { MARS } from "./mars";
import type { Bounds } from "./types";

/**
 * Return envelope drawn on the GPU. The API ships one texture holding each cell's deadline T(X)
 * (the last moment it is still possible to get home from X with reserve). At EVA time t the envelope
 * is {T >= t}: a single uniform update per frame, so scrubbing is perfectly smooth.
 */
const SOURCE = /* glsl */ `
uniform sampler2D image;
uniform float threshold;
uniform vec4 fillColor;
uniform vec4 edgeColor;
uniform vec4 lostColor;
czm_material czm_getMaterial(czm_materialInput materialInput) {
  czm_material m = czm_getDefaultMaterial(materialInput);
  vec4 s = texture(image, materialInput.st);
  float T = s.r;
  float valid = smoothstep(0.2, 0.8, s.a);
  float w = max(fwidth(T) * 1.4, 0.002);
  float inside = smoothstep(threshold - w, threshold + w, T) * valid;
  float edge = (1.0 - smoothstep(0.0, w * 1.1, abs(T - threshold))) * valid;
  float lost = (1.0 - inside) * valid * step(0.0005, threshold);
  vec3 col = mix(lostColor.rgb, fillColor.rgb, inside);
  col = mix(col, edgeColor.rgb, edge);
  m.diffuse = col;
  m.emission = edgeColor.rgb * edge * 0.6;
  m.alpha = max(max(inside * fillColor.a, lost * lostColor.a), edge * edgeColor.a);
  return m;
}`;

let serial = 0;

export class EnvelopeLayer {
  private primitive?: Cesium.GroundPrimitive;
  private material?: Cesium.Material;
  tMax = 1;

  constructor(private scene: Cesium.Scene) {}

  set(url: string, bounds: Bounds, tMax: number) {
    this.clear();
    this.tMax = tMax;
    this.material = new Cesium.Material({
      fabric: {
        // unique type per texture: Cesium caches material definitions by type name
        type: `MarswalkEnvelope${++serial}`,
        uniforms: {
          image: url, threshold: 0,
          fillColor: Cesium.Color.fromCssColorString("#2fd1a6").withAlpha(0.13),
          edgeColor: Cesium.Color.fromCssColorString("#7ff5d2").withAlpha(0.95),
          lostColor: Cesium.Color.fromCssColorString("#e34948").withAlpha(0.16),
        },
        source: SOURCE,
      },
      translucent: true,
    });
    this.material.uniforms.image = url;
    this.primitive = this.scene.groundPrimitives.add(new Cesium.GroundPrimitive({
      geometryInstances: new Cesium.GeometryInstance({
        geometry: new Cesium.RectangleGeometry({
          rectangle: Cesium.Rectangle.fromDegrees(bounds.west, bounds.south, bounds.east, bounds.north),
          ellipsoid: MARS, vertexFormat: Cesium.EllipsoidSurfaceAppearance.VERTEX_FORMAT,
        }),
      }),
      appearance: new Cesium.EllipsoidSurfaceAppearance({ aboveGround: false, material: this.material }),
      classificationType: Cesium.ClassificationType.TERRAIN,
      asynchronous: false,
    }));
  }

  /** t in seconds since EVA start. */
  setTime(t: number) {
    if (this.material) this.material.uniforms.threshold = Math.min(Math.max(t / this.tMax, 0), 1);
  }

  set visible(v: boolean) {
    if (this.primitive) this.primitive.show = v;
  }

  clear() {
    if (this.primitive) this.scene.groundPrimitives.remove(this.primitive);
    this.primitive = undefined;
    this.material = undefined;
  }
}
