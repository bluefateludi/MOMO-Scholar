import { useCallback, useEffect, useRef, useState } from "react";
import type { TechScoutApi, TechScoutRunDetail } from "../api/contracts";
import { ApiError } from "../api/client";

const terminal = new Set(["completed", "completed_with_limitations", "failed"]);
export function useTechScoutRunPolling(id: string, api: TechScoutApi) {
  const [run, setRun] = useState<TechScoutRunDetail | null>(null); const [error, setError] = useState<ApiError | null>(null); const [connectionLost, setConnectionLost] = useState(false); const [loading, setLoading] = useState(true); const failures = useRef(0); const timer = useRef<number | undefined>(undefined);
  const poll = useCallback(async () => {
    if (document.visibilityState === "hidden") return;
    try { const response = await api.getRun(id); setRun(response.data); setError(null); setConnectionLost(false); setLoading(false); failures.current = 0; if (!terminal.has(response.data.status)) timer.current = window.setTimeout(poll, (response.retryAfterSeconds ?? 2) * 1000); }
    catch (caught) { setLoading(false); if (caught instanceof ApiError) { setError(caught); setConnectionLost(false); if (caught.status === 404) return; } else setConnectionLost(true); failures.current += 1; const base = Math.min(30, 2 * 2 ** (failures.current - 1)); timer.current = window.setTimeout(poll, (base + Math.random() * Math.min(1, base * .2)) * 1000); }
  }, [api, id]);
  useEffect(() => { void poll(); const visible = () => { if (document.visibilityState === "visible") { window.clearTimeout(timer.current); void poll(); } }; document.addEventListener("visibilitychange", visible); return () => { window.clearTimeout(timer.current); document.removeEventListener("visibilitychange", visible); }; }, [poll]);
  return { run, error, connectionLost, loading };
}
