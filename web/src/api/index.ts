import type { RunApi } from "./contracts";
import { httpApi } from "./client";
import { mockApi } from "./mock";

export const isMockMode = import.meta.env.VITE_API_MODE !== "live";
export const api: RunApi = isMockMode ? mockApi : httpApi;
