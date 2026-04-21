import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { KeywordsPage } from "../../src/features/keywords/KeywordsPage";
import { jsonResponse, renderWithProviders } from "./utils";

describe("KeywordsPage", () => {
  let store: Array<{ id: number; term: string; locale: string; enabled: boolean; weight: number }>;

  beforeEach(() => {
    store = [];
    let nextId = 1;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        const method = (init?.method ?? "GET").toUpperCase();
        if (url.endsWith("/api/v1/config/keywords") && method === "GET") {
          return jsonResponse(store);
        }
        if (url.endsWith("/api/v1/config/keywords") && method === "POST") {
          const body = JSON.parse((init?.body as string) ?? "{}");
          const created = {
            id: nextId++,
            term: body.term,
            locale: body.locale ?? "en",
            enabled: body.enabled ?? true,
            weight: body.weight ?? 1,
          };
          store.push(created);
          return jsonResponse(created, 201);
        }
        return jsonResponse({}, 404);
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("creates a keyword via the form", async () => {
    renderWithProviders(<KeywordsPage />);
    const input = await screen.findByPlaceholderText(/keyword|Stichwort/i);
    await userEvent.type(input, "Invoice");
    const addButton = screen.getByRole("button", { name: /Add|Hinzufügen/i });
    await userEvent.click(addButton);
    await waitFor(() => {
      expect(screen.getByText("Invoice")).toBeInTheDocument();
    });
  });
});
