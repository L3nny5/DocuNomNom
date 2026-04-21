import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReviewDetailPage } from "../../src/features/review/ReviewDetailPage";
import { jsonResponse, renderWithProviders } from "./utils";

const detail = {
  item: {
    id: 9,
    part_id: 33,
    status: "open",
    job_id: 1,
    analysis_id: 1,
    file_id: 1,
    file_name: "stack.pdf",
    start_page: 1,
    end_page: 6,
    confidence: 0.5,
    decision: "review_required",
    page_count: 6,
    finished_at: null,
  },
  markers: [{ id: 1, page_no: 3, kind: "start", ts: null }],
  proposals: [
    {
      id: 11,
      source: "rule",
      start_page: 1,
      end_page: 6,
      confidence: 0.5,
      reason_code: "seed",
    },
  ],
  pdf_url: "/api/v1/review/9/pdf",
};

describe("ReviewDetailPage", () => {
  let putPayload: unknown = null;

  beforeEach(() => {
    putPayload = null;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        const method = init?.method ?? "GET";
        if (url.endsWith("/api/v1/review/9") && method === "GET") {
          return jsonResponse(detail);
        }
        if (url.endsWith("/api/v1/review/9/markers") && method === "PUT") {
          putPayload = init?.body ? JSON.parse(String(init.body)) : null;
          return jsonResponse([{ id: 2, page_no: 4, kind: "start", ts: null }]);
        }
        return jsonResponse({}, 404);
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders proposals, markers and the PDF iframe", async () => {
    renderWithProviders(<ReviewDetailPage />, {
      route: "/review/9",
      path: "/review/:id",
    });
    expect(await screen.findByText("stack.pdf")).toBeInTheDocument();
    expect(screen.getByText(/1.*6.*\/.*6/)).toBeInTheDocument();
    expect(screen.getByText("Start: page 3")).toBeInTheDocument();
    expect(screen.getByText(/seed/)).toBeInTheDocument();
    expect(screen.getByTitle(/PDF/i)).toHaveAttribute("src", "/api/v1/review/9/pdf");
  });

  it("adds a marker and saves the new set", async () => {
    renderWithProviders(<ReviewDetailPage />, {
      route: "/review/9",
      path: "/review/:id",
    });
    await screen.findByText("stack.pdf");

    const input = screen.getByLabelText("Page number") as HTMLInputElement;
    await userEvent.clear(input);
    await userEvent.type(input, "5");
    await userEvent.click(screen.getByRole("button", { name: "Add marker" }));

    expect(screen.getByText("Start: page 3")).toBeInTheDocument();
    expect(screen.getByText("Start: page 5")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Save markers" }));

    await waitFor(() => {
      expect(putPayload).toEqual({
        markers: [
          { page_no: 3, kind: "start" },
          { page_no: 5, kind: "start" },
        ],
      });
    });
  });

  it("rejects out-of-range pages with an inline error", async () => {
    renderWithProviders(<ReviewDetailPage />, {
      route: "/review/9",
      path: "/review/:id",
    });
    await screen.findByText("stack.pdf");

    const input = screen.getByLabelText("Page number") as HTMLInputElement;
    await userEvent.clear(input);
    await userEvent.type(input, "99");
    await userEvent.click(screen.getByRole("button", { name: "Add marker" }));

    expect(screen.getByText(/integer between 1 and 6/i)).toBeInTheDocument();
  });
});
