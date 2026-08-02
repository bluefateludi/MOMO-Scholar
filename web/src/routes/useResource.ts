import { useEffect, useState } from "react";
import { ApiError } from "../api/client";

export function useResource<T>(load: () => Promise<T>, dependencies: unknown[]) {
  const [data, setData] = useState<T | null>(null); const [error, setError] = useState<ApiError | null>(null);
  useEffect(() => { let active = true; setData(null); setError(null); load().then((value) => active && setData(value)).catch((caught) => active && setError(caught instanceof ApiError ? caught : new ApiError(0, "connection_lost", "The local API could not be reached."))); return () => { active = false; }; }, dependencies); // eslint-disable-line react-hooks/exhaustive-deps
  return { data, error };
}
