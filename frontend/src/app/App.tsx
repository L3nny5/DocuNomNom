import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useMemo } from "react";
import { createBrowserRouter, Navigate, RouterProvider } from "react-router-dom";
import { AppLayout } from "./AppLayout";
import { ConfigPage } from "../features/config/ConfigPage";
import { HistoryPage } from "../features/history/HistoryPage";
import { JobDetailPage } from "../features/jobs/JobDetailPage";
import { JobsPage } from "../features/jobs/JobsPage";
import { KeywordsPage } from "../features/keywords/KeywordsPage";
import { ReviewDetailPage } from "../features/review/ReviewDetailPage";
import { ReviewPage } from "../features/review/ReviewPage";

export function App() {
  const queryClient = useMemo(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: 1,
            staleTime: 5_000,
          },
        },
      }),
    [],
  );

  const router = useMemo(
    () =>
      createBrowserRouter([
        {
          path: "/",
          element: <AppLayout />,
          children: [
            { index: true, element: <Navigate to="/jobs" replace /> },
            { path: "jobs", element: <JobsPage /> },
            { path: "jobs/:id", element: <JobDetailPage /> },
            { path: "review", element: <ReviewPage /> },
            { path: "review/:id", element: <ReviewDetailPage /> },
            { path: "history", element: <HistoryPage /> },
            { path: "config", element: <ConfigPage /> },
            { path: "keywords", element: <KeywordsPage /> },
          ],
        },
      ]),
    [],
  );

  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
