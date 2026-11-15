import * as api from "./api";
import type { AssistantResponse, ProvenanceEntry, Route, Validation } from "./types";

const esc = (s: string) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);

export interface DrawerHooks {
  showValidation: (v: Validation | null) => void;
  setEnvelopeVisible?: (v: boolean) => void;
  showRoutes: (routes: Route[], label?: string) => void;
}

export class Drawer {
  private el = document.getElementById("drawer")!;
  private body = document.getElementById("drawer-body")!;
  private current: string | null = null;
  private chat: { role: "user" | "assistant"; content: string }[] = [];
  private chatHtml = "";

  private suggestions: string[] = [
    "Plan a 4 hour EVA to the hydrated minerals on the delta.",
    "Take me to the olivine at Seitah, safest route only.",
    "Roughly how much oxygen do I need to reach Three Forks and back?",
    "A dust storm is coming. Can I still make it to Wildcat Ridge in 3 hours?",
  ];

  constructor(private hooks: DrawerHooks) {
    api.chatSuggestions().then((s) => { if (s.length) this.suggestions = s; }).catch(() => undefined);
    document.getElementById("drawer-close")!.addEventListener("click", () => this.close());
    document.querySelectorAll<HTMLButtonElement>("[data-drawer]").forEach((b) =>
      b.addEventListener("click", () => this.open(b.dataset.drawer!)));
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") this.close(); });
  }

  close() {
    this.el.classList.remove("open");
    this.el.setAttribute("aria-hidden", "true");
    if (this.current === "validate") { this.hooks.showValidation(null); this.hooks.setEnvelopeVisible?.(true); }
    this.current = null;
  }

  /** Open the drawer with caller-provided HTML (used by the similar-ground tool). Returns the body element. */
  openCustom(kind: string, html: string): HTMLElement {
    if (this.current === "validate") { this.hooks.showValidation(null); this.hooks.setEnvelopeVisible?.(true); }
    this.current = kind;
    this.el.classList.add("open");
    this.el.setAttribute("aria-hidden", "false");
    this.body.innerHTML = html;
    return this.body;
  }

  get openKind() { return this.current; }

  async open(kind: string) {
    if (this.current === kind) return this.close();
    if (this.current === "validate") { this.hooks.showValidation(null); this.hooks.setEnvelopeVisible?.(true); }
    this.current = kind;
    this.el.classList.add("open");
    this.el.setAttribute("aria-hidden", "false");
    this.body.innerHTML = `<p class="hint">Loading...</p>`;
    try {
      if (kind === "sources") await this.sources();
      else if (kind === "assumptions") await this.assumptions();
      else if (kind === "validate") await this.validation();
      else if (kind === "chat") this.renderChat();
    } catch (e) {
      this.body.innerHTML = `<p>Could not load: ${esc(String(e))}</p>`;
    }
  }

  private async sources() {
    const m = await api.getManifest();
    this.body.innerHTML = `<h2>Data sources</h2><p class="hint">Every layer and every number traces to one of these NASA products.</p>` +
      m.layers.map((l: ProvenanceEntry) => `<div class="prov"><b>${esc(l.id)}</b> &nbsp;${esc(l.mission)}, ${esc(l.instrument)}
        <div class="meta">${esc(l.product_id)}${l.resolution_m ? `, ${l.resolution_m} m/px` : ""}, ${esc(l.acquired)}</div>
        <div class="meta">${l.processing.map(esc).join("; ")}</div>
        <a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.url)}</a></div>`).join("");
  }

  private async assumptions() {
    const a = await api.getAssumptions();
    const rows: string[] = [];
    const walk = (o: Record<string, unknown>, path: string) => {
      for (const [k, v] of Object.entries(o)) {
        if (v && typeof v === "object" && "value" in (v as object)) {
          const p = v as { value: unknown; source: string };
          rows.push(`<div class="assume"><span>${esc(path + k.replace(/_/g, " "))}</span><span class="val">${esc(JSON.stringify(p.value))}</span>
            <span class="src">${esc(p.source)}</span></div>`);
        } else if (v && typeof v === "object") walk(v as Record<string, unknown>, `${path}${k.replace(/_/g, " ")}: `);
      }
    };
    walk(a, "");
    this.body.innerHTML = `<h2>Model assumptions</h2><p class="hint">Version ${esc(String(a.version))}. Edit config/model.yaml to change any of these.</p>${rows.join("")}`;
  }

  private async validation() {
    const v = await api.validate();
    this.hooks.showValidation(v);
    this.hooks.setEnvelopeVisible?.(false);
    this.body.innerHTML = `<h2>Check against Perseverance</h2>
      <p>Perseverance drove from its sol ${v.sol_from} position to its sol ${v.sol_to} position. We planned the same trip for a suited walker
      on the same terrain. Dashed white: the rover's real path. Solid gold: our plan for a walker.</p>
      <div class="totals"><div><dt>Mean deviation</dt><dd class="metric">${v.mean_deviation_m.toFixed(0)} <small>m</small></dd></div>
      <div><dt>Frechet distance</dt><dd class="metric">${v.frechet_m.toFixed(0)} <small>m</small></dd></div>
      <div><dt>Rover path</dt><dd>${(v.actual.length_m / 1000).toFixed(2)} <small>km</small></dd></div>
      <div><dt>Our path</dt><dd>${(v.planned.length_m / 1000).toFixed(2)} <small>km</small></dd></div></div>
      <p class="hint">${esc(v.note)}</p><p class="hint">Source: Mars 2020 MMGIS traverse (M20_traverse.json).</p>`;
  }

  private renderChat() {
    const suggestions = this.suggestions;
    this.body.innerHTML = `<h2>Flight Controller</h2>
      <p class="hint">Ask in plain language. Every oxygen, battery, distance and time figure comes from the planner and is checked before you see it.</p>
      <div class="chat-suggest">${suggestions.map((s) => `<button class="ghost suggest">${esc(s)}</button>`).join("")}</div>
      <div class="chat-log" id="chat-log">${this.chatHtml}</div>
      <form class="chat-form" id="chat-form"><textarea id="chat-in" placeholder="Plan an EVA..." aria-label="Message"></textarea>
      <button class="cta" style="width:auto;margin:0">Send</button></form>`;
    const form = document.getElementById("chat-form") as HTMLFormElement;
    const input = document.getElementById("chat-in") as HTMLTextAreaElement;
    this.body.querySelectorAll<HTMLButtonElement>(".suggest").forEach((b) => b.addEventListener("click", () => { input.value = b.textContent ?? ""; form.requestSubmit(); }));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      input.value = "";
      this.chat.push({ role: "user", content: text });
      this.append(`<div class="msg user">${esc(text)}</div><div class="msg bot" id="pending">Planning...</div>`);
      try {
        let r: AssistantResponse;
        if (api.state.online) r = await api.assistant(this.chat);
        else {
          const i = suggestions.indexOf(text);
          if (i < 0) throw new Error("This hosted demo answers the suggested questions above (precomputed by the planner). For any question, run the planner locally with make dev.");
          r = await api.demoAssistant(i);
        }
        this.chat.push({ role: "assistant", content: r.answer });
        this.resolvePending(this.renderAnswer(r));
        if (r.routes?.length) this.hooks.showRoutes(r.routes, "Flight Controller plan");
      } catch (err) {
        this.resolvePending(`<div class="msg bot">${esc(String(err instanceof Error ? err.message : err))}</div>`);
      }
    });
  }

  private resolvePending(html: string) {
    this.chatHtml = this.chatHtml.replace(`<div class="msg bot" id="pending">Planning...</div>`, html);
    this.append("");
  }

  private append(html: string) {
    this.chatHtml += html;
    const log = document.getElementById("chat-log");
    if (log) { log.innerHTML = this.chatHtml; log.lastElementChild?.scrollIntoView({ block: "end" }); }
    this.wireAnswer();
  }

  private renderAnswer(r: AssistantResponse): string {
    // highlight unverified numbers, link citations and route names
    let out = "";
    let i = 0;
    const spans = [...r.verification.unverified].sort((a, b) => a.start - b.start);
    for (const u of spans) { out += esc(r.answer.slice(i, u.start)) + `<mark title="Not found in any tool result">${esc(r.answer.slice(u.start, u.end))}</mark>`; i = u.end; }
    out += esc(r.answer.slice(i));
    out = out.replace(/\[(\d+)\]/g, (m, n) => {
      const c = r.citations.find((x) => x.n === Number(n));
      return c ? `<a class="cite" href="${esc(c.url)}#page=${c.page}" target="_blank" rel="noopener" title="${esc(c.title)}, p. ${c.page}">${m}</a>` : m;
    });
    out = out.replace(/\b(Safest|Fastest|Most science)\b/g, (m) => `<span class="route-ref" data-route="${m === "Most science" ? "science" : m.toLowerCase()}">${m}</span>`);
    const v = r.verification;
    const badge = v.passed
      ? `<svg width="14" height="14" viewBox="0 0 14 14"><circle cx="7" cy="7" r="6" fill="#2fd1a6"/><path d="M4 7.2 L6.2 9.2 L10 5" stroke="#0f1c27" stroke-width="1.8" fill="none"/></svg> ${v.verified_count} numbers verified against tool results`
      : `<svg width="14" height="14" viewBox="0 0 14 14"><circle cx="7" cy="7" r="6" fill="#e34948"/><path d="M7 3.5 V8 M7 10 V10.2" stroke="#0f1c27" stroke-width="1.8"/></svg> ${v.unverified.length} number(s) could not be verified (highlighted)`;
    const cons = r.constraints ? `<div class="constraints">Understood as: ${esc(Object.entries(r.constraints).filter(([k, x]) => x != null && x !== false && k !== "tool").map(([k, x]) => `${k.replace(/_/g, " ")} ${Array.isArray(x) ? x.join(", ") : x}`).join("; "))}</div>` : "";
    const cites = r.citations.length ? `<div class="sources-list">${r.citations.map((c) => `[${c.n}] <a href="${esc(c.url)}#page=${c.page}" target="_blank" rel="noopener">${esc(c.title)}</a>, p. ${c.page}`).join("<br>")}</div>` : "";
    const mode = r.mode === "precomputed"
      ? `<div class="hint">Precomputed answer: produced by the same planner tools and number verifier, saved for this hosted demo.</div>`
      : r.mode === "offline" ? `<div class="hint">Offline mode: templated answer from tool results, no language model. For live answers set ANTHROPIC_API_KEY, or LLM_PROVIDER=gemini with GEMINI_API_KEY.</div>` : "";
    return `<div class="msg bot">${cons}${out}<div class="verify">${badge}</div>${cites}${mode}</div>`;
  }

  private wireAnswer() {
    this.body.querySelectorAll<HTMLElement>(".route-ref").forEach((el) => el.addEventListener("click", () =>
      document.querySelector<HTMLButtonElement>(`.route[data-objective="${el.dataset.route}"]`)?.click()));
  }
}
