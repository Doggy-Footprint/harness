import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";

const emptySummary = { runs: 0, completed_runs: 0, compliant_runs: 0, handoff_runs: 0,
  verifier_rounds: 0, verifier_retries: 0, seeds_run: 0, seeds_detected: 0,
  linked_cost_usd: 0, run_items: [] };
const populatedSummary = { ...emptySummary, runs: 1, completed_runs: 1, compliant_runs: 1,
  linked_cost_usd: 1.25, run_items: [{ run_id: "run-1", spec: "analytics", status: "complete", compliant: true }] };
const detail = { run_id: "run-1", spec: "analytics", spec_version: 1, status: "complete", compliant: true,
  compliance_reasons: [], events: [{ event: "workflow_start" }, { event: "workflow_end", status: "complete" }],
  verifier_rounds: 1, verifier_retries: 0, seeds_run: 0, seeds_detected: 0,
  transcript_metadata: [{ client: "claude", session_id: "session-1", path: "session.jsonl", model: "model-a",
    input_tokens: 10, output_tokens: 5, cache_read_tokens: 0, cache_write_5m_tokens: 0, cache_write_1h_tokens: 0, linked_cost_usd: 1.25 }], linked_cost_usd: 1.25 };

function deferred() { let resolve; const promise = new Promise((done) => { resolve = done; }); return { promise, resolve }; }
function response(body, ok = true) { return Promise.resolve({ ok, status: ok ? 200 : 500, json: () => Promise.resolve(body) }); }

describe("spec v1 V5/Q3 dashboard states", () => {
  beforeEach(() => { window.history.replaceState({}, "", "/"); global.fetch = vi.fn(); });
  afterEach(() => vi.restoreAllMocks());

  it("renders an accessible loading state while summary is pending", () => {
    const pending = deferred(); fetch.mockReturnValue(pending.promise); render(<App apiBase="" />);
    expect(screen.getByRole("status")).toBeVisible();
  });

  it("renders an empty summary without run links", async () => {
    fetch.mockReturnValue(response(emptySummary)); render(<App apiBase="" />);
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/summary"));
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText("0", { selector: "[data-metric='runs']" })).toBeVisible();
  });

  it("renders populated metrics and navigates to accessible run detail", async () => {
    fetch.mockReturnValueOnce(response(populatedSummary)).mockReturnValueOnce(response(detail)); render(<App apiBase="" />);
    const link = await screen.findByRole("link", { name: /run-1/ });
    fireEvent.click(link);
    await waitFor(() => expect(fetch).toHaveBeenLastCalledWith("/api/runs/run-1"));
    expect(await screen.findByText("analytics")).toBeVisible();
    expect(screen.getByText("complete")).toBeVisible();
  });

  it("renders an accessible API error state", async () => {
    fetch.mockReturnValue(response({}, false)); render(<App apiBase="" />);
    expect(await screen.findByRole("alert")).toBeVisible();
  });
});

describe("spec v2 U2/F7/Q3 summary and detail field coverage", () => {
  beforeEach(() => { cleanup(); window.history.replaceState({}, "", "/"); global.fetch = vi.fn(); });
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  const richSummary = {
    runs: 8, completed_runs: 6, compliant_runs: 3, handoff_runs: 2,
    verifier_rounds: 5, verifier_retries: 4, seeds_run: 9, seeds_detected: 1,
    linked_cost_usd: 12.34,
    run_items: [{ run_id: "run-detail", spec: "analytics", status: "handoff", compliant: false }],
  };
  const richDetail = {
    run_id: "run-detail", spec: "analytics", spec_version: 7, status: "handoff", compliant: false,
    compliance_reasons: ["expected_one_start", "identity_mismatch"],
    events: [{ event: "workflow_start" }, { event: "workflow_end", status: "handoff" }],
    verifier_rounds: 5, verifier_retries: 4, seeds_run: 9, seeds_detected: 1,
    transcript_metadata: [
      { client: "claude", session_id: "session-a", path: "a.jsonl", model: "model-claude",
        input_tokens: 10, output_tokens: 20, cache_read_tokens: 0, cache_write_5m_tokens: 0, cache_write_1h_tokens: 0, linked_cost_usd: 6.5 },
      { client: "codex", session_id: "session-b", path: "b.jsonl", model: "model-codex",
        input_tokens: 30, output_tokens: 40, cache_read_tokens: 0, cache_write_5m_tokens: 0, cache_write_1h_tokens: 0, linked_cost_usd: 5.84 },
    ],
    linked_cost_usd: 12.34,
  };

  it("summary view labels every aggregate metric with its distinguishable value", async () => {
    fetch.mockReturnValue(response(richSummary));
    render(<App apiBase="" />);
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/summary"));
    expect(screen.getByText(/handoff runs\D*2/i)).toBeVisible();
    expect(screen.getByText(/compliant runs\D*3/i)).toBeVisible();
    expect(screen.getByText(/verifier rounds\D*5/i)).toBeVisible();
    expect(screen.getByText(/verifier retries\D*4/i)).toBeVisible();
    expect(screen.getByText(/seeds run\D*9/i)).toBeVisible();
    expect(screen.getByText(/seeds detected\D*1/i)).toBeVisible();
    expect(screen.getByText(/cost.*12\.34/i)).toBeVisible();
  });

  it("summary view renders unknown cost when linked_cost_usd is null", async () => {
    fetch.mockReturnValue(response({ ...richSummary, linked_cost_usd: null }));
    render(<App apiBase="" />);
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/summary"));
    expect(screen.getByText(/cost.*unknown cost/i)).toBeVisible();
  });

  // Description-term/detail (dt/dd) pairs render the label and value as separate
  // sibling nodes, so each label's value is asserted on the label's next sibling
  // rather than matched together as one string.
  function expectLabelledValue(labelPattern, value) {
    const label = screen.getByText(labelPattern, { selector: "dt" });
    expect(label.nextElementSibling).toHaveTextContent(value);
  }

  it("detail view labels spec_version, every compliance reason, run counters, and run cost", async () => {
    fetch.mockReturnValueOnce(response(richSummary)).mockReturnValueOnce(response(richDetail));
    render(<App apiBase="" />);
    const link = await screen.findByRole("link", { name: /run-detail/ });
    fireEvent.click(link);
    await waitFor(() => expect(fetch).toHaveBeenLastCalledWith("/api/runs/run-detail"));
    await screen.findByText(/spec version/i, { selector: "dt" });
    expectLabelledValue(/spec version/i, "7");
    expect(screen.getByText("expected_one_start")).toBeVisible();
    expect(screen.getByText("identity_mismatch")).toBeVisible();
    expectLabelledValue(/verifier rounds/i, "5");
    expectLabelledValue(/verifier retries/i, "4");
    expectLabelledValue(/seeds run/i, "9");
    expectLabelledValue(/seeds detected/i, "1");
    expectLabelledValue(/cost/i, "12.34");
    const claudeEntry = screen.getByText(/model-claude/i);
    expect(claudeEntry).toHaveTextContent(/claude/i);
    expect(claudeEntry).toHaveTextContent("6.5");
    const codexEntry = screen.getByText(/model-codex/i);
    expect(codexEntry).toHaveTextContent(/codex/i);
    expect(codexEntry).toHaveTextContent("5.84");
  });

  it("detail view renders unknown cost for a null run linked_cost_usd", async () => {
    const nullCostDetail = { ...richDetail, linked_cost_usd: null };
    fetch.mockReturnValueOnce(response(richSummary)).mockReturnValueOnce(response(nullCostDetail));
    render(<App apiBase="" />);
    const link = await screen.findByRole("link", { name: /run-detail/ });
    fireEvent.click(link);
    await waitFor(() => expect(fetch).toHaveBeenLastCalledWith("/api/runs/run-detail"));
    await screen.findByText(/cost/i, { selector: "dt" });
    expectLabelledValue(/cost/i, "unknown cost");
  });
});
