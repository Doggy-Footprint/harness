import React from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { HINTS } from "./hints";

// Independent oracle for agent-docs/specs/4ac23629e9b7a145-isolation-telemetry.md (v1), O9.
// Item ids U1..U5 follow the Verification Obligations table.

const RULES = ["test_reads_implementation", "test_runs_tests", "impl_reads_tests",
  "impl_runs_test_command", "dispatch_run_instruction"];
const COUNTS = { test_reads_implementation: 3, test_runs_tests: 5, impl_reads_tests: 7,
  impl_runs_test_command: 11, dispatch_run_instruction: 13 };
const TOTAL = 39;
const HEADERS = ["Time", "Run", "Agent", "Rule", "Match", "Excerpt"];

const rowOne = { ts: "2026-09-22T01:02:03+00:00", workflow_run_id: "run-hh", session_id: "sess-1",
  agent_type: "test-implementer", rule: "test_reads_implementation", tool_name: "Read",
  match: "pkg/directives.go", match_kind: "path", excerpt: "EXCERPT_ONE pkg/directives.go" };
const rowTwo = { ts: "2026-09-22T00:00:01+00:00", workflow_run_id: "run-hh", session_id: "sess-2",
  agent_type: null, rule: "dispatch_run_instruction", tool_name: "Agent",
  match: "Run npm test", match_kind: "runner", excerpt: "EXCERPT_TWO run npm test" };
const populated = { total: TOTAL, by_rule: COUNTS,
  by_agent_type: { "test-implementer": 26, main: 13 }, candidates: [rowOne, rowTwo] };
const empty = { total: 0, by_rule: Object.fromEntries(RULES.map((rule) => [rule, 0])),
  by_agent_type: {}, candidates: [] };

const runItem = { run_id: "run-hh", spec: "analytics", status: "complete", compliant: true,
  isolation_candidates: 2 };
const baseSummary = { runs: 1, completed_runs: 1, compliant_runs: 1, handoff_runs: 0,
  verifier_rounds: 1, verifier_retries: 0, seeds_run: 0, seeds_detected: 0, linked_cost_usd: 1.25,
  run_items: [runItem], workflow: { runs: [runItem] } };
const baseDetail = { run_id: "run-hh", spec: "analytics", spec_version: 1, status: "complete",
  compliant: true, compliance_reasons: [],
  events: [{ event: "workflow_start" }, { event: "workflow_end", status: "complete" }],
  verifier_rounds: 1, verifier_retries: 0, seeds_run: 0, seeds_detected: 0,
  transcript_metadata: [], linked_cost_usd: 1.25 };

function response(body, ok = true) {
  return Promise.resolve({ ok, status: ok ? 200 : 500, json: () => Promise.resolve(body) });
}

async function renderSummary(summary) {
  fetch.mockReturnValue(response(summary));
  render(<App apiBase="" />);
  await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/summary"));
}

async function renderDetail(summary, detail) {
  fetch.mockReturnValueOnce(response(summary)).mockReturnValueOnce(response(detail));
  render(<App apiBase="" />);
  fireEvent.click(await screen.findByRole("link", { name: /run-hh/ }));
  await waitFor(() => expect(fetch).toHaveBeenLastCalledWith("/api/runs/run-hh"));
}

const findSection = () => screen.findByRole("region", { name: "Harness hacking" });

// v3 DOM shape (F15): the label element's immediately following sibling element
// carries exactly one number, equal to the expected count. No ancestor fallback.
function siblingNumbers(label) {
  const sibling = label.nextElementSibling;
  expect(sibling, `no following sibling element for label "${label.textContent}"`).not.toBeNull();
  return sibling.textContent.match(/\d+/g) || [];
}

function labelFor(section, text) {
  const candidates = within(section).getAllByText(text).filter((node) => !node.closest("table"));
  expect(candidates.length).toBeGreaterThan(0);
  return candidates[0];
}

function expectCounts(section, total, counts) {
  expect(siblingNumbers(labelFor(section, "Total")), "Total").toEqual([String(total)]);
  for (const rule of RULES) {
    expect(siblingNumbers(labelFor(section, rule)), rule).toEqual([String(counts[rule])]);
  }
}

function expectTableRows(section) {
  const headers = within(section).getAllByRole("columnheader").map((node) => node.textContent.trim());
  expect(headers).toEqual(HEADERS);
  const rowFor = (needle) => within(section).getAllByRole("row")
    .find((row) => row.textContent.includes(needle));
  const first = within(rowFor("EXCERPT_ONE")).getAllByRole("cell");
  expect(first).toHaveLength(6);
  expect(first[0].textContent.trim()).not.toBe("");
  expect(first[1]).toHaveTextContent("run-hh");
  expect(first[2]).toHaveTextContent("test-implementer");
  expect(first[3]).toHaveTextContent("test_reads_implementation");
  expect(first[4]).toHaveTextContent("pkg/directives.go");
  expect(first[5]).toHaveTextContent("EXCERPT_ONE pkg/directives.go");
  const second = within(rowFor("EXCERPT_TWO")).getAllByRole("cell");
  expect(second).toHaveLength(6);
  expect(second[1]).toHaveTextContent("run-hh");
  expect(second[2]).toHaveTextContent(/^main$/);
  expect(second[3]).toHaveTextContent("dispatch_run_instruction");
  expect(second[4]).toHaveTextContent("Run npm test");
  expect(second[5]).toHaveTextContent("EXCERPT_TWO run npm test");
}

// Hovering a parent does not fire a descendant's mouseenter, so every node of
// the labelled element is tried.
function tooltipTextFor(element) {
  for (const node of [element, ...element.querySelectorAll("*")]) {
    fireEvent.mouseEnter(node);
    const tip = screen.queryByRole("tooltip");
    if (tip) {
      const text = tip.textContent;
      fireEvent.mouseLeave(node);
      return text;
    }
    fireEvent.mouseLeave(node);
  }
  return null;
}

describe("spec isolation-telemetry O9 harness hacking dashboard", () => {
  beforeEach(() => { cleanup(); window.history.replaceState({}, "", "/"); global.fetch = vi.fn(); });
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  it("U1 summary card shows the total, one count per rule id and the table row cells", async () => {
    await renderSummary({ ...baseSummary, harness_hacking: populated });
    const section = await findSection();
    expectCounts(section, TOTAL, COUNTS);
    expectTableRows(section);
  });

  it("U2 empty state text is shown with zero counts when there are no candidates", async () => {
    await renderSummary({ ...baseSummary, harness_hacking: empty });
    const section = await findSection();
    expect(within(section).getByText("No isolation candidates recorded.")).toBeVisible();
    expectCounts(section, 0, Object.fromEntries(RULES.map((rule) => [rule, 0])));
    expect(within(section).queryByText(/EXCERPT_/)).not.toBeInTheDocument();
  });

  it("U2 populated card does not show the empty state text", async () => {
    await renderSummary({ ...baseSummary, harness_hacking: populated });
    const section = await findSection();
    expect(within(section).queryByText("No isolation candidates recorded.")).not.toBeInTheDocument();
  });

  it("U3 a response without harness_hacking renders no section and leaves other content intact", async () => {
    await renderSummary(baseSummary);
    expect(await screen.findByRole("link", { name: /run-hh/ })).toBeVisible();
    expect(screen.getByText("1", { selector: "[data-metric='runs']" })).toBeVisible();
    expect(screen.queryByRole("region", { name: "Harness hacking" })).not.toBeInTheDocument();
    expect(screen.queryByText(/harness hacking/i)).not.toBeInTheDocument();
    expect(screen.queryByText("No isolation candidates recorded.")).not.toBeInTheDocument();
  });

  it("U4 run detail renders its own Harness hacking card", async () => {
    await renderDetail(baseSummary, { ...baseDetail, harness_hacking: populated });
    const section = await findSection();
    expectCounts(section, TOTAL, COUNTS);
    expectTableRows(section);
  });

  it("U4 run detail without harness_hacking renders no section", async () => {
    await renderDetail({ ...baseSummary, harness_hacking: populated }, baseDetail);
    await screen.findByText(/spec version/i, { selector: "dt" });
    expect(screen.queryByRole("region", { name: "Harness hacking" })).not.toBeInTheDocument();
  });

  it("U4 run detail with zero candidates shows the empty state", async () => {
    await renderDetail(baseSummary, { ...baseDetail, harness_hacking: empty });
    const section = await findSection();
    expect(within(section).getByText("No isolation candidates recorded.")).toBeVisible();
  });

  it("U5 HINTS is exported and the card title and each rule id have an English and a differing Korean hint", async () => {
    expect(HINTS).toBeTruthy();
    await renderSummary({ ...baseSummary, harness_hacking: empty });
    let section = await findSection();
    const english = {};
    english.title = tooltipTextFor(within(section).getAllByRole("heading")[0]);
    for (const rule of RULES) english[rule] = tooltipTextFor(labelFor(section, rule));
    for (const [key, text] of Object.entries(english)) {
      expect(text, `EN hint for ${key}`).toBeTruthy();
    }

    fireEvent.click(screen.getByRole("button", { name: "KO" }));
    section = await findSection();
    const korean = {};
    korean.title = tooltipTextFor(within(section).getAllByRole("heading")[0]);
    for (const rule of RULES) korean[rule] = tooltipTextFor(labelFor(section, rule));
    for (const key of Object.keys(english)) {
      expect(korean[key], `KO hint for ${key}`).toBeTruthy();
      expect(korean[key], `KO differs from EN for ${key}`).not.toBe(english[key]);
      expect(korean[key], `KO hint for ${key} is Korean text`).toMatch(/[가-힣]/);
    }
  });
});
