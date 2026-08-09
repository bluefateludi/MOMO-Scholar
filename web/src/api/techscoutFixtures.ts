import type { TechScoutEvidence, TechScoutReport, TechScoutRunDetail, TracePage } from "./contracts";
import { generatedTechScoutFixture } from "./techscoutFixtures.generated";

export const TECHSCOUT_FIXTURE_ID = "10000000-0000-4000-8000-000000000001";
export const syntheticNotice = "Synthetic Wave 1 contract fixture — not live research or evaluation evidence.";

export const techScoutRun = generatedTechScoutFixture.detail as unknown as TechScoutRunDetail;
export const techScoutCandidates = techScoutRun.candidates;
export const techScoutEvidence = generatedTechScoutFixture.evidence as unknown as TechScoutEvidence[];
export const techScoutReport = generatedTechScoutFixture.report as unknown as TechScoutReport;
export const fixtureTrace = generatedTechScoutFixture.trace as unknown as TracePage;
