import { afterEach, describe, expect, it, vi } from "vitest";
import { httpApi, messageForCode } from "../api/client";
import { DEMO_ID, EV1, demoRun } from "../api/fixtures";

afterEach(() => vi.unstubAllGlobals());

describe("same-origin HTTP client", () => {
  it("uses /api/v1, preserves Location and respects Retry-After", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(demoRun), {
      status: 202,
      headers: { "Content-Type": "application/json", Location: `/api/v1/runs/${DEMO_ID}`, "Retry-After": "2" },
    }));
    vi.stubGlobal("fetch", fetchMock);
    const response = await httpApi.createRun(demoRun);
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/runs", expect.objectContaining({ method: "POST" }));
    expect(response.location).toBe(`/api/v1/runs/${DEMO_ID}`);
    expect(response.retryAfterSeconds).toBe(2);
  });

  it("URL-encodes opaque Evidence IDs exactly once", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({}), {
      status: 200, headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);
    const opaque = `${EV1}/part%?#`;
    await httpApi.getEvidenceItem(DEMO_ID, opaque);
    expect(fetchMock.mock.calls[0][0]).toBe(`/api/v1/runs/${DEMO_ID}/evidence/${encodeURIComponent(opaque)}`);
  });

  it.each([
    [404, "run_not_found"], [409, "artifact_not_ready"], [429, "run_busy"], [503, "queue_full"],
  ])("maps %s %s envelopes without exposing server text", async (status, code) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code, message: "raw server text", details: {} } }), {
      status, headers: { "Content-Type": "application/json" },
    })));
    await expect(httpApi.getRun(DEMO_ID)).rejects.toMatchObject({ status, code, message: messageForCode(code) });
  });
});
