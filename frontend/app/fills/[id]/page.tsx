import { api } from "@/lib/api";
import ManualFillForm from "@/components/ManualFillForm";
import { notFound } from "next/navigation";

function fillTitle(fill: Awaited<ReturnType<typeof api.fill>>) {
  if (fill.instrument_type === "stock") {
    return `${fill.ticker} stock fill`;
  }
  return `${fill.ticker} ${fill.option_type ?? "option"} ${fill.strike ?? "-"} ${fill.expiration ?? "-"}`;
}

export default async function FillDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ returnTo?: string }>;
}) {
  const { id } = await params;
  const { returnTo } = await searchParams;

  let fill;
  let accounts;

  try {
    [fill, accounts] = await Promise.all([api.fill(id), api.accounts()]);
  } catch {
    notFound();
  }

  const cancelHref = returnTo || "/fills";

  return (
    <div className="space-y-6">
      <div>
        <a href={cancelHref} className="text-sm text-muted-foreground hover:text-foreground">
          Back
        </a>
        <h1 className="mt-2 text-xl font-semibold text-foreground">{fillTitle(fill)}</h1>
        <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
          Editing a fill rebuilds trades from scratch using the corrected fill history. If this changes how fills group
          together, the original trade detail URL may no longer exist after save.
        </p>
      </div>

      <ManualFillForm
        accounts={accounts}
        mode="edit"
        initialFill={fill}
        successHref={cancelHref}
        cancelHref={cancelHref}
      />
    </div>
  );
}
