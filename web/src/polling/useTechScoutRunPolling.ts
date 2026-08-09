import type { TechScoutApi } from "../api/contracts";
import { usePollingResource } from "./usePollingResource";

const terminal = new Set(["completed", "completed_with_limitations", "failed"]);
export function useTechScoutRunPolling(id: string, api: TechScoutApi) {
  return usePollingResource(id, api, terminal);
}
