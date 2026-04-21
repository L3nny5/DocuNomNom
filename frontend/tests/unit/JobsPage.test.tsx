import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { JobsPage } from "../../src/features/jobs/JobsPage";
import { jsonResponse, renderWithProviders } from "./utils";

const sampleJob = {
  id: 7,
  file_id: 1,
  file_name: "demo.pdf",
  status: "completed",
  attempt: 1,
  mode: "off",
  pipeline_version: "1.0.0",
  run_key: "run-key-7",
  error_code: null,
  error_msg: null,
  created_at: "2026-04-19T12:00:00",
  updated_at: "2026-04-19T12:00:01",
};

describe("JobsPage", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.includes("/api/v1/jobs/rescan")) {
          return jsonResponse({ enqueued: 2 });
        }
        if (url.includes("/api/v1/jobs")) {
          return jsonResponse({
            items: [sampleJob],
            total: 1,
            limit: 100,
            offset: 0,
          });
        }
        return jsonResponse({}, 404);
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders jobs returned by the API", async () => {
    renderWithProviders(<JobsPage />);
    expect(await screen.findByText("demo.pdf")).toBeInTheDocument();
    expect(screen.getByText(/run-key-7|#7|7/)).toBeTruthy();
  });

  it("triggers rescan and shows the enqueued count", async () => {
    renderWithProviders(<JobsPage />);
    await screen.findByText("demo.pdf");
    const button = screen.getByRole("button", { name: /Rescan|neu einlesen/i });
    await userEvent.click(button);
    await waitFor(() => {
      expect(
        screen.getByText((text) => /2/.test(text) && /Enqueued|eingereiht/i.test(text)),
      ).toBeInTheDocument();
    });
  });
});
