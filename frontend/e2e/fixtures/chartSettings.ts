import type { BrowserContext } from "@playwright/test";

/**
 * An in-memory `/charts/settings` with the real endpoint's revision rule, so
 * chart tests start from empty server settings and never share state through
 * the e2e database. Tests edit `revision`/`data` to play another device.
 */
export type SettingsStore = {
  revision: number; data: Record<string, unknown> | null; offline: boolean;
  saves: { base: number; data: Record<string, unknown>; status: number }[];
};

export async function fakeChartSettings(context: BrowserContext, store: Partial<SettingsStore> = {}): Promise<SettingsStore> {
  const state: SettingsStore = { revision: 0, data: null, offline: false, saves: [], ...store };
  const copy = () => ({ revision: state.revision, data: state.data, updated_at: null });
  await context.route("**/api/backend/charts/settings", async (route) => {
    const body = route.request().method() === "PUT" ? route.request().postDataJSON() : null;
    if (state.offline) {
      if (body) state.saves.push({ base: body.base_revision, data: body.data, status: 503 });
      return route.fulfill({ status: 503, json: { detail: "API unavailable" } });
    }
    if (!body) return route.fulfill({ json: copy() });
    const stale = body.base_revision !== state.revision;
    state.saves.push({ base: body.base_revision, data: body.data, status: stale ? 409 : 200 });
    if (stale) return route.fulfill({ status: 409, json: { detail: { code: "revision_conflict", message: "Changed on another device.", current: copy() } } });
    state.revision += 1;
    state.data = body.data;
    return route.fulfill({ json: copy() });
  });
  return state;
}
