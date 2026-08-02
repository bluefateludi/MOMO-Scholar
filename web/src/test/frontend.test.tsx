import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { demoRun, DEMO_ID, EV1 } from "../api/fixtures";
import { DemoBanner, ErrorPanel, RunBanner } from "../components/Feedback";
import { SafeMarkdown } from "../components/SafeMarkdown";
import { HomePage } from "../routes/HomePage";
import { ReportPage } from "../routes/ReportPage";

describe("create-run form", () => {
  it("shows frozen defaults and advanced retrieval settings", async () => {
    render(<MemoryRouter><HomePage/></MemoryRouter>);
    expect(screen.getByRole("spinbutton", { name: /paper count/i })).toHaveValue(3);
    expect(screen.getByRole("radio", { name: /pdf preferred/i })).toBeChecked();
    expect(screen.getByRole("radio", { name: "auto" })).toBeChecked();
    await userEvent.click(screen.getByText(/retrieval settings/i));
    expect(screen.getByRole("spinbutton", { name: /candidate k/i })).toHaveValue(30);
    expect(screen.getByRole("spinbutton", { name: /^top k/i })).toHaveValue(8);
    expect(screen.getByRole("spinbutton", { name: /evidence \/ paper/i })).toHaveValue(6);
  });

  it("blocks invalid cross-field settings before POST", async () => {
    render(<MemoryRouter><HomePage/></MemoryRouter>); const user = userEvent.setup();
    await user.type(screen.getByRole("textbox", { name: /research question/i }), "A valid research question");
    await user.click(screen.getByText(/retrieval settings/i));
    const candidate = screen.getByRole("spinbutton", { name: /candidate k/i }); await user.clear(candidate); await user.type(candidate, "2");
    await user.click(screen.getByRole("button", { name: /create research run/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Top K cannot exceed candidate K");
  });

  it("navigates immediately after the accepted mock POST", async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><Routes><Route path="/" element={<HomePage/>}/><Route path="/runs/:id" element={<LocationProbe/>}/></Routes></MemoryRouter>);
    await user.type(screen.getByRole("textbox", { name: /research question/i }), "A traceable review question");
    await user.click(screen.getByRole("button", { name: /create research run/i }));
    expect(await screen.findByText(/\/runs\//)).toBeInTheDocument();
  });
});

describe("safe research reading", () => {
  it("removes raw HTML and resolves exact Evidence markers", () => {
    render(<MemoryRouter><SafeMarkdown markdown={`Text [${EV1}] [missing:ev_999] <script>alert('x')</script> [bad](javascript:alert(1))`} runId={DEMO_ID} evidenceIds={[EV1]}/></MemoryRouter>);
    expect(document.querySelector("script")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Evidence" })).toHaveAttribute("href", `/runs/${DEMO_ID}/evidence/${encodeURIComponent(EV1)}`);
    expect(screen.getByText("bad").closest("a")).toHaveAttribute("href", "");
    expect(screen.getByText(/Unresolved Evidence/)).toBeInTheDocument();
  });

  it("keeps the synthetic-demo warning visible on the report", async () => {
    render(<MemoryRouter initialEntries={[`/runs/${DEMO_ID}/report`]}><Routes><Route path="/runs/:id/report" element={<ReportPage/>}/></Routes></MemoryRouter>);
    await waitFor(() => expect(screen.getByText("Synthetic offline demo")).toBeInTheDocument());
    expect(screen.getByText(/Not research output or evaluation evidence/i)).toBeInTheDocument();
    expect(screen.getByText("Rejected critical claims")).toBeInTheDocument();
  });

  it("announces the demo disclaimer as a note", () => {
    render(<DemoBanner/>); expect(screen.getByRole("note")).toHaveTextContent("No provider or network call");
  });

  it("presents terminal failures and corrupt artifacts without raw exceptions", () => {
    const failed = { ...demoRun, demo: false, origin: "live" as const, status: "failed" as const, has_report: false, manifest: { ...demoRun.manifest!, degradations: [], errors: [{ stage: "initializing", code: "provider_configuration_missing" }] } };
    const { rerender } = render(<MemoryRouter><RunBanner run={failed}/></MemoryRouter>);
    expect(screen.getByRole("alert")).toHaveTextContent("generation provider is not configured");
    rerender(<MemoryRouter><ErrorPanel code="artifact_corrupt" message="A saved artifact could not be safely read."/></MemoryRouter>);
    expect(screen.getByRole("alert")).toHaveTextContent("artifact_corrupt");
  });
});

function LocationProbe() { return <span>{useLocation().pathname}</span>; }
