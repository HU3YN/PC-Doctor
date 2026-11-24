import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CollectorInfo } from "../api";
import { GetCollectorPage } from "./GetCollectorPage";

function show(info: Partial<CollectorInfo>) {
  const body: CollectorInfo = {
    available: true,
    sha256: "ab".repeat(32),
    includes_presentmon: true,
    lan_addresses: [],
    photo_reading: false,
    ...info,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(body), { status: 200 })),
  );
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <GetCollectorPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("GetCollectorPage", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("offers one download and says PresentMon is inside it", async () => {
    show({ includes_presentmon: true });
    expect(await screen.findByText(/PresentMon .* is inside the zip/)).toBeInTheDocument();
    // One zip is everything: there is no second download to remember.
    const downloads = screen.getAllByRole("link").filter((link) => link.hasAttribute("download"));
    expect(downloads.map((link) => link.getAttribute("href"))).toEqual(["/api/collector.zip"]);
    expect(document.body.textContent).not.toMatch(/presentmon\.zip|Get-Tools/);
    expect(document.body.textContent).toMatch(/same file as the collector release/);
  });

  it("says the collector fetches PresentMon itself when the server lacks it", async () => {
    show({ includes_presentmon: false });
    expect(await screen.findByText(/is not in this\s+server.s zip/)).toBeInTheDocument();
    expect(screen.getByText(/fetches and checks it itself on the first capture/)).toBeInTheDocument();
    // A zip without PresentMon is not the release: never claim it is.
    expect(document.body.textContent).toMatch(/not the same file as the GitHub release/);
    expect(document.body.textContent).not.toMatch(/gh attestation verify/);
    const downloads = screen.getAllByRole("link").filter((link) => link.hasAttribute("download"));
    expect(downloads.map((link) => link.getAttribute("href"))).toEqual(["/api/collector.zip"]);
  });
});
