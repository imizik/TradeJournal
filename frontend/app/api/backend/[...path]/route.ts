import { forward } from "@/lib/backendProxy";
export const dynamic = "force-dynamic";
async function handler(request: Request, { params }: { params: Promise<{ path: string[] }> }) {
  return forward(request, (await params).path);
}
export { handler as GET, handler as POST, handler as PUT, handler as PATCH, handler as DELETE, handler as HEAD };
