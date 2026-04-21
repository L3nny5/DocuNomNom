import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../src/api/client";

describe("api client", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.endsWith("/api/v1/health")) {
          return new Response(JSON.stringify({ status: "ok", version: "0.3.0" }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        if (url.includes("/api/v1/jobs/9999")) {
          return new Response(
            JSON.stringify({ detail: { code: "not_found", message: "Job not found" } }),
            { status: 404, headers: { "Content-Type": "application/json" } },
          );
        }
        return new Response("{}", { status: 200 });
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns parsed JSON for 2xx responses", async () => {
    const res = await api.health();
    expect(res.status).toBe("ok");
  });

  it("throws an ApiError shape for non-2xx responses", async () => {
    await expect(api.getJob(9999)).rejects.toMatchObject({
      status: 404,
      code: "not_found",
    });
  });
});
