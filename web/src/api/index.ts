import type { RunApi } from "./contracts";
import { httpApi } from "./client";
import { mockApi } from "./mock";
import { techScoutHttpApi } from "./techscout";
import { techScoutMockApi } from "./techscoutMock";

export const isMockMode = import.meta.env.VITE_API_MODE === "mock";
export const api: RunApi = isMockMode ? mockApi : httpApi;
export const techScoutApi = isMockMode ? techScoutMockApi : techScoutHttpApi;
