export interface Venue {
  code: string;
  name: string;
}

export interface RaceSummary {
  id: string;
  race_date: string;
  venue: Venue;
  race_number: number;
  scheduled_at: string | null;
  grade: string | null;
  data_completeness: number;
  status:
    | "upcoming"
    | "live"
    | "pending_result"
    | "final"
    | "cancelled"
    | "void"
    | "unknown";
}

export interface RaceListResponse {
  items: RaceSummary[];
  total: number;
  page: number;
  page_size: number;
}

export interface Exhibition {
  exhibition_course: number | null;
  exhibition_start_timing: string | null;
  exhibition_time_seconds: string | null;
  tilt: string | null;
  half_lap_time_seconds: string | null;
  lap_time_seconds: string | null;
  cornering_time_seconds: string | null;
  straight_time_seconds: string | null;
  observed_at: string;
  source: string | null;
  lap_source: string | null;
}

export interface RaceEntry {
  lane: number;
  racer_registration_number: string | null;
  racer_name: string | null;
  class_name: string | null;
  motor_number: number | null;
  boat_number: number | null;
  weight_kg: string | null;
  exhibition: Exhibition | null;
  part_replacements: Array<{
    part_name: string;
    quantity: number;
    replaced_at: string;
  }>;
}

export interface RaceDetail extends RaceSummary {
  distance_m: number | null;
  weather: {
    weather: string | null;
    air_temperature_c: string | null;
    water_temperature_c: string | null;
    wind_direction: string | null;
    wind_speed_mps: string | null;
    wave_height_cm: number | null;
    observed_at: string;
  } | null;
  entries: RaceEntry[];
  result: {
    winning_technique: string | null;
    trifecta_combination: string | null;
    trifecta_payout_yen: number | null;
    trifecta_popularity_rank: number | null;
    trifecta_refunded: boolean;
    finalized_at: string | null;
    source: string | null;
    entries: Array<{
      lane: number;
      finish_position: number | null;
      actual_course: number | null;
      actual_start_timing: string | null;
      status: string | null;
    }>;
  } | null;
}

export interface Contribution {
  key: string;
  label: string;
  raw_value: string | null;
  points: string;
  explanation: string;
}

export interface AnalysisItem {
  lane: number;
  rank: number;
  score: string;
  confidence: string;
  contributions: Contribution[];
  warnings: string[];
}

export interface RaceAnalysis {
  race_id: string;
  profile_version: string;
  calculated_at: string;
  data_cutoff_at: string;
  items: AnalysisItem[];
  disclaimer: string;
}

export interface SourceTable {
  schema_name: string;
  table_name: string;
  estimated_rows: number | null;
  columns: Array<{
    name: string;
    data_type: string;
    nullable: boolean;
    null_fraction: number | null;
    distinct_estimate: number | null;
  }>;
  primary_key: string[];
}

export interface SourceInspection {
  inspected_at: string;
  database_name: string;
  tables: SourceTable[];
}

export interface EvaluationSummary {
  date_from: string | null;
  date_to: string | null;
  profile_version: string;
  calculated_at: string;
  metrics: {
    race_count: number;
    top_1_accuracy: number;
    top_2_coverage: number;
    top_3_coverage: number;
    average_winner_rank: number;
    lane_1_baseline_accuracy: number;
  };
  notes: string[];
}

export interface ImportBatch {
  id: string;
  status: string;
  started_at: string;
  completed_at: string | null;
  rows_read: number;
  rows_written: number;
  errors_count: number;
  high_water_mark: string | null;
  official_results: {
    eligible_races: number;
    checked_races: number;
    finalized_races: number;
    pending_races: number;
    errors_count: number;
    already_running: boolean;
  };
  official_exhibitions: {
    eligible_races: number;
    checked_races: number;
    imported_races: number;
    pending_races: number;
    errors_count: number;
    already_running: boolean;
  };
  official_win_odds: {
    eligible_races: number;
    checked_races: number;
    imported_races: number;
    pending_races: number;
    errors_count: number;
    already_running: boolean;
  };
  official_trifecta_odds: {
    eligible_races: number;
    checked_races: number;
    imported_races: number;
    pending_races: number;
    errors_count: number;
    already_running: boolean;
  };
  boatcast_laps: {
    eligible_races: number;
    checked_races: number;
    imported_races: number;
    pending_races: number;
    errors_count: number;
    already_running: boolean;
  };
}

export interface TwoBoatFlowSummary {
  race_id: string;
  escape_assessment: string;
  likely_two_three_condition: boolean;
  has_tickets: boolean;
  ticket_count: number;
  hit: boolean | null;
}

export interface TwoBoatFlow {
  race_id: string;
  win_odds_source: string | null;
  popularity_source: string | null;
  win_odds_observed_at: string | null;
  status: "pass" | "review";
  outer_lane: number | null;
  outer_outer_lane: number | null;
  likely_lanes: number[];
  escape_assessment:
    | "likely"
    | "unlikely"
    | "low_confidence"
    | "uncertain"
    | "not_assessed";
  likely_two_three_condition: boolean;
  metrics: Array<{
    lane: number;
    popularity_rank: number | null;
    win_odds: string | null;
    reference_rank: number | null;
    exhibition_start_timing: string | null;
    exhibition_time: string | null;
    lap_time: string | null;
    exhibition_time_corrected: string | null;
    lap_time_corrected: string | null;
    exhibition_rank: number | null;
    lap_rank: number | null;
    course_avg_start_rank: string | null;
    course_avg_start_timing: string | null;
    nationwide_win_rate: string | null;
    course_top3_rate: string | null;
    course_starts: number | null;
    course_stats_snapshot_date: string | null;
    course_stats_source: string | null;
    ap: boolean;
  }>;
  steps: Array<{
    number: number;
    result: string;
    detail: string;
  }>;
  tickets: Array<{
    combination: [number, number, number];
    odds: string | null;
    popularity_rank: number | null;
  }>;
  composite_odds: string | null;
  decision: string;
  disclaimer: string;
}

export interface TwoBoatEvaluation {
  data_source: "live_saved" | "source_database";
  date_from: string;
  date_to: string;
  result_available_races: number;
  live_complete_races: number;
  excluded_incomplete_live_races: number;
  official_exhibition_covered_races: number;
  boatcast_lap_covered_races: number;
  popularity_covered_races: number;
  total_finalized_races: number;
  gap_triggered_races: number;
  insufficient_data_races: number;
  triggered_races: number;
  trigger_rate: number | null;
  likely_boat_win_rate: number | null;
  likely_boat_top3_rate: number | null;
  triggered_lane_1_win_rate: number | null;
  ticket_generated_races: number;
  ticket_hit_rate: number | null;
  average_ticket_count: number | null;
  escape_assessment_accuracy: number | null;
  escape_assessed_races: number;
  course_stats_covered_races: number;
  course_stats_coverage_rate: number | null;
  course_stats_history_available_from: string;
  course_stats_initial_snapshot_uncertain_through: string;
  snapshot_lag_days_min: number | null;
  snapshot_lag_days_median: number | null;
  snapshot_lag_days_max: number | null;
  odds_covered_races: number;
  flat_stake_return_rate: number | null;
  notes: string[];
}

export interface LabRefresh {
  eligible_races: number;
  complete_races: number;
  predictions_created: number;
  settlements_created: number;
  already_running: boolean;
}

export interface LabStrategySummary {
  strategy_code: string;
  strategy_version: string;
  strategy_name: string;
  description: string;
  prediction_count: number;
  applicable_count: number;
  settled_count: number;
  hit_count: number;
  hit_rate: number | null;
  total_stake_yen: number;
  total_returned_yen: number;
  profit_yen: number;
  return_rate: number | null;
  max_payout_excluded_return_rate: number | null;
}

export interface LabPrediction {
  prediction_id: string;
  race_id: string;
  race_date: string;
  venue_code: string;
  venue_name: string;
  race_number: number;
  scheduled_at: string | null;
  strategy_code: string;
  strategy_version: string;
  strategy_name: string;
  status: "ready" | "skipped";
  skip_reason: string | null;
  likely_lanes: number[];
  strong_threat_lanes: number[];
  threat_scores: Record<string, number>;
  tickets: Array<{
    combination: [number, number, number];
    stake_yen: number;
  }>;
  created_at: string;
  settlement: {
    winning_combination: string | null;
    refunded: boolean;
    hit: boolean | null;
    stake_yen: number;
    returned_yen: number;
    profit_yen: number;
    settled_at: string;
  } | null;
}

export interface LabDashboard {
  date_from: string;
  date_to: string;
  calculated_at: string;
  summaries: LabStrategySummary[];
  recent_predictions: LabPrediction[];
  notes: string[];
}
