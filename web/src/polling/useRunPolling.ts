import type { RunApi } from "../api/contracts";
import { usePollingResource } from "./usePollingResource";

const terminal = new Set(["completed", "completed_with_degradation", "failed", "interrupted"]);
export function useRunPolling(id: string, api: RunApi) {
  return usePollingResource(id, api, terminal);
}
