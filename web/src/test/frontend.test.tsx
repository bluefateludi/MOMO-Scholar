import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { techScoutApi } from "../api";
import { TECHSCOUT_FIXTURE_ID, fixtureTrace, syntheticNotice, techScoutEvidence, techScoutReport, techScoutRun } from "../api/techscoutFixtures";
import { CandidatePage } from "../routes/CandidatePage";
import { EvidencePage } from "../routes/EvidencePage";
import { HomePage } from "../routes/HomePage";
import { ReportPage } from "../routes/ReportPage";
import { RunPage } from "../routes/RunPage";

beforeEach(() => {
  vi.spyOn(techScoutApi, "listRuns").mockResolvedValue({ data: { items: [techScoutRun], next_cursor: null } });
  vi.spyOn(techScoutApi, "getRun").mockResolvedValue({ data: techScoutRun });
  vi.spyOn(techScoutApi, "getReport").mockResolvedValue({ data: techScoutReport });
  vi.spyOn(techScoutApi, "getEvidence").mockResolvedValue({ data: { items: techScoutEvidence } });
  vi.spyOn(techScoutApi, "getEvidenceItem").mockResolvedValue({ data: techScoutEvidence[0] });
  vi.spyOn(techScoutApi, "getCandidate").mockResolvedValue({ data: techScoutRun.candidates[0] });
  vi.spyOn(techScoutApi, "getTrace").mockResolvedValue({ data: fixtureTrace });
});

describe("TechScout task input", () => {
  it("captures environment, hard constraints, candidates, and mode", async () => {
    render(<MemoryRouter><HomePage/></MemoryRouter>);
    expect(screen.getByRole("textbox", { name: /python version/i })).toHaveValue("3.11");
    expect(screen.getByRole("textbox", { name: /hard constraints/i })).toHaveValue("local persistence\nmetadata equality filtering");
    expect(screen.getByRole("textbox", { name: /candidate shortlist/i })).toHaveValue("Chroma, Qdrant Local, pgvector");
    expect(screen.getByRole("radio", { name: "Fast" })).toBeChecked();
    expect(await screen.findByText(/Synthetic offline fixture/i)).toBeInTheDocument();
  });

  it("navigates after the synthetic mock accepts a task", async () => {
    vi.spyOn(techScoutApi, "createRun").mockResolvedValue({ data: techScoutRun });
    render(<MemoryRouter><Routes><Route path="/" element={<HomePage/>}/><Route path="/runs/:id" element={<LocationProbe/>}/></Routes></MemoryRouter>);
    await userEvent.type(screen.getByRole("textbox", { name: /decision question/i }), "Choose a safe local vector store");
    await userEvent.click(screen.getByRole("button", { name: /start techscout task/i }));
    expect(await screen.findByText(`/runs/${TECHSCOUT_FIXTURE_ID}`)).toBeInTheDocument();
  });
});

describe("fixture-backed Wave 1 views", () => {
  it("renders the four-stage progress, candidate, recovery, approval, and collapsed Trace", async () => {
    render(<MemoryRouter initialEntries={[`/runs/${TECHSCOUT_FIXTURE_ID}`]}><Routes><Route path="/runs/:id" element={<RunPage/>}/></Routes></MemoryRouter>);
    expect(await screen.findByText(techScoutRun.question)).toBeInTheDocument();
    for (const stage of ["Plan", "Research", "Verify", "Decide"]) expect(screen.getByText(stage)).toBeInTheDocument();
    expect(screen.getByText(/not needed · 0\/1/i)).toBeInTheDocument();
    expect(screen.getByText(/not required/i)).toBeInTheDocument();
    expect(screen.queryByText(/Investigation plan frozen/i)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /trace feed/i }));
    expect(await screen.findByText(/Investigation plan frozen/i)).toBeInTheDocument();
  });

  it("keeps the synthetic warning on report, candidate, and evidence views", async () => {
    const routes = <Routes><Route path="/runs/:id/report" element={<ReportPage/>}/><Route path="/runs/:id/candidates/:candidateId" element={<CandidatePage/>}/><Route path="/runs/:id/evidence/:evidenceId" element={<EvidencePage/>}/></Routes>;
    const { unmount } = render(<MemoryRouter initialEntries={[`/runs/${TECHSCOUT_FIXTURE_ID}/report`]}>{routes}</MemoryRouter>);
    expect(await screen.findByRole("note")).toHaveTextContent(syntheticNotice); expect(screen.getByText(/Allowlisted checks/i)).toBeInTheDocument(); unmount();
    const candidate = render(<MemoryRouter initialEntries={[`/runs/${TECHSCOUT_FIXTURE_ID}/candidates/chroma`]}>{routes}</MemoryRouter>);
    expect(await screen.findByRole("note")).toHaveTextContent(syntheticNotice); candidate.unmount();
    render(<MemoryRouter initialEntries={[`/runs/${TECHSCOUT_FIXTURE_ID}/evidence/ev-chroma-persistence`]}>{routes}</MemoryRouter>);
    expect(await screen.findByRole("note")).toHaveTextContent(syntheticNotice); expect(screen.getByText(/no external URL/i)).toBeInTheDocument();
  });
});

function LocationProbe() { return <span>{useLocation().pathname}</span>; }
