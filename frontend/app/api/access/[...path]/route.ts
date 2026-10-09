import { forward } from "@/lib/backendProxy";
export const dynamic = "force-dynamic";
async function handler(request: Request, { params }: { params: Promise<{ path: string[] }> }) {
  return forward(request, (await params).path, true);
}
export { handler as GET, handler as POST };
