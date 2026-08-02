import { useCallback, useEffect, useRef, useState } from "react";
import type { RunApi, RunDetail } from "../api/contracts";
import { ApiError } from "../api/client";

const terminal = new Set(["completed", "completed_with_degradation", "failed", "interrupted"]);
export function useRunPolling(id: string, api: RunApi) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [connectionLost, setConnectionLost] = useState(false);
  const [loading, setLoading] = useState(true);
  const failures = useRef(0);
  const timer = useRef<number | undefined>(undefined);

  const poll = useCallback(async () => {
    if (document.visibilityState === "hidden") return;
    try {
      const response = await api.getRun(id);
      setRun(response.data); setError(null); setConnectionLost(false); setLoading(false); failures.current = 0;
      if (!terminal.has(response.data.status)) timer.current = window.setTimeout(poll, (response.retryAfterSeconds ?? 2) * 1000);
    } catch (caught) {
      setLoading(false);
      if (caught instanceof ApiError) {
        setError(caught);
        setConnectionLost(false);
        if (caught.status === 404 && caught.code === "run_not_found") return;
      } else {
        setConnectionLost(true);
      }
      failures.current += 1;
      const base = Math.min(30, 2 * 2 ** (failures.current - 1));
      timer.current = window.setTimeout(poll, (base + Math.random() * Math.min(1, base * 0.2)) * 1000);
    }
  }, [api, id]);

  useEffect(() => {
    void poll();
    const onVisibility = () => { if (document.visibilityState === "visible") { window.clearTimeout(timer.current); void poll(); } };
    document.addEventListener("visibilitychange", onVisibility);
    return () => { window.clearTimeout(timer.current); document.removeEventListener("visibilitychange", onVisibility); };
  }, [poll]);
  return { run, error, connectionLost, loading, refresh: poll };
}
