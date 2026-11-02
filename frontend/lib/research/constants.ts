// Presentation constants for the AI Buildout cockpit. Colors are expressed as
// Tailwind utility classes so the module stays inside the app's dark theme
// instead of the artifact's hardcoded hex palette.

import type { Cap, CoType, Mon, Prio, SignalLevel, Status } from "./types";

export const SLUG = "ai-buildout";

export const MON_LABEL: Record<Mon, string> = {
  scarcity: "SCARCITY",
  licensing: "LICENSE",
  capex: "CAPEX-FIN",
};

// Badge classes (solid pill) for monetization model.
export const MON_BADGE: Record<Mon, string> = {
  scarcity: "bg-secondary text-foreground",
  licensing: "bg-secondary text-muted-foreground",
  capex: "bg-secondary text-muted-foreground",
};

export const TYPE_LABEL: Record<CoType, string> = {
  core: "CORE",
  picks: "PICKS",
  cyclical: "CYCLE",
  moonshot: "MOON",
  hype: "HYPE",
};

export const TYPE_FULL: Record<CoType, string> = {
  core: "CORE COMPOUNDER",
  picks: "PICKS & SHOVELS",
  cyclical: "CYCLICAL",
  moonshot: "MOONSHOT",
  hype: "HYPE RISK",
};

export const TYPE_BADGE: Record<CoType, string> = {
  core: "bg-secondary text-foreground",
  picks: "bg-secondary text-muted-foreground",
  cyclical: "bg-secondary text-muted-foreground",
  moonshot: "bg-secondary text-muted-foreground",
  hype: "bg-secondary text-muted-foreground",
};

export const STATUS_BADGE: Record<Status, string> = {
  Untouched: "bg-secondary text-muted-foreground",
  Researching: "bg-secondary text-foreground",
  Watchlist: "bg-secondary text-foreground",
  Position: "bg-secondary text-foreground",
  Passed: "bg-secondary text-muted-foreground",
};

export const STATUS_DOT: Record<Status, string> = {
  Untouched: "bg-muted-foreground/50",
  Researching: "bg-muted-foreground",
  Watchlist: "bg-foreground/70",
  Position: "bg-foreground",
  Passed: "bg-muted-foreground/30",
};

export const SIGNAL_BADGE: Record<SignalLevel, string> = {
  G: "bg-secondary text-foreground",
  A: "bg-primary/15 text-primary",
  R: "bg-red-500/10 text-red-400",
};

export const SIGNAL_NEXT: Record<SignalLevel, SignalLevel> = {
  G: "A",
  A: "R",
  R: "G",
};

export const MON_OPTIONS: { value: Mon; label: string }[] = [
  { value: "scarcity", label: "scarcity" },
  { value: "licensing", label: "licensing" },
  { value: "capex", label: "capex-financed" },
];

export const TYPE_OPTIONS: { value: CoType; label: string }[] = [
  { value: "core", label: "core compounder" },
  { value: "picks", label: "picks & shovels" },
  { value: "cyclical", label: "cyclical" },
  { value: "moonshot", label: "moonshot" },
  { value: "hype", label: "hype risk" },
];

export const CAP_OPTIONS: Cap[] = ["mega", "large", "mid", "small", "micro"];
export const STATUS_OPTIONS: Status[] = [
  "Untouched",
  "Researching",
  "Watchlist",
  "Position",
  "Passed",
];
export const PRIO_OPTIONS: Prio[] = ["A", "B", "C"];

// Score → text color. Opportunity scores (higher = greener).
export function qualityColor(v: number): string {
  if (v >= 8) return "text-foreground";
  if (v >= 6) return "text-foreground/80";
  if (v >= 4) return "text-muted-foreground";
  if (v > 0) return "text-muted-foreground";
  return "text-muted-foreground";
}

// Risk scores (higher = redder).
export function riskColor(v: number): string {
  if (v >= 9) return "text-red-400";
  if (v >= 7) return "text-primary";
  if (v >= 4) return "text-foreground/80";
  if (v > 0) return "text-muted-foreground";
  return "text-muted-foreground";
}

export const MOAT_CLUSTER_LABELS: Record<string, string> = {
  semis: "Semiconductors",
  networking: "Interconnect",
  power: "Power & utilities",
  neoclouds: "Neoclouds",
  "semi-equip": "Semi equipment",
};

// Which layers open which moat cluster (from the artifact's LAYER_CLUSTER).
export const LAYER_CLUSTER: Record<string, string> = {
  gpus: "semis",
  "custom-silicon": "semis",
  memory: "semis",
  networking: "networking",
  optical: "networking",
  "power-gen": "power",
  grid: "power",
  neoclouds: "neoclouds",
  "semi-equip": "semi-equip",
};

export const DEEP_FIELDS: {
  key: keyof import("./types").DeepDive;
  label: string;
  full?: boolean;
  tone?: "neutral" | "ai" | "risk" | "bull" | "bear";
}[] = [
  { key: "businessDesc", label: "Business description", full: true },
  { key: "moat", label: "Moat / differentiation" },
  { key: "revGrowth", label: "Revenue growth" },
  { key: "margins", label: "Margins" },
  { key: "fcfPath", label: "FCF path" },
  { key: "custQuality", label: "Customer / design-win quality" },
  { key: "aiExposure", label: "AI / data-center exposure", full: true, tone: "ai" },
  { key: "valRisk", label: "Valuation risk", tone: "risk" },
  { key: "bull", label: "Bull case", tone: "bull" },
  { key: "bear", label: "Bear case", tone: "bear" },
  { key: "prove", label: "What would PROVE the thesis", tone: "bull" },
  { key: "breakThesis", label: "What would BREAK the thesis", tone: "bear" },
];

export const TABS: { v: string; label: string }[] = [
  { v: "stack", label: "Stack" },
  { v: "watchlist", label: "Watchlist" },
  { v: "moat", label: "Moat Lab" },
  { v: "conviction", label: "Conviction" },
  { v: "shortlist", label: "Shortlist" },
  { v: "checklist", label: "Checklist" },
  { v: "deepdive", label: "Deep Dive" },
];
