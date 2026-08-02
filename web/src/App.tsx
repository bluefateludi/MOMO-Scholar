import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { Layout } from "./components/Layout";
import { EvidencePage } from "./routes/EvidencePage";
import { HomePage } from "./routes/HomePage";
import { NotFoundPage } from "./routes/NotFoundPage";
import { PaperPage } from "./routes/PaperPage";
import { ReportPage } from "./routes/ReportPage";
import { RunPage } from "./routes/RunPage";

export const router = createBrowserRouter([{ element: <Layout/>, children: [{ path: "/", element: <HomePage/> }, { path: "/runs/:id", element: <RunPage/> }, { path: "/runs/:id/report", element: <ReportPage/> }, { path: "/runs/:id/papers/:paperId", element: <PaperPage/> }, { path: "/runs/:id/evidence/:evidenceId", element: <EvidencePage/> }, { path: "*", element: <NotFoundPage/> }] }]);
export function App() { return <RouterProvider router={router}/>; }
