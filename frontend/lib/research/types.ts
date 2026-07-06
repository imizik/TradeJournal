// Types for the AI Buildout research workspace. Mirrors the backend seed shape
// (backend/app/data/ai_buildout_seed.json) served by /research/workspaces/{slug}.

export type Mon = "scarcity" | "licensing" | "capex";
export type CoType = "core" | "picks" | "cyclical" | "moonshot" | "hype";
export type Cap = "mega" | "large" | "mid" | "small" | "micro";
export type Status =
  | "Untouched"
  | "Researching"
  | "Watchlist"
  | "Position"
  | "Passed";
export type Prio = "A" | "B" | "C";
export type SignalLevel = "G" | "A" | "R";

export type Company = {
  ticker: string;
  name: string;
  layer: string;
  cap: Cap;
  mon: Mon;
  type: CoType;
  // Opportunity scores (0–10)
  q: number;
  ai: number;
  up: number;
  // Risk scores (0–10)
  bsRisk: number;
  valRisk: number;
  ccRisk: number;
  cxRisk: number;
  // Free-text fundamentals
  rev: string;
  gm: string;
  fcf: string;
  thesis: string;
  bear: string;
  buy: string;
  sell: string;
  prio: Prio;
  status: Status;
  stars: number;
  short: boolean;
};

export type CompanyTextField =
  | "rev"
  | "gm"
  | "fcf"
  | "thesis"
  | "bear"
  | "buy"
  | "sell";
export type CompanyScoreField =
  | "q"
  | "ai"
  | "up"
  | "bsRisk"
  | "valRisk"
  | "ccRisk"
  | "cxRisk";
export type CompanySelectField = "cap" | "mon" | "type" | "prio" | "status" | "layer";

export type Layer = {
  id: string;
  name: string;
  group: string;
  mon: Mon;
  what: string;
  whyMoney: string;
  whyFail: string;
  bottleneck: string;
  metrics: string;
  redFlags: string;
};

export type LayerTextField =
  | "what"
  | "whyMoney"
  | "whyFail"
  | "bottleneck"
  | "metrics"
  | "redFlags";

export type MoatItem = {
  ticker: string;
  type: CoType;
  makes: string;
  moat: string;
  different: string;
  valueChain: string;
  bull: string;
  bear: string;
};

export type MoatField = Exclude<keyof MoatItem, "ticker" | "type">;

export type MoatCluster = {
  title: string;
  items: MoatItem[];
};

export type DeepDive = {
  businessDesc: string;
  moat: string;
  revGrowth: string;
  margins: string;
  fcfPath: string;
  custQuality: string;
  aiExposure: string;
  valRisk: string;
  bull: string;
  bear: string;
  prove: string;
  breakThesis: string;
};

export type DeepDiveField = keyof DeepDive;

export type Signpost = {
  id: string;
  label: string;
  level: SignalLevel;
  notes: string;
};

export type ChecklistItem = { id: string; text: string };
export type ChecklistAnswer = { checked: boolean; notes: string };

export type WorkspaceData = {
  order: string[];
  layers: Record<string, Layer>;
  companies: Record<string, Company>;
  moat: Record<string, MoatCluster>;
  deepDives: Record<string, Partial<DeepDive>>;
  signposts: Signpost[];
  checklistTemplate: ChecklistItem[];
  // Per-ticker bear-case answers: ticker -> checkId -> answer.
  checklistByTicker: Record<string, Record<string, ChecklistAnswer>>;
  shortlistOrder: string[];
};

export type Workspace = {
  slug: string;
  revision: number;
  schema_version: number;
  data: WorkspaceData;
  updated_at: string | null;
};
