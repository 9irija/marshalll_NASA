# Web design plan

Built with the `frontend-design` skill (`.claude/skills/frontend-design`, Apache-2.0, from anthropics/skills)
and the dataviz method (palettes run through its validator).

**Subject.** A flight-controller console for one EVA at Jezero. Audience: a judge in 3 minutes, and the crew
member the tool imagines. Primary job: make the return envelope visible, shrinking over the real terrain as
the EVA clock runs.

**Colour.** Martian sunset sky is blue, so the chrome is dusk blue instead of black or rust.

| Token | Hex | Role |
|---|---|---|
| dusk | `#0f1c27` | panel base (86 % opacity, blurred) |
| dusk-raised | `#13212e` | chart surface (validator surface) |
| haze | `#2b4053` | hairlines, inactive controls |
| frost | `#e9eef2` / `#a9b8c5` | primary / secondary text |
| butterscotch | `#d9a066` | the one brand accent: the EVA clock and focus rings (Mars daytime sky) |
| envelope | `#2fd1a6` | the safe-return region and its edge |
| critical | `#e34948` | point of no return, always with an icon and words |

Routes (validated, dark): safest `#3987e5`, fastest `#c98500`, most science `#9085e9`.
Consumables (validated, dark): O2 `#199e70`, battery `#d95926`.

**Type.** Archivo (variable width). Text at width 100; numbers in tabular figures; the EVA clock at
width 125, weight 300, very large: the one bold typographic gesture. Sentence case everywhere.

**Layout.**
```
+-------------------------------------------------------------+
| plan panel |        3D Jezero (full bleed)      | readout    |
| target,    |                                    | totals,    |
| EVA limit, |                                    | 2 charts   |
| hazards,   |                                    |            |
| layers     |                                    |            |
| [T+ 1:42  ======o=========|PNR======  safe area 4.1 km2  ] |
+-------------------------------------------------------------+
```
Left-aligned text, panels float over the terrain; on phones the panels become a bottom sheet with tabs.

**Review against generic defaults.** First draft used near-black + one neon accent (default #2) and a
monospace face for numbers (default #5). Changed to dusk blue grounded in the Martian sunset and
tabular Archivo. No all-caps eyebrows, no numbered markers, no arrow-suffixed buttons.

**Motion.** One orchestrated moment: the envelope contracting while the astronaut marker walks the route.
Everything else responds to input only; `prefers-reduced-motion` disables autoplay.
