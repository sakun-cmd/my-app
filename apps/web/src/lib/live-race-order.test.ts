import { describe, expect, it } from "vitest";

import type { RaceSummary } from "./types";
import { orderLiveRaces } from "./live-race-order";

function race(
  id: string,
  venueCode: string,
  raceNumber: number,
  scheduledAt: string | null,
  status: RaceSummary["status"],
): RaceSummary {
  return {
    id,
    race_date: "2026-09-11",
    venue: { code: venueCode, name: venueCode },
    race_number: raceNumber,
    scheduled_at: scheduledAt,
    grade: null,
    data_completeness: 100,
    status,
  };
}

describe("orderLiveRaces", () => {
  it("orders unfinished races by deadline and moves finals to the venue-sorted tail", () => {
    const races = [
      race("final-21-2", "21", 2, "2026-09-11T02:00:00Z", "final"),
      race("later", "01", 2, "2026-09-11T03:00:00Z", "upcoming"),
      race("final-01-2", "01", 2, "2026-09-11T01:00:00Z", "final"),
      race("earlier", "24", 1, "2026-09-11T02:00:00Z", "live"),
      race("final-01-1", "01", 1, "2026-09-11T00:00:00Z", "final"),
    ];

    expect(orderLiveRaces(races).map((item) => item.id)).toEqual([
      "earlier",
      "later",
      "final-01-1",
      "final-01-2",
      "final-21-2",
    ]);
  });

  it("moves cancelled and void races to the tail with the finals", () => {
    const races = [
      race("cancelled-02-1", "02", 1, "2026-09-11T00:00:00Z", "cancelled"),
      race("pending", "03", 1, "2026-09-11T05:00:00Z", "pending_result"),
      race("void-01-3", "01", 3, "2026-09-11T01:00:00Z", "void"),
      race("final-01-1", "01", 1, "2026-09-11T02:00:00Z", "final"),
    ];

    expect(orderLiveRaces(races).map((item) => item.id)).toEqual([
      "pending",
      "final-01-1",
      "void-01-3",
      "cancelled-02-1",
    ]);
  });

  it("places an unfinished race without a deadline after timed unfinished races", () => {
    const races = [
      race("missing", "01", 1, null, "unknown"),
      race("timed", "02", 1, "2026-09-11T02:00:00Z", "pending_result"),
      race("final", "03", 1, "2026-09-11T01:00:00Z", "final"),
    ];

    expect(orderLiveRaces(races).map((item) => item.id)).toEqual([
      "timed",
      "missing",
      "final",
    ]);
  });
});
