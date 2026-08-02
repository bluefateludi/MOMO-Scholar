import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { RunApi, RunDetail } from "../api/contracts";
import { demoRun } from "../api/fixtures";
import { useRunPolling } from "../polling/useRunPolling";

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
});
