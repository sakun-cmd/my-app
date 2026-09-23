import { RaceAnalysisView } from "@/components/RaceAnalysisView";

export default async function RacePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <RaceAnalysisView raceId={id} />;
}

