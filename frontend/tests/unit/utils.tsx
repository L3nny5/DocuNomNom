import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderOptions } from "@testing-library/react";
import { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import "../../src/i18n";

export function renderWithProviders(
  ui: ReactElement,
  opts: { route?: string; path?: string } & Omit<RenderOptions, "wrapper"> = {},
) {
  const { route = "/", path } = opts;
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>
        {path ? (
          <Routes>
            <Route path={path} element={ui} />
          </Routes>
        ) : (
          ui
        )}
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
