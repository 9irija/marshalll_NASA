import { defineConfig } from "vite";
import { viteStaticCopy } from "vite-plugin-static-copy";
import { fileURLToPath } from "node:url";

const cesiumSource = "node_modules/cesium/Build/Cesium";

export default defineConfig({
  resolve: {
    // Use Cesium's prebuilt ESM bundle; pre-bundling the sources trips over @zip.js exports.
    alias: [{ find: /^cesium$/, replacement: fileURLToPath(new URL(`./${cesiumSource}/index.js`, import.meta.url)) }],
  },
  optimizeDeps: { exclude: ["cesium"] },
  plugins: [
    viteStaticCopy({
      targets: ["Workers", "ThirdParty", "Assets", "Widgets"].map((d) => ({ src: `${cesiumSource}/${d}`, dest: "cesium" })),
    }),
  ],
  build: { chunkSizeWarningLimit: 6000 },
  server: { port: 5173 },
});
