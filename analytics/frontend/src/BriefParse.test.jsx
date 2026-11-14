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
const noAmends = { intent_mismatch: 0, brief_change: 0, contract_change: 0, correction: 0, unspecified: 0 };

const STAMP = "2026-11-14T01:02:03+00:00";
const entry = (overrides) => ({ stage: "understanding", round: 11, fact_questions: 31, user_decisions: 32,
  split: null, picks_differ: null, ts: STAMP, session_id: "sess-brief-aaa", tool_use_id: "toolu_AAA111",
  parsed: null, ...overrides });

const UNDERSTANDING = "First point\nSecond point\n\nThird point";
const fullParsed = { text: "ORIGINAL-LINE-ONE\nORIGINAL-LINE-TWO", understanding: UNDERSTANDING,
  questions: [{ kind: "fact", text: "Which store do you use?" },
    { kind: "decision", text: "Pick the retry policy?" }] };

function response(body, ok = true) {
  return Promise.resolve({ ok, status: ok ? 200 : 500, json: () => Promise.resolve(body) });
}

async function openDetail(briefs, runId = "run-full") {
  fetch.mockReturnValueOnce(response(baseSummary))
    .mockReturnValueOnce(response({ ...baseDetail, briefs, amend_reasons: noAmends }));
  const view = render(<App apiBase="" />);
  fireEvent.click(await screen.findByRole("link", { name: new RegExp(runId) }));
  await waitFor(() => expect(fetch).toHaveBeenLastCalledWith(`/api/runs/${runId}`));
  return view;
}

function smallestContaining(element, needles) {
  for (let node = element; node && node !== document.body; node = node.parentElement) {
    const text = node.textContent.toLowerCase();
    if (needles.every((needle) => text.includes(needle.toLowerCase()))) return node;
  }
  throw new Error(`no ancestor of "${element.textContent}" contains ${needles.join(", ")}`);
}

function preWrapElementHolding(root, exactText) {
  const holders = [...root.querySelectorAll("*")].filter((node) => node.textContent === exactText);
  expect(holders.length, `element whose text content is ${JSON.stringify(exactText)}`).toBeGreaterThan(0);
  return holders.filter((node) => getComputedStyle(node).whiteSpace === "pre-wrap");
}

describe("run detail Brief card with parsed briefs", () => {
  beforeEach(() => { cleanup(); window.history.replaceState({}, "", "/"); global.fetch = vi.fn(); });
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  it("S1 shows each question with its kind label and the understanding with line breaks", async () => {
    const { container } = await openDetail([entry({ parsed: fullParsed })]);

    const factRow = smallestContaining(await screen.findByText("Which store do you use?"),
      ["fact", "Which store do you use?"]);
    expect(factRow.textContent.toLowerCase()).not.toContain("decision");
    expect(factRow.textContent).not.toContain("Pick the retry policy?");
    const decisionRow = smallestContaining(await screen.findByText("Pick the retry policy?"),
      ["decision", "Pick the retry policy?"]);
    expect(decisionRow.textContent.toLowerCase()).not.toContain("fact");
    expect(decisionRow.textContent).not.toContain("Which store do you use?");

    expect(preWrapElementHolding(container, UNDERSTANDING).length).toBeGreaterThan(0);
    expect(screen.queryByText("No questions found.")).not.toBeInTheDocument();
    expect(screen.queryByText("No understanding section.")).not.toBeInTheDocument();
    expect(screen.queryByText("Brief text not found.")).not.toBeInTheDocument();
  });

  it("S2 shows both empty messages for no questions and a null understanding", async () => {
    await openDetail([entry({ parsed: { text: "plain text only", understanding: null, questions: [] } })]);
    expect(await screen.findByText("No questions found.")).toBeVisible();
    expect(screen.getByText("No understanding section.")).toBeVisible();
    expect(screen.queryByText("Brief text not found.")).not.toBeInTheDocument();
  });

  it("S3 shows the not-found message for a null parsed value and nothing parsed", async () => {
    await openDetail([entry({ parsed: null })]);
    expect(await screen.findByText("Brief text not found.")).toBeVisible();
    expect(screen.queryByText("No questions found.")).not.toBeInTheDocument();
    expect(screen.queryByText("No understanding section.")).not.toBeInTheDocument();
    expect(screen.queryByText("Original text")).not.toBeInTheDocument();
  });

  it("S2 S3 messages are decided per brief entry", async () => {
    await openDetail([
      entry({ tool_use_id: "toolu_AAA111", parsed: fullParsed }),
      entry({ tool_use_id: "toolu_BBB222", parsed: null }),
      entry({ tool_use_id: "toolu_CCC333", parsed: { text: "t", understanding: null, questions: [] } }),
    ]);
    expect(await screen.findAllByText("Brief text not found.")).toHaveLength(1);
    expect(screen.getAllByText("No questions found.")).toHaveLength(1);
    expect(screen.getAllByText("No understanding section.")).toHaveLength(1);
    expect(screen.getAllByText("Original text")).toHaveLength(2);
  });

  it("S4 keeps the original text collapsed until the disclosure is opened", async () => {
    const { container } = await openDetail([entry({ parsed: fullParsed })]);
    const label = await screen.findByText("Original text");
    const details = label.closest("details");
    expect(details).not.toBeNull();
    expect(details).not.toHaveAttribute("open");

    const original = screen.getByText(/ORIGINAL-LINE-ONE/);
    expect(original).not.toBeVisible();

    fireEvent.click(label);
    expect(details).toHaveAttribute("open");
    expect(screen.getByText(/ORIGINAL-LINE-ONE/)).toBeVisible();
    expect(preWrapElementHolding(container, fullParsed.text).length).toBeGreaterThan(0);
  });

  it("S6 still shows the existing Brief card fields next to the parsed content", async () => {
    await openDetail([entry({ stage: "approval", round: 12, fact_questions: 33, user_decisions: 34,
      split: "accepted", picks_differ: 35, session_id: "sess-brief-bbb", tool_use_id: "toolu_BBB222",
      parsed: fullParsed })]);
    const row = smallestContaining(await screen.findByText(/toolu_BBB222/), [
      "approval", "12", "33", "34", "accepted", "35", "sess-brief-bbb", "toolu_BBB222"]);
    expect(row.textContent).toContain("2026");
    expect(screen.queryByText("No brief events.")).not.toBeInTheDocument();
  });
});

describe("transcript text is rendered as text", () => {
  beforeEach(() => { cleanup(); window.history.replaceState({}, "", "/"); global.fetch = vi.fn(); });
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  const hostile = {
    text: "<b>x</b> original <script>alert(1)</script>",
    understanding: "<img src=x onerror=alert(1)> understood",
    questions: [{ kind: "fact", text: "<script>alert('q')</script> Q?" },
      { kind: "decision", text: "<b>bold</b> D?" }],
  };
  const benign = { text: "original", understanding: "understood",
    questions: [{ kind: "fact", text: "Q?" }, { kind: "decision", text: "D?" }] };

  async function injectedElements(parsed, waitFor_) {
    const { container } = await openDetail([entry({ parsed })]);
    await screen.findByText(waitFor_);
    const count = container.querySelectorAll("script, img, b").length;
    const handlers = container.querySelectorAll("[onerror]").length;
    const text = container.textContent;
    cleanup();
    fetch.mockReset();
    window.history.replaceState({}, "", "/");
    return { count, handlers, text };
  }

  it("S5 shows script, img, and b markup literally and creates no such elements", async () => {
    const baseline = await injectedElements(benign, "Q?");
    const result = await injectedElements(hostile, "<script>alert('q')</script> Q?");

    expect(result.count).toBe(baseline.count);
    expect(result.handlers).toBe(0);
    expect(result.text).toContain("<script>alert('q')</script> Q?");
    expect(result.text).toContain("<b>bold</b> D?");
    expect(result.text).toContain("<img src=x onerror=alert(1)> understood");
    expect(result.text).toContain("<b>x</b> original <script>alert(1)</script>");
  });
});

describe("summary Brief questions card", () => {
  beforeEach(() => { cleanup(); window.history.replaceState({}, "", "/"); global.fetch = vi.fn(); });
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  const questions = [
    { run_id: "run-bq-1", stage: "decision", round: 2, ts: STAMP, kind: "decision", text: "Zeta first?" },
    { run_id: "run-bq-2", stage: "understanding", round: 1, ts: STAMP, kind: "fact", text: "Alpha second?" },
    { run_id: "run-bq-3", stage: "approval", round: 3, ts: null, kind: "fact", text: "Mid third?" },
  ];
  const summary = { ...baseSummary, run_items: [], brief_only_runs: [], brief_questions: questions };

  it("S7 lists each question with run id, stage, kind, and text in API order", async () => {
    fetch.mockReturnValue(response(summary));
    render(<App apiBase="" />);
    expect((await screen.findAllByText("Brief questions"))[0]).toBeVisible();

    const rows = [];
    for (const item of questions) {
      const link = await screen.findByRole("link", { name: new RegExp(item.run_id) });
      const row = smallestContaining(link, [item.run_id, item.stage, item.kind, item.text]);
      for (const other of questions.filter((candidate) => candidate !== item)) {
        expect(row.textContent).not.toContain(other.text);
      }
      rows.push(screen.getByText(item.text));
    }
    const follows = (a, b) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
    expect(follows(rows[0], rows[1])).toBe(true);
    expect(follows(rows[1], rows[2])).toBe(true);
    expect(screen.queryByText("No brief questions.")).not.toBeInTheDocument();
  });

  it("S8 clicking a run id requests that run's detail", async () => {
    fetch.mockReturnValueOnce(response(summary)).mockReturnValueOnce(response({
      ...baseDetail, run_id: "run-bq-2", status: "before_approval", compliant: null,
      briefs: [], amend_reasons: noAmends }));
    render(<App apiBase="" />);
    fireEvent.click(await screen.findByRole("link", { name: /run-bq-2/ }));
    await waitFor(() => expect(fetch).toHaveBeenLastCalledWith("/api/runs/run-bq-2"));
  });

  it("S9 shows the empty message when there are no brief questions", async () => {
    fetch.mockReturnValue(response({ ...summary, brief_questions: [] }));
    render(<App apiBase="" />);
    expect((await screen.findAllByText("Brief questions"))[0]).toBeVisible();
    expect(screen.getByText("No brief questions.")).toBeVisible();
  });
});

describe("hint texts for the brief parse views", () => {
  it("S10 every hint key has non-empty en and ko text", () => {
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
