// Marswalk demo deck as an editable PowerPoint (7 slides, 13.33 x 7.5 in).
const path = require("path");
const pptxgen = require("pptxgenjs");
const { applyTheme } = require(process.env.PPTX_SKILL + "/scripts/apply_theme.js");

const SUB = process.argv[2];                    // submission folder
const IMG = (f) => path.join(SUB, "img", f);
const OUT = path.join(SUB, "Marswalk_demo.pptx");

const THEME = {
  name: "Marswalk Dusk",
  headFontFace: "Calibri",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "0F1C27", lt1: "FFFFFF", dk2: "13212E", lt2: "E9EEF2",
    accent1: "D9A066", accent2: "2FD1A6", accent3: "9085E9", accent4: "E34948", accent5: "3987E5", accent6: "A9B8C5",
    hlink: "D9A066", folHlink: "C98500",
  },
};

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
pres.title = "Marswalk Mission Planner";
pres.subject = "NASA Space Apps 2026: Interplanetary Survival Guide: Martian Map";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
const C = pres.SchemeColor;
const BG = "0F1C27";

pres.defineSlideMaster({
  title: "Marswalk Content",
  background: { color: BG },
  objects: [
    { placeholder: { options: { name: "kicker", type: "body", x: 0.6, y: 0.45, w: 12.1, h: 0.35, fontSize: 13, bold: true,
      color: C.accent1, charSpacing: 3, margin: 0, valign: "top" }, text: "" } },
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.8, w: 12.1, h: 0.8, fontSize: 34, bold: true,
      color: C.background2, margin: 0, valign: "top", align: "left" }, text: "" } },
  ],
  slideNumber: { x: 12.4, y: 7.0, w: 0.5, h: 0.3, fontSize: 10, color: C.accent6 },
});
pres.defineSlideMaster({
  title: "Marswalk Split",
  background: { color: BG },
  objects: [
    { placeholder: { options: { name: "kicker", type: "body", x: 0.6, y: 1.2, w: 5.0, h: 0.35, fontSize: 13, bold: true,
      color: C.accent1, charSpacing: 3, margin: 0, valign: "top" }, text: "" } },
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 1.6, w: 5.0, h: 1.6, fontSize: 32, bold: true,
      color: C.background2, margin: 0, valign: "top", align: "left" }, text: "" } },
  ],
  slideNumber: { x: 12.4, y: 7.0, w: 0.5, h: 0.3, fontSize: 10, color: C.accent6 },
});

function bullets(slide, items, x, y, w, h, size = 16) {
  const runs = [];
  items.forEach((it, i) => {
    const parts = Array.isArray(it) ? it : [[it, false]];
    parts.forEach(([t, b], j) => runs.push({ text: t, options: { bold: b, color: b ? C.background2 : C.accent6,
      bullet: j === 0 ? { indent: 16 } : undefined, breakLine: j === parts.length - 1 && i < items.length - 1, paraSpaceAfter: 10 } }));
  });
  slide.addText(runs, { x, y, w, h, fontSize: size, valign: "top", margin: 0, isTextBox: true, objectName: "Bullets" });
}
const shot = (slide, file, x, y, w, h, name, alt) =>
  slide.addImage({ path: IMG(file), x, y, w, h, altText: alt, objectName: name,
    shadow: { type: "outer", color: "000000", opacity: 0.45, blur: 12, offset: 4, angle: 90 } });

// 1. Title ---------------------------------------------------------------------------------------
pres.addSection({ title: "Introduction" });
let s = pres.addSlide({ sectionTitle: "Introduction" });
s.background = { color: BG };
s.addImage({ path: IMG("crops/hero.png"), x: 5.2, y: 0, w: 8.13, h: 7.5, objectName: "Hero image",
  altText: "Return envelope closing on the habitat at Jezero crater" });
s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 7.2, h: 7.5, fill: { color: BG }, line: { type: "none" }, objectName: "Title panel" });
s.addShape(pres.shapes.RECTANGLE, { x: 7.2, y: 0, w: 1.2, h: 7.5, fill: { color: BG, transparency: 45 }, line: { type: "none" }, objectName: "Fade" });
s.addText("NASA SPACE APPS 2026\nINTERPLANETARY SURVIVAL GUIDE: MARTIAN MAP", { x: 0.6, y: 1.05, w: 6.3, h: 0.6, fontSize: 13, bold: true,
  color: C.accent1, charSpacing: 3, margin: 0, isTextBox: true, objectName: "Kicker" });
s.addText("Marswalk\nMission Planner", { x: 0.6, y: 1.75, w: 7.0, h: 1.9, fontSize: 54, bold: true, color: C.background2, margin: 0,
  valign: "top", isTextBox: true, objectName: "Title" });
s.addText("Can I get there, do the science, and get home alive?", { x: 0.6, y: 3.75, w: 6.4, h: 0.9, fontSize: 24, italic: true,
  color: C.accent1, margin: 0, valign: "top", isTextBox: true, objectName: "Question" });
s.addText("A layered 3D map of Jezero crater that computes on eight NASA and USGS datasets to plan a suited Marswalk: routes costed in oxygen and battery, a shrinking return envelope, live hazards, a helmet HUD and ML-guided science.",
  { x: 0.6, y: 4.8, w: 6.2, h: 1.6, fontSize: 17, color: C.accent6, margin: 0, valign: "top", isTextBox: true, objectName: "Pitch" });
s.addNotes("Marswalk answers the astronaut's real question for one spacewalk at the Perseverance landing site.");

// 2. Problem -------------------------------------------------------------------------------------
pres.addSection({ title: "Problem" });
s = pres.addSlide({ masterName: "Marswalk Split", sectionTitle: "Problem" });
s.addText("THE PROBLEM", { placeholder: "kicker" });
s.addText("Mars maps are built for regions. Astronauts walk metres", { placeholder: "title" });
bullets(s, [
  [["Mars Trek and USGS maps show ", false], ["where things are", true], [", not whether a suited crew member can reach them and return.", false]],
  [["The real limit is life support: ", false], ["kilograms of O2 and watt-hours", true], [", not kilometres.", false]],
  [["Safety depends on what a map hides: ", false], ["radio shadow, solar storms, distance to shelter.", true]],
  [["We plan at ", false], ["2 m resolution", true], [" at the Perseverance landing site, where rover data checks our answers.", false]],
], 0.6, 3.35, 5.0, 3.6, 16);
shot(s, "routes.png", 6.1, 1.2, 6.65, 3.74, "Routes screenshot", "Three routes from the habitat to Wildcat Ridge on HiRISE terrain");
s.addText("Jezero crater: Octavia E. Butler landing site to the western delta, on the HiRISE DTM with 25 cm imagery.",
  { x: 6.1, y: 5.1, w: 6.65, h: 0.5, fontSize: 12, color: C.accent6, margin: 0, isTextBox: true, objectName: "Caption" });

// 3. How it works --------------------------------------------------------------------------------
pres.addSection({ title: "How it works" });
s = pres.addSlide({ masterName: "Marswalk Content", sectionTitle: "How it works" });
s.addText("HOW IT WORKS", { placeholder: "kicker" });
s.addText("Eight data layers in, one safety decision out", { placeholder: "title" });
const layers = [
  ["Topographic", "HiRISE DTM 1 m: slope, roughness"], ["Optical", "HiRISE 25 cm, CTX; rover photos"],
  ["Spectral", "CRISM: olivine, clays, carbonate, hydration"], ["Thermal", "THEMIS night IR: rock vs dust"],
  ["Geologic", "USGS SIM 3464 map units"], ["Atmospheric", "MEDA weather at Jezero"],
  ["Radiation", "MSL RAD dose, NASA DONKI"], ["Ground truth", "706 Perseverance positions"],
];
layers.forEach(([h, d], i) => {
  const x = 0.6 + (i % 4) * 3.07, y = 1.8 + Math.floor(i / 4) * 0.95;
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: 2.9, h: 0.8, rectRadius: 0.08, fill: { color: "13212E" }, line: { color: "2B4053", width: 1 },
    objectName: `Layer ${h}` });
  s.addText([{ text: h, options: { bold: true, color: C.accent1, fontSize: 14, breakLine: true } }, { text: d, options: { color: C.accent6, fontSize: 12 } }],
    { x: x + 0.15, y: y + 0.08, w: 2.6, h: 0.66, margin: 0, valign: "top", isTextBox: true, objectName: `Layer text ${h}` });
});
shot(s, "crops/envelope_wide.png", 0.6, 3.85, 5.9, 2.75, "Envelope screenshot", "Return envelope closing on the habitat");
shot(s, "crops/mapsheet_wide.png", 6.85, 3.85, 5.9, 2.75, "Mission map", "Printable mission map with geology, times, dead zones and point of no return");
s.addText([{ text: "Return envelope. ", options: { bold: true, color: C.background2 } },
  { text: "Every cell gets a last safe moment; the safe area shrinks as the EVA clock runs.", options: { color: C.accent6 } }],
  { x: 0.6, y: 6.7, w: 5.9, h: 0.6, fontSize: 13, margin: 0, valign: "top", isTextBox: true, objectName: "Envelope caption" });
s.addText([{ text: "Printable mission map. ", options: { bold: true, color: C.background2 } },
  { text: "Curiosity-style route sheet: geology, T+ times, dead zones, point of no return.", options: { color: C.accent6 } }],
  { x: 6.85, y: 6.7, w: 5.9, h: 0.6, fontSize: 13, margin: 0, valign: "top", isTextBox: true, objectName: "Routes caption" });

// 4. Safety --------------------------------------------------------------------------------------
pres.addSection({ title: "Safety" });
s = pres.addSlide({ masterName: "Marswalk Split", sectionTitle: "Safety" });
s.addText("SAFETY THE MAP DOES NOT SHOW", { placeholder: "kicker" });
s.addText("It finds the risks before the crew steps out", { placeholder: "title" });
const risks = [
  ["AA5AE6", "Comms dead zones: ", "radio line of sight to the habitat on only 14 % of the Wildcat Ridge walk."],
  ["E34948", "Solar storms: ", "up to 67 min from shelter against a 30 min rule. One click replans: shelter now."],
  ["2FD1A6", "Rover + walkback: ", "the same trip in 70 min; the envelope still assumes a walk home if the rover fails."],
  ["D9A066", "Live replanning ", "for a dust storm or suit leak from the current position."],
];
risks.forEach(([col, h, d], i) => {
  const y = 3.35 + i * 0.9;
  s.addShape(pres.shapes.OVAL, { x: 0.6, y: y + 0.08, w: 0.2, h: 0.2, fill: { color: col }, line: { type: "none" }, objectName: `Dot ${i + 1}` });
  s.addText([{ text: h, options: { bold: true, color: C.background2 } }, { text: d, options: { color: C.accent6 } }],
    { x: 0.95, y, w: 4.7, h: 0.82, fontSize: 15, margin: 0, valign: "top", isTextBox: true, objectName: `Risk ${i + 1}` });
});
s.addImage({ path: IMG("situation.png"), x: 6.2, y: 0.7, w: 2.85, h: 6.07, altText: "On this route: comms, shelter time, dose, geology",
  objectName: "Situation panel", shadow: { type: "outer", color: "000000", opacity: 0.45, blur: 12, offset: 4, angle: 90 } });
shot(s, "crops/routes_tall.png", 9.35, 0.7, 3.4, 6.07, "Route crop", "Route with purple radio dead zones");

// 5. ML ------------------------------------------------------------------------------------------
pres.addSection({ title: "Machine learning" });
s = pres.addSlide({ masterName: "Marswalk Split", sectionTitle: "Machine learning" });
s.addText("MACHINE LEARNING", { placeholder: "kicker" });
s.addText("Find more ground like the best science site", { placeholder: "title" });
bullets(s, [
  [["10 measurements per 8 m cell at 3 scales: ", false], ["minerals, temperature, brightness, terrain.", true]],
  [["Pick a spot (Wildcat Ridge, organics-bearing mudstone): it returns the most similar ground the crew can ", false], ["reach.", true]],
  [["Checked against the USGS map it never saw: ", false], ["1.7x to 5.1x", true], [" better than chance; tuned on half the site, tested on the other half.", false]],
  [["ML proposes, physics decides: ", true], ["each candidate is costed by the planner before any number is shown.", false]],
], 0.6, 3.35, 5.0, 3.7, 15);
shot(s, "similar.png", 6.1, 1.2, 6.65, 3.74, "Similar ground screenshot", "Similar-ground search with candidates and model card");
const stats = [["0.68", "balanced accuracy predicting USGS units on unseen ground (chance 0.33)"], ["1.48x", "similarity lift on the held-out half"]];
stats.forEach(([n, d], i) => {
  const x = 6.1 + i * 3.4;
  s.addText(n, { x, y: 5.15, w: 3.1, h: 0.75, fontSize: 40, color: C.background2, margin: 0, isTextBox: true, objectName: `Stat ${i + 1}` });
  s.addText(d, { x, y: 5.9, w: 3.1, h: 0.8, fontSize: 13, color: C.accent6, margin: 0, valign: "top", isTextBox: true, objectName: `Stat label ${i + 1}` });
});

// 6. HUD -----------------------------------------------------------------------------------------
pres.addSection({ title: "In the field" });
s = pres.addSlide({ sectionTitle: "In the field" });
s.background = { color: BG };
shot(s, "hud.png", 0.6, 0.7, 7.6, 4.28, "HUD screenshot", "Helmet heads-up display along the route");
s.addText("IN THE FIELD", { x: 8.6, y: 1.2, w: 4.2, h: 0.35, fontSize: 13, bold: true, color: C.accent1, charSpacing: 3, margin: 0,
  isTextBox: true, objectName: "Kicker" });
s.addText("A helmet HUD for the walk itself", { x: 8.6, y: 1.6, w: 4.2, h: 1.3, fontSize: 32, bold: true, color: C.background2,
  margin: 0, valign: "top", isTextBox: true, objectName: "Title" });
bullets(s, [
  [["First-person view on the plan: ", false], ["heading, O2, power, next stop, ETA.", true]],
  [["Return margin", true], [" and a point-of-no-return countdown that turns red.", false]],
  [["Comms status and the ", false], ["geologic unit underfoot.", true]],
], 8.6, 3.1, 4.2, 2.4, 15);
s.addText([{ text: "What you will see. ", options: { bold: true, color: C.background2 } },
  { text: "Perseverance's own Navcam, Mastcam-Z and Hazcam frames from the sol it stood at each stop, shown before the crew arrives.", options: { color: C.accent6 } }],
  { x: 3.6, y: 5.35, w: 4.6, h: 1.6, fontSize: 14, margin: 0, valign: "top", isTextBox: true, objectName: "POV text" });
s.addImage({ path: IMG("pov.png"), x: 0.6, y: 5.25, w: 2.65, h: 1.85, altText: "Perseverance raw images at Wildcat Ridge, sol 557",
  objectName: "POV strip" });

// 7. Trust + impact ------------------------------------------------------------------------------
pres.addSection({ title: "Trust and impact" });
s = pres.addSlide({ masterName: "Marswalk Content", sectionTitle: "Trust and impact" });
s.addText("WHY TRUST IT", { placeholder: "kicker" });
s.addText("Every number traces to NASA data and to code", { placeholder: "title" });
[["106 m", "mean deviation from Perseverance's real drive between the same points"],
 ["0", "safety numbers from the AI assistant: a verifier checks every figure"],
 ["48", "automated tests, plus route cases and evals; every assumption sourced"],
 ["~2 s", "to plan three routes on 3 million terrain cells"]].forEach(([n, d], i) => {
  const x = 0.6 + i * 3.07;
  s.addText(n, { x, y: 1.75, w: 2.9, h: 0.8, fontSize: 44, color: C.background2, margin: 0, isTextBox: true, objectName: `Big stat ${i + 1}` });
  s.addText(d, { x, y: 2.55, w: 2.85, h: 0.8, fontSize: 13, color: C.accent6, margin: 0, valign: "top", isTextBox: true, objectName: `Big stat label ${i + 1}` });
});
shot(s, "crops/validation_wide.png", 0.6, 3.55, 5.9, 2.2, "Validation screenshot", "Planned walker route vs Perseverance drive");
shot(s, "crops/fc_wide.png", 6.85, 3.55, 5.9, 2.2, "Flight Controller screenshot", "Flight Controller answer with verified numbers");
s.addText([{ text: "Impact: ", options: { bold: true, color: C.background2 } },
  { text: "planners and crews get a decision, not a picture: go, go by rover, or don't go, with the reason. The same pipeline runs on any site with a HiRISE DTM.", options: { color: C.accent6 } }],
  { x: 0.6, y: 5.95, w: 12.15, h: 0.6, fontSize: 15, margin: 0, valign: "top", isTextBox: true, objectName: "Impact" });
s.addText("github.com/9irija/marshalll_NASA  ·  Python (GDAL, numba, scikit-learn, FastAPI), TypeScript + CesiumJS, Claude with tool use  ·  Images: NASA/JPL-Caltech/UArizona",
  { x: 0.6, y: 6.75, w: 11.6, h: 0.35, fontSize: 11, color: C.accent6, margin: 0, isTextBox: true, objectName: "Footer" });

(async () => {
  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("wrote", OUT);
})();
