import { useEffect, useState } from 'react';
import { AlertCircle, ArrowRight, CheckCircle2, ChevronDown, Clock3, FlaskConical, Info, LoaderCircle, Play, RefreshCw, ShieldCheck, ShieldQuestion, SlidersHorizontal, XCircle } from 'lucide-react';
import { api, formatDate, type GuardStatus, type LabCase, type LabReport, type SecurityLabInventory } from './api';

const categoryLabels: Record<string, string> = {
  uploads: 'Uploads', invalid_uploads: 'Invalid uploads', upload: 'Uploads', prompt_injection: 'Prompt injection',
  missing_fields: 'Missing fields', financial: 'Financial checks', financial_discrepancies: 'Financial checks',
  authorization: 'Authorization', audit: 'Audit integrity', validation: 'Validation',
};
const outcomeLabels = { passed: 'PASS', failed: 'FAIL', skipped: 'NOT RUN' };
const controlLabels = { implemented: 'Implemented', optional: 'Optional', limitation: 'Limitation' };
function categoryLabel(value: string) { return categoryLabels[value] || value.replace(/[_-]/g, ' ').replace(/^./, letter => letter.toUpperCase()); }
function duration(value: number) { return value < 1000 ? `${Math.round(value)} ms` : `${(value / 1000).toFixed(1)} s`; }

function Failure({ message, retry }: { message: string; retry?: () => void }) {
  return <div className="error-box" role="alert"><AlertCircle size={17} /><span>{message}</span>{retry && <button className="text-button" onClick={retry}>Try again</button>}</div>;
}

function ClassifierStatus({ guard }: { guard: GuardStatus }) {
  const runtimeReady = guard.enabled && guard.available && guard.runtime_verified;
  return <section className="panel lab-classifier" aria-labelledby="classifier-title">
    <div className="lab-card-heading"><span className="lab-card-icon"><ShieldQuestion size={21} /></span><div><span className="section-kicker">OPTIONAL CLASSIFIER</span><h2 id="classifier-title">Llama Prompt Guard 2</h2></div><span className={`lab-chip ${runtimeReady ? 'runtime' : 'neutral'}`}>{guard.status.replace(/[_-]/g, ' ')}</span></div>
    <p className="lab-body-copy">{guard.reason || 'No classifier diagnostics were returned by the backend.'}</p>
    <dl className="lab-guard-facts"><div><dt>Configured model</dt><dd>{guard.model || 'Not configured'}</dd></div><div><dt>Runtime exercised</dt><dd>{guard.runtime_verified ? 'Yes, see reported results' : 'Not verified'}</dd></div><div><dt>Score threshold</dt><dd>{Number.isFinite(guard.threshold) ? guard.threshold.toFixed(2) : 'Not reported'}</dd></div></dl>
    {guard.enabled && <p className="lab-fine-print">Built with Llama · <a href="https://huggingface.co/meta-llama/Llama-Prompt-Guard-2-22M/blob/main/LICENSE" target="_blank" rel="noopener noreferrer">Llama 4 Community License</a></p>}
    <p className="lab-fine-print">Classifier scores are review signals. False positives and missed injections are possible; a clear result does not establish safety.</p>
  </section>;
}

function CaseResult({ result }: { result: LabCase }) {
  const Icon = result.status === 'passed' ? CheckCircle2 : result.status === 'failed' ? XCircle : Clock3;
  return <details className={`lab-case ${result.status}`}>
    <summary><span className={`lab-outcome-icon ${result.status}`}><Icon size={19} /></span><span className="lab-case-title"><strong>{result.title}</strong><span>{categoryLabel(result.category)}<span className="dot-separator">·</span>{result.method === 'classifier' ? 'Configured classifier' : result.method === 'contract' ? 'Contract check' : 'Integration check'}</span></span><span className={`lab-chip ${result.status}`}>{outcomeLabels[result.status]}</span><time>{duration(result.duration_ms)}</time><ChevronDown size={16} className="lab-case-chevron" /></summary>
    <div className="lab-case-details"><dl className="lab-expectations"><div><dt>Expected</dt><dd>{result.expected}</dd></div><div><dt>Observed</dt><dd>{result.observed}</dd></div></dl>{result.error && <div className="lab-case-error"><AlertCircle size={15} /><span>{result.error}</span></div>}<div className="lab-evidence-label">Recorded evidence</div><pre className="lab-evidence">{JSON.stringify(result.evidence, null, 2)}</pre><span className="lab-case-id">Check ID: {result.id}</span></div>
  </details>;
}

export default function SecurityLab() {
  const [inventory, setInventory] = useState<SecurityLabInventory | null>(null);
  const [report, setReport] = useState<LabReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const [category, setCategory] = useState('');
  const [outcome, setOutcome] = useState('');

  useEffect(() => {
    let active = true;
    setLoading(true); setError('');
    api.securityLab().then(value => { if (active) { setInventory(value); setReport(value.last_run); } })
      .catch(reason => { if (active) setError((reason as Error).message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [revision]);

  async function run() {
    setRunning(true); setError('');
    try { const value = await api.runSecurityLab(); setReport(value); setCategory(''); setOutcome(''); }
    catch (reason) { setError((reason as Error).message || 'Security checks could not be completed. No new result was recorded.'); }
    finally { setRunning(false); }
  }

  const guard = report?.guard || inventory?.guard;
  const categories = [...new Set(report?.cases.map(item => item.category) || [])];
  const visibleCases = report?.cases.filter(item => (!category || category === item.category) && (!outcome || outcome === item.status)) || [];
  const metrics = [{ key: 'total', label: 'Checks executed or not run', icon: FlaskConical }, { key: 'passed', label: 'Passed for these fixtures', icon: CheckCircle2 }, { key: 'failed', label: 'Failed checks', icon: XCircle }, { key: 'skipped', label: 'Not run / unavailable', icon: Clock3 }] as const;

  return <>
    <div className="page-title"><div><div className="eyebrow">SECURITY LAB</div><h1>Test the controls. Inspect the evidence.</h1><p>Run bounded checks with synthetic documents and inspect what actually happened.</p></div><div className="page-actions"><button className="button primary" onClick={run} disabled={running || loading || !inventory}>{running ? <LoaderCircle size={17} className="spin" /> : <Play size={16} />}{running ? 'Running checks…' : 'Run security checks'}</button></div></div>
    <div className="info-banner lab-scope-notice"><Info size={18} /><span>Checks provide evidence for these fixtures, not a security guarantee. Runs use isolated synthetic records; no AI can authorize access, make review decisions, or release funds.</span></div>
    {error && <Failure message={error} retry={running ? undefined : () => setRevision(value => value + 1)} />}
    {loading && !inventory ? <div className="loading"><LoaderCircle size={23} className="spin" /><span>Inspecting configured controls…</span></div> : <>
      <div className="metrics lab-metrics">{metrics.map(({ key, label, icon: Icon }) => <div className={`metric-card lab-metric-${key}`} key={key}><div className="metric-top"><span>{label}</span><span className="metric-icon"><Icon size={19} /></span></div><strong className="metric-value">{report ? report.summary[key] : '—'}</strong><div className="metric-note">{report ? 'From the latest completed run' : 'No completed run loaded'}</div></div>)}</div>
      <div className="lab-overview-grid">{guard && <ClassifierStatus guard={guard} />}<section className="panel lab-run-info"><div className="lab-card-heading"><span className="lab-card-icon"><FlaskConical size={21} /></span><div><span className="section-kicker">TEST SCOPE</span><h2>A reproducible local check</h2></div></div><p className="lab-body-copy">{report?.scope || 'The backend exercises predefined upload, validation, authorization, prompt handling, and audit scenarios against isolated data. Optional model checks can be skipped when the configured runtime is unavailable.'}</p>{report ? <dl className="lab-run-facts"><div><dt>Completed</dt><dd>{formatDate(report.finished_at, true)}</dd></div><div><dt>Duration</dt><dd>{duration(report.duration_ms)}</dd></div><div><dt>Run ID</dt><dd><code>{report.id}</code></dd></div></dl> : <p className="lab-fine-print">Nothing has been marked as passing. Run the checks to create a report.</p>}<button className="text-button" disabled={running || loading} onClick={() => setRevision(value => value + 1)}><RefreshCw size={14} />Reload saved report<ArrowRight size={14} /></button></section></div>
      <section className="panel lab-results" aria-labelledby="lab-results-title"><div className="section-title"><div><h2 id="lab-results-title">Check results</h2><p>{report ? `${visibleCases.length} of ${report.cases.length} checks · expand a row for expected behavior, observations, and evidence` : 'Outcomes appear only after the backend completes a run.'}</p></div>{running && <span className="lab-running" role="status"><LoaderCircle size={15} className="spin" />Running real checks</span>}</div>
        {report ? <><div className="table-toolbar lab-filters"><label className="filter-select"><SlidersHorizontal size={15} /><select aria-label="Filter security category" value={category} onChange={event => setCategory(event.target.value)}><option value="">All categories</option>{categories.map(value => <option key={value} value={value}>{categoryLabel(value)}</option>)}</select></label><label className="filter-select"><select aria-label="Filter security outcome" value={outcome} onChange={event => setOutcome(event.target.value)}><option value="">All outcomes</option><option value="passed">Passed</option><option value="failed">Failed</option><option value="skipped">Skipped</option></select></label></div><div className="lab-case-list">{visibleCases.length ? visibleCases.map(result => <CaseResult key={result.id} result={result} />) : <div className="inline-empty">No checks match these filters.</div>}</div></> : <div className="empty lab-empty"><div className="empty-icon"><FlaskConical size={27} /></div><h3>No test report yet</h3><p>Run the suite to measure the configured controls. Unavailable model checks will be shown as skipped, with a reason.</p></div>}
      </section>
      {!!inventory?.controls.length && <section className="panel lab-controls" aria-labelledby="lab-controls-title"><div className="section-title"><div><h2 id="lab-controls-title">Control inventory</h2><p>Implemented controls, optional components, and limits reported by the backend.</p></div><ShieldCheck size={20} /></div><div className="lab-control-grid">{inventory.controls.map(control => <article className="lab-control" key={control.id}><span className={`lab-chip control-${control.state}`}>{controlLabels[control.state]}</span><h3>{control.title}</h3><p>{control.description}</p></article>)}</div></section>}
      {!!report?.limitations.length && <section className="lab-limitations" aria-labelledby="lab-limitations-title"><h2 id="lab-limitations-title"><Info size={17} />How to interpret this run</h2><ul>{report.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul></section>}
    </>}
  </>;
}
