import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { HINTS } from "./hints";

const baseSummary = { runs: 1, completed_runs: 1, compliant_runs: 1, handoff_runs: 0,
  verifier_rounds: 1, verifier_retries: 0, seeds_run: 0, seeds_detected: 0, linked_cost_usd: 1.25,
  run_items: [{ run_id: "run-full", spec: "analytics", status: "complete", compliant: true }] };
const baseDetail = { run_id: "run-full", spec: "analytics", spec_version: 1, status: "complete",
  compliant: true, compliance_reasons: [],
  events: [{ event: "workflow_start" }, { event: "workflow_end", status: "complete" }],
  verifier_rounds: 1, verifier_retries: 0, seeds_run: 0, seeds_detected: 0,
  transcript_metadata: [], linked_cost_usd: 1.25 };

const FIRST_TS = "2026-11-14T01:02:03+00:00";
const SECOND_TS = "2026-11-14T05:06:07+00:00";
const briefOne = { stage: "understanding", round: 11, fact_questions: 31, user_decisions: 32,
  split: null, picks_differ: null, ts: FIRST_TS, session_id: "sess-brief-aaa", tool_use_id: "toolu_AAA111" };
const briefTwo = { stage: "approval", round: 12, fact_questions: 33, user_decisions: 34,
  split: "accepted", picks_differ: 35, ts: SECOND_TS, session_id: "sess-brief-bbb", tool_use_id: "toolu_BBB222" };
const noAmends = { intent_mismatch: 0, brief_change: 0, contract_change: 0, correction: 0, unspecified: 0 };
const AMENDS = { intent_mismatch: 21, brief_change: 22, contract_change: 23, correction: 24, unspecified: 25 };
const AMEND_LABELS = { intent_mismatch: /intent[_ ]mismatch/i, brief_change: /brief[_ ]change/i,
  contract_change: /contract[_ ]change/i, correction: /correction/i, unspecified: /unspecified/i };

function response(body, ok = true) {
  return Promise.resolve({ ok, status: ok ? 200 : 500, json: () => Promise.resolve(body) });
}

async function openDetail(detail, summary = baseSummary, runId = "run-full") {
  fetch.mockReturnValueOnce(response(summary)).mockReturnValueOnce(response(detail));
  render(<App apiBase="" />);
  fireEvent.click(await screen.findByRole("link", { name: new RegExp(runId) }));
  await waitFor(() => expect(fetch).toHaveBeenLastCalledWith(`/api/runs/${runId}`));
}

function smallestContaining(element, needles) {
  for (let node = element; node && node !== document.body; node = node.parentElement) {
    if (needles.every((needle) => node.textContent.includes(needle))) return node;
  }
  throw new Error(`no ancestor of "${element.textContent}" contains ${needles.join(", ")}`);
}

function timeShown(text, stamp) {
  const date = new Date(stamp);
  const candidates = [stamp, stamp.replace("T", " ").slice(0, 19), stamp.slice(0, 10), stamp.slice(11, 19),
    date.toISOString(), date.toLocaleString(), date.toLocaleTimeString(), date.toLocaleDateString(),
    date.toUTCString(), date.toString()];
  return candidates.some((candidate) => text.includes(candidate));
}

function countBesideLabel(labelPattern, own) {
  const others = Object.values(AMENDS).filter((value) => value !== own);
  const token = (value) => new RegExp(`(^|\\D)${value}(\\D|$)`);
  const labels = screen.queryAllByText(labelPattern);
  expect(labels.length, `label ${labelPattern}`).toBeGreaterThan(0);
  return labels.some((label) => {
    let node = label;
    for (let depth = 0; depth < 3 && node && node !== document.body; depth += 1, node = node.parentElement) {
      const text = node.textContent;
      if (token(own).test(text) && !others.some((value) => token(value).test(text))) return true;
    }
    return false;
  });
}

describe("run detail Brief card", () => {
  beforeEach(() => { cleanup(); window.history.replaceState({}, "", "/"); global.fetch = vi.fn(); });
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  it("S1 lists each brief entry with its fields and an empty cell for null", async () => {
    await openDetail({ ...baseDetail, briefs: [briefOne, briefTwo], amend_reasons: noAmends });
    expect((await screen.findAllByText("Brief")).length).toBeGreaterThan(0);

    const rowOne = smallestContaining(await screen.findByText(/toolu_AAA111/), [
      "understanding", "11", "31", "32", "sess-brief-aaa", "toolu_AAA111"]);
    expect(rowOne.textContent).not.toContain("toolu_BBB222");
    expect(rowOne.textContent).not.toMatch(/null|undefined|NaN/);
    expect(timeShown(rowOne.textContent, FIRST_TS)).toBe(true);

    const rowTwo = smallestContaining(await screen.findByText(/toolu_BBB222/), [
      "approval", "12", "33", "34", "accepted", "35", "sess-brief-bbb", "toolu_BBB222"]);
    expect(rowTwo.textContent).not.toContain("toolu_AAA111");
    expect(timeShown(rowTwo.textContent, SECOND_TS)).toBe(true);
  });

  it("S2 shows the empty message when there are no brief events", async () => {
    await openDetail({ ...baseDetail, briefs: [], amend_reasons: noAmends });
    expect(await screen.findByText("No brief events.")).toBeVisible();
    expect(screen.queryByText(/toolu_/)).not.toBeInTheDocument();
  });

  it("S3 shows the before_approval badge and no compliance badge for a brief-only run", async () => {
    const summary = { ...baseSummary, run_items: [], runs: 0, completed_runs: 0, compliant_runs: 0,
      brief_only_runs: [{ run_id: "run-bo", rounds: 1, last_stage: "understanding", last_ts: FIRST_TS }] };
    const detail = { ...baseDetail, run_id: "run-bo", spec: null, spec_version: null,
      status: "before_approval", compliant: null, events: [], briefs: [briefOne],
      amend_reasons: noAmends, linked_cost_usd: null };
    await openDetail(detail, summary, "run-bo");
    expect((await screen.findAllByText("before_approval")).length).toBeGreaterThan(0);
    expect(screen.queryAllByText(/compliant/i)).toHaveLength(0);
  });

  it("S3 control: a complete compliant run still shows a compliance badge", async () => {
    await openDetail({ ...baseDetail, briefs: [], amend_reasons: noAmends });
    await screen.findByText("No brief events.");
    expect(screen.queryAllByText(/compliant/i).length).toBeGreaterThan(0);
  });

  it("S4 shows the five amend reason counts next to their labels", async () => {
    await openDetail({ ...baseDetail, briefs: [], amend_reasons: AMENDS });
    await screen.findByText("No brief events.");
    for (const [reason, label] of Object.entries(AMEND_LABELS)) {
      expect(countBesideLabel(label, AMENDS[reason]), `${reason} count`).toBe(true);
    }
  });
});

describe("summary Briefs before approval card", () => {
  beforeEach(() => { cleanup(); window.history.replaceState({}, "", "/"); global.fetch = vi.fn(); });
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  it("S5 lists brief-only runs and opens the run detail from the run id", async () => {
    const summary = { ...baseSummary, run_items: [],
      brief_only_runs: [{ run_id: "run-bo-7", rounds: 17, last_stage: "approval", last_ts: SECOND_TS }] };
    fetch.mockReturnValueOnce(response(summary)).mockReturnValueOnce(response({
      ...baseDetail, run_id: "run-bo-7", status: "before_approval", compliant: null,
      briefs: [], amend_reasons: noAmends }));
    render(<App apiBase="" />);

    expect(await screen.findByText("Briefs before approval")).toBeVisible();
    const link = await screen.findByRole("link", { name: /run-bo-7/ });
    const row = smallestContaining(link, ["run-bo-7", "17", "approval"]);
    expect(row.textContent).toContain("run-bo-7");
    expect(screen.queryByText("No briefs before approval.")).not.toBeInTheDocument();

    fireEvent.click(link);
    await waitFor(() => expect(fetch).toHaveBeenLastCalledWith("/api/runs/run-bo-7"));
  });

  it("S6 shows the empty message when there are no brief-only runs", async () => {
    fetch.mockReturnValue(response({ ...baseSummary, brief_only_runs: [] }));
    render(<App apiBase="" />);
    expect(await screen.findByText("Briefs before approval")).toBeVisible();
    expect(screen.getByText("No briefs before approval.")).toBeVisible();
  });
});

describe("hint texts", () => {
  it("S7 every hint key has non-empty en and ko text", () => {
    const entries = Object.entries(HINTS);
    expect(entries.length).toBeGreaterThan(0);
    for (const [key, value] of entries) {
      expect(typeof value?.en, `en type for ${key}`).toBe("string");
      expect(value.en.trim(), `en text for ${key}`).not.toBe("");
      expect(typeof value?.ko, `ko type for ${key}`).toBe("string");
      expect(value.ko.trim(), `ko text for ${key}`).not.toBe("");
    }
  });
});
