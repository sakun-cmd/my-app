import type { RaceSummary } from "./types";

function compareVenueAndRace(left: RaceSummary, right: RaceSummary) {
  return (
    left.venue.code.localeCompare(right.venue.code) ||
    left.race_number - right.race_number
  );
}

const settledStatuses: ReadonlySet<RaceSummary["status"]> = new Set([
  "final",
  "cancelled",
  "void",
]);

export function orderLiveRaces(races: RaceSummary[]) {
  return [...races].sort((left, right) => {
    const leftFinal = settledStatuses.has(left.status);
    const rightFinal = settledStatuses.has(right.status);
    if (leftFinal !== rightFinal) return leftFinal ? 1 : -1;
    if (leftFinal) return compareVenueAndRace(left, right);

    const leftTime = left.scheduled_at
      ? new Date(left.scheduled_at).getTime()
      : Number.POSITIVE_INFINITY;
    const rightTime = right.scheduled_at
      ? new Date(right.scheduled_at).getTime()
      : Number.POSITIVE_INFINITY;
    return leftTime - rightTime || compareVenueAndRace(left, right);
  });
}
