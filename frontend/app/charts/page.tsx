import ChartWorkspace from "@/components/charts/ChartWorkspace";

export default async function ChartsPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const query = await searchParams;
  // A new route link must apply its symbol / historical focus, even from Charts.
  const target = [query.symbol, query.from, query.to, query.trade, query.fill];
  return <ChartWorkspace key={JSON.stringify(target)} initialSymbol={typeof query.symbol === "string" ? query.symbol.toUpperCase() : undefined} />;
}
