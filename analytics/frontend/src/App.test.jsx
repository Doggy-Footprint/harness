import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";


const emptySummary = {
  runs: 0,
  completed_runs: 0,
  compliant_runs: 0,
  handoff_runs: 0,
  verifier_rounds: 0,
  verifier_retries: 0,
  seeds_run: 0,
  seeds_detected: 0,
  linked_cost_usd: 0,
  run_items: [],
};

const populatedSummary = {
  ...emptySummary,
  runs: 1,
  completed_runs: 1,
  compliant_runs: 1,
  linked_cost_usd: 1.25,
  run_items: [{ run_id: "run-1", contract: "sample", status: "complete", compliant: true }],
};

const detail = {
  run_id: "run-1",
  contract: "sample",
  contract_version: 1,
  status: "complete",
  compliant: true,
  compliance_reasons: [],
  events: [{ event: "workflow_start" }, { event: "workflow_end", status: "complete" }],
  verifier_rounds: 1,
  verifier_retries: 0,
  seeds_run: 0,
  seeds_detected: 0,
  transcript_metadata: { model: "model-a", input_tokens: 10, output_tokens: 5 },
  linked_cost_usd: 1.25,
};

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

function response(body, ok = true) {
  return Promise.resolve({ ok, status: ok ? 200 : 500, json: () => Promise.resolve(body) });
}

describe("contract v5 U5 A12 V8 dashboard states", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/");
    global.fetch = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders an accessible loading state while summary is pending", () => {
    const pending = deferred();
    fetch.mockReturnValue(pending.promise);
    render(<App apiBase="" />);
    expect(screen.getByRole("status")).toBeVisible();
  });

  it("renders an empty summary without run links", async () => {
    fetch.mockReturnValue(response(emptySummary));
    render(<App apiBase="" />);
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/summary"));
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText("0", { selector: "[data-metric='runs']" })).toBeVisible();
  });

  it("renders populated metrics and navigates from summary to run detail", async () => {
    fetch
      .mockReturnValueOnce(response(populatedSummary))
      .mockReturnValueOnce(response(detail));
    render(<App apiBase="" />);
    const runLink = await screen.findByRole("link", { name: /run-1/ });
    expect(screen.getByText("1", { selector: "[data-metric='runs']" })).toBeVisible();
    fireEvent.click(runLink);
    await waitFor(() => expect(fetch).toHaveBeenLastCalledWith("/api/runs/run-1"));
    expect(await screen.findByText("sample")).toBeVisible();
    expect(screen.getByText("complete")).toBeVisible();
  });

  it("renders an accessible API error state", async () => {
    fetch.mockReturnValue(response({}, false));
    render(<App apiBase="" />);
    expect(await screen.findByRole("alert")).toBeVisible();
  });
});
