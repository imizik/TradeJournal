import CompanyResearch from "@/components/company-research/CompanyResearch";
export default async function Page({ params }: { params: Promise<{ symbol: string }> }) {
  return <CompanyResearch symbol={decodeURIComponent((await params).symbol)} />;
}
