import { accessConfig, requireAccess, upstreamHeaders } from "@/lib/accessServer";

export const dynamic = "force-dynamic";

const CONTEXT = "Plan a trade from this screenshot";
const lab = (params: Record<string, string>) =>
  new Response(null, { status: 303, headers: { Location: `/copilot-lab?${new URLSearchParams(params)}`, "Cache-Control": "no-store" } });

/** The phone's share sheet (the manifest's share_target): the shared image is stored through POST /copilot/images, then
 * the lab opens with it attached and a question ready, nothing sent. Owner only. */
export async function POST(request: Request) {
  // The share sheet opens this as the user's own navigation; a form posted from another site is refused.
  if (request.headers.get("sec-fetch-site") === "cross-site") return Response.json({ detail: "Not permitted" }, { status: 403 });
  const access = await requireAccess();
  if (!access.owner) return Response.json({ detail: "Not found" }, { status: 404 });
  let image: File | undefined;
  try {
    image = (await request.formData()).getAll("image").find((value): value is File => value instanceof File && value.size > 0);
  } catch { /* not a form: open the lab with nothing attached */ }
  if (!image) return lab({ context: "The share carried no image; attach the screenshot here" });
  const config = accessConfig();
  const form = new FormData();
  form.append("image", image, image.name || "screenshot");
  const headers = upstreamHeaders(request.headers);
  headers.delete("content-type");  // the new form's own boundary
  if (config.profile !== "private_legacy") {
    headers.set("x-tj-csrf", access.csrf);
    headers.set("origin", config.origin);
  }
  try {
    const response = await fetch(`${config.target}/copilot/images`, { method: "POST", body: form, headers, cache: "no-store", redirect: "manual" });
    const stored = response.ok ? await response.json() as { id?: string } : null;
    if (stored?.id && /^[0-9a-f]{32}$/.test(stored.id)) return lab({ image: stored.id, context: CONTEXT });
  } catch { /* said below */ }
  return lab({ context: "The shared screenshot could not be attached; attach it here" });
}
