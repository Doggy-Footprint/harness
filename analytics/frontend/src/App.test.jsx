import React from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

describe("spec v4 (compliance-classification) VO5/F7 run and session class lines", () => {
  beforeEach(() => { cleanup(); window.history.replaceState({}, "", "/"); global.fetch = vi.fn(); });
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  const classifiedSummary = {
    ...emptySummary,
    runs: 7, completed_runs: 6, compliant_runs: 3, handoff_runs: 1,
    run_items: [{ run_id: "run-1", spec: "analytics", status: "complete", compliant: true }],
    classification: {
      runs: { compliant: 3, noncompliant: 2, excluded: 2 },
      sessions: { compliant: 5, noncompliant: 1, partial: 2, unrelated: 4, excluded: 3 },
    },
  };

  it("renders the run-class line with one span per class and the fixture counts", async () => {
    fetch.mockReturnValue(response(classifiedSummary));
    render(<App apiBase="" />);
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/summary"));

    for (const [cls, value] of Object.entries(classifiedSummary.classification.runs)) {
      expect(screen.getByText(String(value), { selector: `[data-metric='class-runs-${cls}']` })).toBeVisible();
    }
  });

  it("renders the session-class line with one span per class and the fixture counts", async () => {
    fetch.mockReturnValue(response(classifiedSummary));
    render(<App apiBase="" />);
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/summary"));

    for (const [cls, value] of Object.entries(classifiedSummary.classification.sessions)) {
      expect(screen.getByText(String(value), { selector: `[data-metric='class-sessions-${cls}']` })).toBeVisible();
    }
  });
});

describe("spec v4 FR13/C13 workflow and other-sessions tabs", () => {
  beforeEach(() => { cleanup(); window.history.replaceState({}, "", "/"); global.fetch = vi.fn(); });
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  // v4 Signatures fixes non_workflow's and workflow's shape exactly
  // (F5 correction): non_workflow.{sessions:int, tools:{name:count},
  // subagents:{type:count}, cost:{by_model:{model:usd|null},
  // tokens_by_model, total_usd, unknown_models}}; workflow.runs is a list of
  // FR12 run summaries.
  const tabbedSummary = {
    runs: 2, completed_runs: 2, compliant_runs: 2, handoff_runs: 0,
    verifier_rounds: 2, verifier_retries: 0, seeds_run: 0, seeds_detected: 0,
    linked_cost_usd: 3.5,
    run_items: [{ run_id: "run-tab", spec: "analytics", status: "complete", compliant: true }],
    workflow: { runs: [{ run_id: "run-tab", spec: "analytics", status: "complete", compliant: true }] },
    non_workflow: {
      sessions: 4,
      tools: { Bash: 12, Read: 7, Write: 3 },
      cost: {
        by_model: { "known-model": 9.5, "mystery-model": null },
        tokens_by_model: { "known-model": { input_tokens: 100, output_tokens: 50, cache_read_tokens: 0, cache_write_tokens: 0 } },
        total_usd: 9.5,
        unknown_models: ["mystery-model"],
      },
      subagents: { reviewer: 5, "general-purpose": 2 },
    },
  };

  function renderWithTabbedSummary() {
    fetch.mockReturnValue(response(tabbedSummary));
    render(<App apiBase="" />);
    return waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/summary"));
  }

  it("shows the Workflow tab's run summary by default", async () => {
    await renderWithTabbedSummary();
    expect(screen.getByRole("link", { name: /run-tab/ })).toBeVisible();
    expect(screen.queryByText("Bash")).not.toBeInTheDocument();
  });

  function findOtherSessionsTab() {
    return screen.getByText(/Other sessions/i);
  }

  // "9.5" (per-model cost and the cost total) and "mystery-model" (its
  // model-cost row and the separate unknown-models note) each legitimately
  // render in more than one place. Rather than weaken the check to "appears
  // somewhere on the page", each assertion below is scoped to the single
  // table row (accessible role "row", i.e. a <tr>) that also carries the
  // row's other distinguishing cell, so it verifies the value against the
  // specific record it belongs to.
  function findRowContaining(...matchers) {
    const rows = screen.getAllByRole("row");
    const match = rows.find((row) => matchers.every((matcher) => within(row).queryAllByText(matcher).length > 0));
    if (!match) throw new Error(`no table row found containing: ${matchers.join(", ")}`);
    return match;
  }

  it("switching to the Other sessions tab renders the tool, model-cost, and subagent tables", async () => {
    await renderWithTabbedSummary();
    fireEvent.click(findOtherSessionsTab());
    await screen.findByText("Bash");

    const bashRow = findRowContaining("Bash", "12");
    expect(within(bashRow).getByText("Bash")).toBeVisible();
    expect(screen.getByText("Read")).toBeVisible();
    expect(screen.getByText("Write")).toBeVisible();

    const modelCostRow = findRowContaining("known-model", /9\.5/);
    expect(within(modelCostRow).getByText(/9\.5/)).toBeVisible();
    // The same 9.5 value also appears once more as the cost total.
    expect(screen.getAllByText(/9\.5/)).toHaveLength(2);

    const subagentRow = findRowContaining("reviewer", "5");
    expect(within(subagentRow).getByText("5")).toBeVisible();
    expect(screen.getByText("general-purpose")).toBeVisible();
  });

  it("switching back to the Workflow tab restores the run summary", async () => {
    await renderWithTabbedSummary();
    fireEvent.click(findOtherSessionsTab());
    await screen.findByText("Bash");
    fireEvent.click(screen.getByText(/^Workflow$/i));
    expect(await screen.findByRole("link", { name: /run-tab/ })).toBeVisible();
    expect(screen.queryByText("Bash")).not.toBeInTheDocument();
  });

  it("Other sessions tab shows an unknown-model indicator for unpriced models", async () => {
    await renderWithTabbedSummary();
    fireEvent.click(findOtherSessionsTab());
    await screen.findByText("Bash");
    // mystery-model's own model-cost row must show an unknown-cost indicator.
    const mysteryRow = findRowContaining("mystery-model", /unknown/i);
    expect(within(mysteryRow).getByText("mystery-model")).toBeVisible();
    expect(within(mysteryRow).getByText(/unknown/i)).toBeVisible();
    // It is also named a second time, in the separate unknown-models note.
    expect(screen.getAllByText(/mystery-model/i)).toHaveLength(2);
  });
});
