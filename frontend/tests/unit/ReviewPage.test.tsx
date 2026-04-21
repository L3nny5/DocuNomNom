import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { ReviewPage } from "../../src/features/review/ReviewPage";
import { jsonResponse, renderWithProviders } from "./utils";

const sampleItem = {
  id: 4,
  part_id: 12,
  status: "open",
  job_id: 1,
  analysis_id: 1,
  file_id: 1,
  file_name: "bundle.pdf",
  start_page: 1,
  end_page: 8,
  confidence: 0.42,
  decision: "review_required",
  page_count: 8,
  finished_at: null,
};

describe("ReviewPage", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.includes("/api/v1/review")) {
          return jsonResponse({ items: [sampleItem], total: 1, limit: 100, offset: 0 });
        }
        return jsonResponse({}, 404);
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lists open review items", async () => {
    renderWithProviders(<ReviewPage />);
    expect(await screen.findByText("bundle.pdf")).toBeInTheDocument();
    expect(screen.getByText("1–8 / 8")).toBeInTheDocument();
  });
});
