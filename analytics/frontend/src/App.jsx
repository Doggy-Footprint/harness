import { createContext, useContext, useEffect, useRef, useState } from "react";
import { HINTS, detectLang } from "./hints";

const LangContext = createContext("en");

// The bubble is position: fixed from the anchor's viewport rect because table
// wrappers scroll horizontally (overflow-x: auto) and would clip an absolutely
// positioned child.
function Tip({ as: Tag = "span", hint, className = "", children, ...rest }) {
  const lang = useContext(LangContext);
  const ref = useRef(null);
  const [pos, setPos] = useState(null);
  const text = HINTS[hint]?.[lang];
  if (!text) return <Tag className={className} {...rest}>{children}</Tag>;
  const show = () => {
    const r = ref.current.getBoundingClientRect();
    const left = Math.min(Math.max(8, r.left), window.innerWidth - 288);
    const below = r.bottom + 8;
    setPos(below + 120 > window.innerHeight ? { left, bottom: window.innerHeight - r.top + 8 } : { left, top: below });
  };
  const hide = () => setPos(null);
  return (
    <Tag ref={ref} className={`${className} has-tip`} tabIndex={0} onMouseEnter={show} onMouseLeave={hide} onFocus={show} onBlur={hide} {...rest}>
      {children}
      {pos && <span role="tooltip" className="tip" style={pos}>{text}</span>}
    </Tag>
  );
}

export function ratio(numerator, denominator) {
  if (!denominator || numerator == null) return null;
  return numerator / denominator;
}

function formatPercent(value) {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}

function formatNumber(value) {
  return value == null ? "—" : Number(value).toLocaleString("en-US");
}

function formatUsd(value) {
  return value == null ? "unknown cost" : `$${Number(value).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatCell(value) {
  return typeof value === "number" ? formatNumber(value) : value ?? "—";
}

const CLASS_TONES = {
  compliant: "good", noncompliant: "bad", partial: "warn", unrelated: "muted", excluded: "faint",
};

function Badge({ tone = "neutral", children }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

function statusTone(status) {
  if (status === "complete") return "good";
  if (status === "handoff") return "warn";
  return "neutral";
}

function KpiCard({ label, hint, value, numerator, denominator, tone = "accent" }) {
  const width = value == null ? 0 : Math.min(100, value * 100);
  return (
    <div className="card kpi">
      <Tip as="div" hint={hint} className="kpi-label">{label}</Tip>
      <div className="kpi-value">{formatPercent(value)}</div>
      <div className="meter" aria-hidden="true"><span className={`fill-${tone}`} style={{ width: `${width}%` }} /></div>
      <div className="kpi-sub">{formatNumber(numerator)} / {formatNumber(denominator)}</div>
    </div>
  );
}

function StackedBar({ title, hint, prefix, counts }) {
  const entries = Object.entries(counts);
  const total = entries.reduce((sum, [, n]) => sum + n, 0);
  return (
    <div className="card">
      <div className="card-head"><Tip as="h2" hint={hint}>{title}</Tip><span className="muted">{formatNumber(total)} total</span></div>
      <div className="stack" role="img" aria-label={`${title} distribution`}>
        {total > 0 && entries.filter(([, n]) => n > 0).map(([cls, n]) => (
          <span key={cls} className={`fill-${CLASS_TONES[cls] ?? "muted"}`} style={{ width: `${(n / total) * 100}%` }} title={`${cls}: ${n}`} />
        ))}
      </div>
      <ul className="legend">
        {entries.map(([cls, n]) => (
          <li key={cls}>
            <i className={`dot fill-${CLASS_TONES[cls] ?? "muted"}`} />
            <Tip hint={`class_${cls}`} className="legend-name">{cls}</Tip>
            <span className="legend-value" data-metric={`${prefix}-${cls}`}>{formatNumber(n)}</span>
            <span className="legend-pct">{formatPercent(ratio(n, total))}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function StatGroup({ title, hint, rows }) {
  return (
    <div className="card">
      <Tip as="h2" hint={hint}>{title}</Tip>
      <dl className="stats">
        {rows.map(([label, value, rowHint]) => (
          <div key={label} className="stat-row"><Tip as="dt" hint={rowHint}>{label}</Tip><dd>{formatCell(value)}</dd></div>
        ))}
      </dl>
    </div>
  );
}

function BarTable({ title, hint, keyLabel, counts }) {
  const entries = Object.entries(counts ?? {}).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...entries.map(([, n]) => n));
  return (
    <div className="card">
      <Tip as="h2" hint={hint}>{title}</Tip>
      {entries.length === 0 ? <p className="muted">No data.</p> : (
        <table className="bar-table">
          <thead><tr><th>{keyLabel}</th><th className="num">Count</th></tr></thead>
          <tbody>
            {entries.map(([name, count]) => (
              <tr key={name}>
                <td>
                  <span className="bar-name">{name}</span>
                  <span className="bar-track" aria-hidden="true"><span className="fill-accent" style={{ width: `${(count / max) * 100}%` }} /></span>
                </td>
                <td className="num">{formatNumber(count)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function OtherSessions({ nonWorkflow }) {
  if (!nonWorkflow) return <div className="card"><p className="muted">No non-workflow session data.</p></div>;
  const byModel = nonWorkflow.cost?.by_model ?? {};
  const tokensByModel = nonWorkflow.cost?.tokens_by_model ?? {};
  const models = Object.keys(byModel);
  const unknownModels = nonWorkflow.cost?.unknown_models ?? [];
  return (
    <section aria-label="Other sessions" className="stack-gap">
      <div className="grid kpis">
        <div className="card kpi">
          <Tip as="div" hint="nw_sessions" className="kpi-label">Sessions</Tip>
          <div className="kpi-value" data-metric="non-workflow-sessions">{formatNumber(nonWorkflow.sessions)}</div>
          <div className="kpi-sub">outside workflow runs</div>
        </div>
        <div className="card kpi">
          <Tip as="div" hint="nw_models" className="kpi-label">Models</Tip>
          <div className="kpi-value">{models.length}</div>
          <div className="kpi-sub">{unknownModels.length} without pricing</div>
        </div>
      </div>
      <div className="grid two">
        <BarTable title="Tool usage" hint="tool_usage" keyLabel="Tool" counts={nonWorkflow.tools} />
        <BarTable title="Subagents" hint="subagents" keyLabel="Type" counts={nonWorkflow.subagents} />
      </div>
      <div className="card">
        <Tip as="h2" hint="cost_by_model">Cost by model</Tip>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Model</th><Tip as="th" hint="input_tokens" className="num">Input</Tip><Tip as="th" hint="output_tokens" className="num">Output</Tip><Tip as="th" hint="cache_read" className="num">Cache read</Tip><Tip as="th" hint="cache_write" className="num">Cache write</Tip><th className="num">Cost (USD)</th></tr></thead>
            <tbody>
              {models.map(model => {
                const tokens = tokensByModel[model] ?? {};
                return (
                  <tr key={model}>
                    <td className="mono">{model}</td>
                    <td className="num">{formatNumber(tokens.input_tokens)}</td>
                    <td className="num">{formatNumber(tokens.output_tokens)}</td>
                    <td className="num">{formatNumber(tokens.cache_read_tokens)}</td>
                    <td className="num">{formatNumber(tokens.cache_write_tokens)}</td>
                    <td className="num">{byModel[model] ?? <Badge tone="warn">unknown cost</Badge>}</td>
                  </tr>
                );
              })}
              <tr className="total-row">
                <td>Total</td>
                <td colSpan={4} />
                <td className="num">{nonWorkflow.cost?.total_usd}</td>
              </tr>
            </tbody>
          </table>
        </div>
        {unknownModels.length > 0 && (
          <p className="note">Unknown-priced models: {unknownModels.join(", ")}</p>
        )}
      </div>
    </section>
  );
}

const ISOLATION_RULES = [
  "test_reads_implementation", "test_runs_tests", "impl_reads_tests", "impl_runs_test_command", "dispatch_run_instruction",
];

function HarnessHacking({ data }) {
  if (!data) return null;
  const candidates = data.candidates ?? [];
  return (
    <section aria-label="Harness hacking" className="card">
      <div className="card-head"><Tip as="h2" hint="harness_hacking">Harness hacking</Tip></div>
      <ul className="legend">
        <li>
          <span className="legend-name">Total</span>
          <span className="legend-value" data-metric="harness-hacking-total">{formatNumber(data.total)}</span>
        </li>
        {ISOLATION_RULES.map(rule => (
          <li key={rule}>
            <Tip hint={`rule_${rule}`} className="legend-name mono">{rule}</Tip>
            <span className="legend-value" data-metric={`harness-hacking-${rule}`}>{formatNumber(data.by_rule?.[rule] ?? 0)}</span>
          </li>
        ))}
      </ul>
      {candidates.length === 0 ? <p className="muted">No isolation candidates recorded.</p> : (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Time</th><th>Run</th><th>Agent</th><th>Rule</th><th>Match</th><th>Excerpt</th></tr></thead>
            <tbody>
              {candidates.map((item, i) => (
                <tr key={i}>
                  <td className="muted nowrap">{item.ts ?? "—"}</td>
                  <td className="mono">{item.workflow_run_id ?? "—"}</td>
                  <td>{item.agent_type ?? "main"}</td>
                  <td className="mono">{item.rule}</td>
                  <td className="mono">{item.match ?? "—"}{item.match_kind && <> <Badge tone="neutral">{item.match_kind}</Badge></>}</td>
                  <td className="mono excerpt">{item.excerpt ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function RunDetail({ detail, onBack }) {
  const reasons = detail.compliance_reasons ?? [];
  return (
    <section className="stack-gap">
      <div className="detail-head">
        <button className="ghost" onClick={onBack}>← Back to runs</button>
        <h1 className="mono">Run {detail.run_id}</h1>
        <div className="badges">
          <Badge tone={statusTone(detail.status)}>{detail.status}</Badge>
          <Badge tone={detail.compliant ? "good" : "bad"}>{detail.compliant ? "compliant" : "noncompliant"}</Badge>
        </div>
      </div>
      <div className="grid three">
        <StatGroup title="Run" hint="group_runs" rows={[
          ["Run ID", detail.run_id, "run_id"], ["Spec", detail.spec, "spec"], ["Spec version", detail.spec_version, "spec_version"],
          ["Linked cost (USD)", formatUsd(detail.linked_cost_usd), "linked_cost"],
        ]} />
        <StatGroup title="Verification" hint="group_verification" rows={[
          ["Verifier rounds", detail.verifier_rounds, "verifier_rounds"], ["Verifier retries", detail.verifier_retries, "verifier_retries"],
          ["Seeds run", detail.seeds_run, "seeds_run"], ["Seeds detected", detail.seeds_detected, "seeds_detected"],
          ["Fuzz executions", detail.fuzz_execs, "fuzz_execs"], ["Fuzz violations", detail.fuzz_violations, "fuzz_violations"],
        ]} />
        <StatGroup title="Mutation" hint="group_mutation" rows={[
          ["Tool mutants", detail.mutants, "mutants"], ["Mutants killed", detail.killed, "killed"], ["Mutants survived", detail.survived, "survived"],
          ["Equivalent mutants", detail.equivalent, "equivalent"], ["Triage verdicts overturned", detail.overturned, "overturned"],
        ]} />
      </div>
      <div className="card">
        <Tip as="h2" hint="compliance_reasons">Compliance reasons</Tip>
        {reasons.length > 0 ? (
          <ul className="reasons">{reasons.map((reason, i) => <li key={i} className="mono">{reason}</li>)}</ul>
        ) : <p className="muted">No compliance reasons.</p>}
      </div>
      <div className="card">
        <Tip as="h2" hint="usage">Usage</Tip>
        <ul className="usage">
          {(detail.transcript_metadata ?? []).map((entry, i) => (
            <li key={i}>
              Client: {entry.client}, Model: {entry.model}, Cost: {formatUsd(entry.linked_cost_usd)}
            </li>
          ))}
        </ul>
      </div>
      <HarnessHacking data={detail.harness_hacking} />
    </section>
  );
}

function WorkflowSummary({ summary, onSelect }) {
  const killable = summary.mutants == null ? null : summary.mutants - (summary.equivalent ?? 0);
  return (
    <section aria-label="Summary" className="stack-gap">
      <div className="grid kpis">
        <KpiCard label="Compliance rate" hint="compliance_rate" value={ratio(summary.compliant_runs, summary.runs)} numerator={summary.compliant_runs} denominator={summary.runs} tone="good" />
        <KpiCard label="Completion rate" hint="completion_rate" value={ratio(summary.completed_runs, summary.runs)} numerator={summary.completed_runs} denominator={summary.runs} />
        <KpiCard label="Mutation kill rate" hint="kill_rate" value={ratio(summary.killed, killable)} numerator={summary.killed} denominator={killable} />
        <KpiCard label="Seed detection rate" hint="seed_rate" value={ratio(summary.seeds_detected, summary.seeds_run)} numerator={summary.seeds_detected} denominator={summary.seeds_run} />
      </div>
      {summary.classification && (
        <div className="grid two">
          <StackedBar title="Runs by class" hint="runs_by_class" prefix="class-runs" counts={summary.classification.runs} />
          <StackedBar title="Sessions by class" hint="sessions_by_class" prefix="class-sessions" counts={summary.classification.sessions} />
        </div>
      )}
      <div className="grid three">
        <StatGroup title="Runs" hint="group_runs" rows={[
          ["Runs", <span data-metric="runs">{summary.runs}</span>, "runs"],
          ["Completed runs", summary.completed_runs, "completed_runs"], ["Compliant runs", summary.compliant_runs, "compliant_runs"],
          ["Handoff runs", summary.handoff_runs, "handoff_runs"],
          ["Linked cost (USD)", formatUsd(summary.linked_cost_usd), "linked_cost"],
        ]} />
        <StatGroup title="Verification" hint="group_verification" rows={[
          ["Verifier rounds", summary.verifier_rounds, "verifier_rounds"], ["Verifier retries", summary.verifier_retries, "verifier_retries"],
          ["Seeds run", summary.seeds_run, "seeds_run"], ["Seeds detected", summary.seeds_detected, "seeds_detected"],
          ["Fuzz executions", summary.fuzz_execs, "fuzz_execs"], ["Fuzz violations", summary.fuzz_violations, "fuzz_violations"],
        ]} />
        <StatGroup title="Mutation" hint="group_mutation" rows={[
          ["Tool mutants", summary.mutants, "mutants"], ["Mutants killed", summary.killed, "killed"], ["Mutants survived", summary.survived, "survived"],
          ["Equivalent mutants", summary.equivalent, "equivalent"], ["Triage verdicts overturned", summary.overturned, "overturned"],
        ]} />
      </div>
      <HarnessHacking data={summary.harness_hacking} />
      <div className="card">
        <div className="card-head"><Tip as="h2" hint="run_list">Workflow runs</Tip><span className="muted">{summary.run_items.length}</span></div>
        {summary.run_items.length === 0 ? (
          <p className="muted">No workflow runs yet.</p>
        ) : (
          <nav aria-label="Workflow runs" className="table-wrap">
            <table className="runs">
              <thead><tr><Tip as="th" hint="run_id">Run</Tip><Tip as="th" hint="spec">Spec</Tip><Tip as="th" hint="status">Status</Tip><Tip as="th" hint="compliance">Compliance</Tip></tr></thead>
              <tbody>
                {summary.run_items.map(run => (
                  <tr key={run.run_id}>
                    <td>
                      <a className="mono" href={`/runs/${encodeURIComponent(run.run_id)}`} onClick={(event) => { event.preventDefault(); onSelect(run.run_id); }}>
                        {run.run_id}
                      </a>
                    </td>
                    <td className="muted">{run.spec}</td>
                    <td><Badge tone={statusTone(run.status)}>{run.status}</Badge></td>
                    <td><Badge tone={run.compliant ? "good" : "bad"}>{run.compliant ? "compliant" : "noncompliant"}</Badge></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </nav>
        )}
      </div>
    </section>
  );
}

export default function App({ apiBase = "" }) {
  const [summary, setSummary] = useState(null);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState("workflow");
  const [lang, setLang] = useState(detectLang);
  const chooseLang = (next) => { setLang(next); try { localStorage.setItem("analytics-lang", next); } catch {} };
  useEffect(() => {
    fetch(`${apiBase}/api/summary`).then(r => r.ok ? r.json() : Promise.reject(new Error("Unable to load analytics"))).then(setSummary).catch(e => setError(e.message));
  }, [apiBase]);
  useEffect(() => {
    if (!selected) return;
    setDetail(null);
    fetch(`${apiBase}/api/runs/${encodeURIComponent(selected)}`).then(r => r.ok ? r.json() : Promise.reject(new Error("Unable to load run"))).then(setDetail).catch(e => setError(e.message));
  }, [apiBase, selected]);
  if (error) return <main className="center" role="alert"><div className="card"><h1>Analytics unavailable</h1><p className="muted">{error}</p></div></main>;
  if (!summary) return <main className="center" role="status" aria-busy="true"><div className="spinner" /><h1>Loading analytics</h1></main>;

  let body;
  if (tab === "other") body = <OtherSessions nonWorkflow={summary.non_workflow} />;
  else if (selected && !detail) body = <div className="center" role="status" aria-busy="true"><div className="spinner" /><h1>Loading run</h1></div>;
  else if (detail) body = <RunDetail detail={detail} onBack={() => { setSelected(null); setDetail(null); }} />;
  else body = <WorkflowSummary summary={summary} onSelect={setSelected} />;

  return (
    <main>
      <header className="topbar">
        <div className="brand"><span className="logo" aria-hidden="true" /><span>Harness analytics</span></div>
        <nav aria-label="Dashboard tabs" className="segmented tabs">
          <button aria-pressed={tab === "workflow"} onClick={() => setTab("workflow")}>Workflow</button>
          <button aria-pressed={tab === "other"} onClick={() => setTab("other")}>Other sessions</button>
        </nav>
        <div className="segmented lang" role="group" aria-label="Language">
          <button aria-pressed={lang === "ko"} onClick={() => chooseLang("ko")}>KO</button>
          <button aria-pressed={lang === "en"} onClick={() => chooseLang("en")}>EN</button>
        </div>
      </header>
      <LangContext.Provider value={lang}>{body}</LangContext.Provider>
    </main>
  );
}
