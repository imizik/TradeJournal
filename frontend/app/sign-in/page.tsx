import { headers } from "next/headers";
import { notFound } from "next/navigation";
import OwnerSignIn from "@/components/OwnerSignIn";
import { accessConfig } from "@/lib/accessServer";
import { lockMode, safeNext, sessionToken, sessionValid } from "@/lib/ownerLock";

export const dynamic = "force-dynamic";
export const metadata = { title: "Sign in · Trade Journal" };

export default async function SignInPage({ searchParams }: { searchParams: Promise<{ next?: string | string[] }> }) {
  const mode = lockMode();
  const config = accessConfig();
  if (mode === "off" || config.profile !== "private_legacy") notFound();
  const signedIn = (await sessionValid(config.target, sessionToken({ headers: await headers() }))) === true;
  const wanted = (await searchParams).next;
  return <OwnerSignIn signedIn={signedIn} next={safeNext(Array.isArray(wanted) ? wanted[0] : wanted)} reportOnly={mode === "report"} />;
}
