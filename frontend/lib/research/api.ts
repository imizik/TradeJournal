// API client for research workspaces. Kept separate from lib/api.ts because the
// save path needs custom 409 (revision conflict) handling that the generic
// helpers don't provide.

import { API } from "@/lib/api";
import type { Workspace, WorkspaceData } from "./types";

export class RevisionConflictError extends Error {
  current: Workspace;
  constructor(current: Workspace) {
    super("revision_conflict");
    this.name = "RevisionConflictError";
    this.current = current;
  }
}

export async function getWorkspace(slug: string): Promise<Workspace> {
  const res = await fetch(`${API}/research/workspaces/${slug}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`GET workspace ${slug} -> ${res.status}`);
  return res.json();
}

export async function saveWorkspace(
  slug: string,
  baseRevision: number,
  data: WorkspaceData
): Promise<Workspace> {
  const res = await fetch(`${API}/research/workspaces/${slug}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ base_revision: baseRevision, data }),
  });
  if (res.status === 409) {
    const body = await res.json();
    const current: Workspace | undefined = body?.detail?.current;
    if (current) throw new RevisionConflictError(current);
    throw new Error("revision conflict");
  }
  if (!res.ok) throw new Error(`PUT workspace ${slug} -> ${res.status}`);
  return res.json();
}
