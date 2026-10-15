import { checkOwnerDetail } from "@/lib/advisorOwner";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export async function GET(request: Request, { params }: { params: Promise<{ checkId: string }> }) {
  return checkOwnerDetail(request, (await params).checkId);
}
