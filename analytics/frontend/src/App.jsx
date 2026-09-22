import { useEffect, useState } from "react";

export default function App({ apiBase = "" }) {
  const [summary, setSummary] = useState(null);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    fetch(`${apiBase}/api/summary`).then(r => r.ok ? r.json() : Promise.reject(new Error("Unable to load analytics"))).then(setSummary).catch(e => setError(e.message));
  }, [apiBase]);
  useEffect(() => {
    if (!selected) return;
    setDetail(null);
    fetch(`${apiBase}/api/runs/${encodeURIComponent(selected)}`).then(r => r.ok ? r.json() : Promise.reject(new Error("Unable to load run"))).then(setDetail).catch(e => setError(e.message));
  }, [apiBase, selected]);
  if (error) return <main role="alert"><h1>Analytics unavailable</h1><p>{error}</p></main>;
  if (!summary) return <main role="status" aria-busy="true"><h1>Loading analytics</h1></main>;
  if (selected && !detail) return <main role="status" aria-busy="true"><h1>Loading run</h1></main>;
  if (detail) {
    const detailCost = detail.linked_cost_usd ?? "unknown cost";
    return (
      <main>
        <button onClick={() => { setSelected(null); setDetail(null); }}>Back to runs</button>
        <h1>Run {detail.run_id}</h1>
        <dl>
          <dt>Run ID</dt>
          <dd>{detail.run_id}</dd>
          <dt>Spec</dt>
          <dd>{detail.spec}</dd>
          <dt>Spec version</dt>
          <dd>{detail.spec_version}</dd>
          <dt>Status</dt>
          <dd>{detail.status}</dd>
          <dt>Compliant</dt>
          <dd>{String(detail.compliant)}</dd>
          <dt>Verifier rounds</dt>
          <dd>{detail.verifier_rounds}</dd>
          <dt>Verifier retries</dt>
          <dd>{detail.verifier_retries}</dd>
          <dt>Seeds run</dt>
          <dd>{detail.seeds_run}</dd>
          <dt>Seeds detected</dt>
          <dd>{detail.seeds_detected}</dd>
          <dt>Linked cost (USD)</dt>
          <dd>{detailCost}</dd>
        </dl>
        <h2>Compliance reasons</h2>
        {detail.compliance_reasons && detail.compliance_reasons.length > 0 ? (
          <ul>
            {detail.compliance_reasons.map((reason, i) => <li key={i}>{reason}</li>)}
          </ul>
        ) : <p>No compliance reasons.</p>}
        <h2>Usage</h2>
        <ul>
          {detail.transcript_metadata.map((entry, i) => (
            <li key={i}>
              Client: {entry.client}, Model: {entry.model}, Cost: {entry.linked_cost_usd ?? "unknown cost"}
            </li>
          ))}
        </ul>
      </main>
    );
  }
  const summaryCost = summary.linked_cost_usd ?? "unknown cost";
  return (
    <main>
      <h1>Harness analytics</h1>
      <section aria-label="Summary">
        <p>Runs: <span data-metric="runs">{summary.runs}</span></p>
        <p>Completed runs: {summary.completed_runs}</p>
        <p>Compliant runs: {summary.compliant_runs}</p>
        <p>Handoff runs: {summary.handoff_runs}</p>
        <p>Verifier rounds: {summary.verifier_rounds}</p>
        <p>Verifier retries: {summary.verifier_retries}</p>
        <p>Seeds run: {summary.seeds_run}</p>
        <p>Seeds detected: {summary.seeds_detected}</p>
        <p>Linked cost (USD): {summaryCost}</p>
      </section>
      {summary.run_items.length === 0 ? (
        <p>No workflow runs yet.</p>
      ) : (
        <nav aria-label="Workflow runs">
          <ul>
            {summary.run_items.map(run => (
              <li key={run.run_id}>
                <a href={`/runs/${encodeURIComponent(run.run_id)}`} onClick={(event) => { event.preventDefault(); setSelected(run.run_id); }}>
                  {run.run_id} — status: {run.status}, compliant: {String(run.compliant)}
                </a>
              </li>
            ))}
          </ul>
        </nav>
      )}
    </main>
  );
}
