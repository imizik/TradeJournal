export type AppAccess = { enabled: boolean; identifier: string; owner: boolean; csrf: string; sample_data?: boolean; sample_decision_writes_enabled?: boolean;
  grants: { symbols?: string[]; run_ids?: string[]; journal_read?: boolean; decision_write?: boolean } };
export const PRIVATE_ACCESS: AppAccess = { enabled: false, identifier: "owner", owner: true, csrf: "", grants: {} };
