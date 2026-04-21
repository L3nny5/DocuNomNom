import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import { AppLayout } from "../../src/app/AppLayout";
import { renderWithProviders } from "./utils";

describe("AppLayout", () => {
  it("renders the app title and primary navigation links", () => {
    renderWithProviders(<AppLayout />);
    expect(screen.getByText("DocuNomNom")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Jobs/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /History|Verlauf/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Config|Konfiguration/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Keywords|Stichwörter/i })).toBeInTheDocument();
  });
});
