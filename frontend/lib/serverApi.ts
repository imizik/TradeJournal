import "server-only";
import { headers } from "next/headers";
import { createApi } from "./api";
import { accessConfig, requireAccess, upstreamHeaders } from "./accessServer";
export const api = createApi(async (input, init) => {
  const config = accessConfig();
  if (config.profile === "private_legacy") return fetch(input, init);
  const url = new URL(String(input), config.target);
  if (url.origin !== config.target) throw new Error("Authenticated API requests must use the configured backend");
  const access = await requireAccess();
  const selected = upstreamHeaders(new Headers(await headers()));
  new Headers(init?.headers).forEach((value, key) => selected.set(key, value));
  selected.set("x-tj-csrf", access.csrf);
  selected.set("origin", config.origin);
  return fetch(input, { ...init, headers: selected, cache: "no-store", redirect: "manual" });
});
