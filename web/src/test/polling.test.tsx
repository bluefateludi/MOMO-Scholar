import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { RunApi, RunDetail } from "../api/contracts";
import { ApiError } from "../api/client";
import { demoRun } from "../api/fixtures";
import { useRunPolling } from "../polling/useRunPolling";
import type { TechScoutApi, TechScoutRunDetail } from "../api/contracts";
import { techScoutRun } from "../api/techscoutFixtures";
import { useTechScoutRunPolling } from "../polling/useTechScoutRunPolling";

afterEach(() => vi.useRealTimers());
describe("run polling", () => {
  it("stops after a terminal response", async () => {
    const getRun = vi.fn().mockResolvedValue({ data: demoRun }); const api = { getRun } as unknown as RunApi;
    const { result } = renderHook(() => useRunPolling(demoRun.id, api));
    await waitFor(() => expect(result.current.run?.status).toBe("completed_with_degradation"));
    expect(getRun).toHaveBeenCalledTimes(1);
  });

  it("keeps the last run state when connectivity is lost", async () => {
    vi.useFakeTimers(); const running: RunDetail = { ...demoRun, demo: false, origin: "live", status: "running", phase: "analysis", has_report: false };
    const getRun = vi.fn().mockResolvedValueOnce({ data: running, retryAfterSeconds: .001 }).mockRejectedValueOnce(new TypeError("offline")); const api = { getRun } as unknown as RunApi;
    const { result } = renderHook(() => useRunPolling(running.id, api));
    await act(async () => { await Promise.resolve(); });
    await act(async () => { vi.advanceTimersByTime(5); await Promise.resolve(); });
    expect(result.current.run?.status).toBe("running"); expect(result.current.connectionLost).toBe(true);
  });

  it("respects Retry-After and stops on failed or interrupted terminal states", async () => {
    vi.useFakeTimers();
    const running: RunDetail = { ...demoRun, demo: false, origin: "live", status: "running", phase: "analysis", has_report: false };
    const failed: RunDetail = { ...running, status: "failed", phase: "terminal" };
    const getRun = vi.fn().mockResolvedValueOnce({ data: running, retryAfterSeconds: .01 }).mockResolvedValueOnce({ data: failed });
    const api = { getRun } as unknown as RunApi;
    const { result } = renderHook(() => useRunPolling(running.id, api));
    await act(async () => { await Promise.resolve(); });
    expect(getRun).toHaveBeenCalledTimes(1);
    await act(async () => { vi.advanceTimersByTime(9); await Promise.resolve(); });
    expect(getRun).toHaveBeenCalledTimes(1);
    await act(async () => { vi.advanceTimersByTime(1); await Promise.resolve(); });
    expect(result.current.run?.status).toBe("failed");
    await act(async () => { vi.advanceTimersByTime(60_000); await Promise.resolve(); });
    expect(getRun).toHaveBeenCalledTimes(2);
  });

  it("stops on run_not_found without calling it a connection loss", async () => {
    const getRun = vi.fn().mockRejectedValue(new ApiError(404, "run_not_found", "not found"));
    const api = { getRun } as unknown as RunApi;
    const { result } = renderHook(() => useRunPolling(demoRun.id, api));
    await waitFor(() => expect(result.current.error?.code).toBe("run_not_found"));
    expect(result.current.connectionLost).toBe(false);
    expect(getRun).toHaveBeenCalledTimes(1);
  });

  it("pauses while hidden and fetches immediately when visible", async () => {
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    const getRun = vi.fn().mockResolvedValue({ data: demoRun });
    const api = { getRun } as unknown as RunApi;
    renderHook(() => useRunPolling(demoRun.id, api));
    await act(async () => { await Promise.resolve(); });
    expect(getRun).not.toHaveBeenCalled();
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); await Promise.resolve(); });
    expect(getRun).toHaveBeenCalledTimes(1);
  });
});

describe("TechScout polling", () => {
  it("keeps two-second polling semantics and stops at a terminal projection", async () => {
    vi.useFakeTimers();
    const running: TechScoutRunDetail = { ...techScoutRun, synthetic: false, status: "running", progress: { ...techScoutRun.progress, stage: "research", completed_stages: ["plan"] } };
    const getRun = vi.fn().mockResolvedValueOnce({ data: running, retryAfterSeconds: 2 }).mockResolvedValueOnce({ data: techScoutRun });
    const api = { getRun } as unknown as TechScoutApi;
    const { result } = renderHook(() => useTechScoutRunPolling(running.id, api));
    await act(async () => { await Promise.resolve(); }); expect(getRun).toHaveBeenCalledTimes(1);
    await act(async () => { vi.advanceTimersByTime(1999); await Promise.resolve(); }); expect(getRun).toHaveBeenCalledTimes(1);
    await act(async () => { vi.advanceTimersByTime(1); await Promise.resolve(); }); expect(result.current.run?.status).toBe("completed");
    await act(async () => { vi.advanceTimersByTime(30_000); await Promise.resolve(); }); expect(getRun).toHaveBeenCalledTimes(2);
  });
});
