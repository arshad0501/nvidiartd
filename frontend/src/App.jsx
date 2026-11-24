import { useCallback, useEffect, useState } from 'react'

const API = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'
const rank = { Critical: 0, High: 1, Medium: 2, Low: 3 }
async function call(path, options = {}) {
  const response = await fetch(API + path, { ...options, signal: options.signal || AbortSignal.timeout(90000) })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = payload.detail
    throw new Error(typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map(x => x.msg).join('; ') : 'The service could not complete this request.')
  }
  return payload
}

function App() {
  const [data, setData] = useState(null)
  const [runs, setRuns] = useState([])
  const [datasets, setDatasets] = useState([])
  const [dataset, setDataset] = useState('reviews_raw.csv')
  const [viewRun, setViewRun] = useState('')
  const [tab, setTab] = useState('overview')
  const [selectedId, setSelectedId] = useState(null)
  const [reviews, setReviews] = useState([])
  const [reviewError, setReviewError] = useState('')
  const [clusters, setClusters] = useState(7)
  const [routing, setRouting] = useState('complaint_aware')
  const [backend, setBackend] = useState('tfidf')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [running, setRunning] = useState(false)
  const [loading, setLoading] = useState(true)
  const [configured, setConfigured] = useState(null)

  const load = useCallback(async (id = '') => {
    setLoading(true); setError('')
    try {
      const [snapshot, history, sources, ai] = await Promise.all([
        call('/dashboard/snapshot' + (id ? '?run_id=' + id : '')),
        call('/runs'), call('/datasets'), call('/ai/status'),
      ])
      setData(snapshot); setRuns(history); setDatasets(sources); setConfigured(ai); setViewRun(id)
      setSelectedId(old => snapshot.themes.some(t => t.id === old) ? old : snapshot.themes[0]?.id || null)
    } catch (e) { setError(e.message) } finally { setLoading(false) }
  }, [])
  useEffect(() => { load() }, [load])

  const currentRun = data?.run?.id
  useEffect(() => {
    const abort = new AbortController()
    setReviews([]); setReviewError('')
    if (selectedId && currentRun) {
      call('/reviews?theme_id=' + selectedId + '&run_id=' + currentRun + '&limit=25', { signal: abort.signal })
        .then(setReviews).catch(e => { if (e.name !== 'AbortError') setReviewError(e.message) })
    }
    return () => abort.abort()
  }, [selectedId, currentRun])

  const run = async () => {
    setRunning(true); setMessage(''); setError('')
    try {
      const result = await call('/analyze', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ csv_path: dataset, n_clusters: clusters, routing, backend }) })
      setMessage('Published ' + result.reviews_ingested + ' reviews, ' + result.themes_discovered + ' themes and ' + result.insights_generated + ' advisory actions. Previous runs are retained.')
      await load('')
    } catch (e) { setError(e.message) } finally { setRunning(false) }
  }
  const exportRun = async () => {
    try {
      const bundle = await call('/runs/' + currentRun + '/export')
      const url = URL.createObjectURL(new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' }))
      const link = document.createElement('a'); link.href = url; link.download = 'drivesense-' + currentRun + '.json'; link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (e) { setError(e.message) }
  }
  const themes = data?.themes || [], insights = data?.insights || [], summary = data?.summary
  const selected = themes.find(t => t.id === selectedId)
  const max = Math.max(...themes.map(t => t.review_count), 1)
  const openEvidence = id => { setSelectedId(id); setTab('themes') }

  return <div className="shell">
    <aside><div className="brand"><b>DS</b><span>DriveSense<small>EVIDENCE TO ACTION</small></span></div>
      <nav aria-label="Main navigation">{[['overview', 'Overview'], ['themes', 'Theme evidence'], ['actions', 'Action review']].map(([id, label]) =>
        <button aria-current={tab === id ? 'page' : undefined} className={tab === id ? 'active' : ''} onClick={() => setTab(id)} key={id}>{label}</button>)}</nav>
      <div className="side-foot">Automotive triage prototype<br /><small>Human decisions. Traceable evidence.</small></div>
    </aside>
    <main>
      <header><div><p className="eyebrow">QUALITY INTELLIGENCE WORKSPACE</p><h1>Customer signal, <em>made inspectable.</em></h1><p className="intro">Find recurring complaints, inspect the evidence and review suggested next steps.</p></div>
        <button className="primary" disabled={running || loading || !datasets.length} onClick={run}>{running ? 'Analyzing…' : 'Run analysis'}</button></header>
      <section className="controls panel" aria-label="Analysis configuration">
        <label>Dataset<select value={dataset} onChange={e => setDataset(e.target.value)} disabled={running}>{datasets.map(d => <option key={d.name}>{d.name}</option>)}</select></label>
        <label>Requested clusters<input aria-label="Requested clusters" type="number" min="1" max="30" value={clusters} onChange={e => setClusters(Number(e.target.value))} disabled={running} /></label>
        <label>Complaint routing<select value={routing} onChange={e => setRouting(e.target.value)} disabled={running}><option value="complaint_aware">Complaint cues + negative sentiment</option><option value="negative_only">Negative sentiment only (baseline)</option></select></label>
        <label>Representation<select value={backend} onChange={e => setBackend(e.target.value)} disabled={running}><option value="tfidf">TF-IDF lexical vectors</option><option value="lsa">Latent semantic analysis (SVD)</option></select></label>
      </section>
      {error && <div className="notice error" role="alert">{error} <button onClick={() => load(viewRun)} disabled={running}>Retry loading</button></div>}
      {message && <div className="notice" role="status">{message}</div>}
      {loading && <p role="status">Loading the selected run…</p>}
      {summary && <section className="run-strip">
        <label>Published or historical run<select aria-label="Analysis run" value={viewRun} disabled={running || loading} onChange={e => load(e.target.value)}>
          <option value="">Latest successful run</option>{runs.filter(r => r.status === 'succeeded').map(r => <option key={r.id} value={r.id}>{r.started_at.slice(0, 19)} / {r.source_name} / {r.id.slice(0, 8)}</option>)}</select></label>
        <button onClick={exportRun}>Export evidence bundle</button>
        <small>Run {currentRun.slice(0, 8)} · {data.run.source_name} · SHA-256 {data.run.source_sha256.slice(0, 12)}…</small>
      </section>}
      <section className="llm"><div><p className="eyebrow">ACTUAL OUTPUT PROVENANCE</p><h2>{summary ? Object.entries(data.run.metrics.provider_counts || {}).map(([p, n]) => n + ' ' + p + ' actions').join(', ') || 'No complaint actions for this run' : 'Local analytics with optional hosted advice'}</h2>
        <p>VADER scores polarity intensity, not confidence. Themes and severity are preliminary. Every recommendation needs qualified human review. {configured?.nim_enabled ? 'NVIDIA is configured for future runs; each action records its actual provider.' : 'Hosted transfer is disabled unless explicitly configured.'}</p></div></section>
      {!loading && !summary && !error && <section className="empty"><h2>Choose a dataset and run the pipeline.</h2><p>The supplied vehicle reviews are synthetic demonstration data. No accuracy or real-world defect-detection claim is implied.</p></section>}
      {summary && <>
        {tab === 'overview' && <section>
          <div className="metrics"><Metric title="Reviews analyzed" value={summary.total_reviews} note={summary.positive_reviews + ' positive / ' + summary.negative_reviews + ' negative'} />
            <Metric title="Complaint candidates" value={summary.complaint_candidates} note="Includes factual or mixed-sentiment issue cues" danger />
            <Metric title="Neutral polarity" value={summary.neutral_reviews} note="Neutral is preserved as its own class" />
            <Metric title="Nonempty themes" value={summary.theme_count} note={'Requested K = ' + data.run.config.n_clusters} /></div>
          <div className="columns"><section className="panel"><p className="eyebrow">CANDIDATE REVIEW VOLUME</p><h2>Recurring complaint groups</h2>{!themes.length && <p>No candidates were found. This is a valid result, not proof that no defects exist.</p>}
            <div className="bars">{themes.map(t => <div className="bar" key={t.id}><button className="text-button" onClick={() => openEvidence(t.id)}>{t.theme_name}</button><div><i style={{ width: t.review_count / max * 100 + '%' }} /></div><b>{t.review_count}</b></div>)}</div>
          </section><section className="panel"><p className="eyebrow">ADVISORY SEVERITY</p><h2>Human triage queue</h2>{['Critical', 'High', 'Medium', 'Low'].map(level => <div className="severity-row" key={level}><span className={'severity ' + level.toLowerCase()}>{level}</span><b>{summary.severity_breakdown[level] || 0}</b></div>)}<p className="muted">Severity is a triage suggestion, not a verified diagnosis.</p></section></div>
          <section className="panel quality"><h2>Run transparency</h2><p>{data.run.cleaning.raw_rows} raw → {data.run.cleaning.clean_rows} retained. Removed {data.run.cleaning.duplicate_rows} duplicates, {data.run.cleaning.invalid_text_rows} invalid text rows and {data.run.cleaning.invalid_rating_rows} invalid ratings. Missing ratings remain unknown.</p>
            <p>{data.run.metrics.elapsed_seconds.toFixed(3)} seconds for this run · {data.run.metrics.backend || data.run.config.embedding_backend} · seed 42</p>
            {(data.run.metrics.warnings || []).map(w => <p key={w} className="notice">{w}</p>)}
            <details><summary>Scope and limitations</summary><ul>{data.limitations.map(l => <li key={l}>{l}</li>)}</ul></details>
          </section>
        </section>}
        {tab === 'themes' && <section className="theme-grid"><section className="panel"><p className="eyebrow">THEME EVIDENCE</p><h2>Explore concerns</h2>{themes.map(t => <button className={selectedId === t.id ? 'theme selected' : 'theme'} key={t.id} onClick={() => setSelectedId(t.id)}><span>{t.theme_name}</span><b>{t.review_count}</b></button>)}</section>
          <section className="panel">{selected ? <><h2>{selected.theme_name}</h2><p className="keywords">{selected.keywords || 'No lexical keywords available'}</p><p className="muted">{selected.explanation.method}. {selected.explanation.uncertain && 'Ambiguous or unmatched label: inspect the records.'}</p>
            {reviewError && <p role="alert">{reviewError}</p>}{reviews.map(r => <article className="review" key={r.id}><div><b>{r.vehicle}</b><span className={r.sentiment}>{r.sentiment}</span></div><p>“{r.review_text}”</p><small>Source row {r.source_row} · rating {r.rating ?? 'unknown'} · VADER compound {r.sentiment_score.toFixed(4)}</small><p className="muted">Routing: {r.routing_evidence.map(x => x.rule + (x.span ? ' (“' + x.span + '”)' : '')).join(', ')}</p></article>)}
            <small>Showing up to 25 records from this exact run. The export contains all retained records.</small></> : <p>No complaint themes for this run.</p>}</section></section>}
        {tab === 'actions' && <section><div className="action-head"><div><p className="eyebrow">EVIDENCE-LINKED ADVISORY OUTPUTS</p><h2>Engineering and service review</h2></div><p>Sorted by advisory severity, then volume. Review events record a user-entered reviewer name, not independently verified expertise.</p></div>
          <div className="cards">{[...insights].sort((a, b) => rank[a.severity] - rank[b.severity] || (themes.find(t => t.id === b.theme_id)?.review_count || 0) - (themes.find(t => t.id === a.theme_id)?.review_count || 0)).map(a => <ActionCard key={a.id} action={a} onEvidence={() => openEvidence(a.theme_id)} onSaved={() => load(currentRun)} />)}</div>
        </section>}
      </>}
      <footer>DriveSense AI v2 · Evidence-linked decision support · Original synthetic data preserved</footer>
    </main>
  </div>
}

function ActionCard({ action, onEvidence, onSaved }) {
  const [reviewer, setReviewer] = useState(''), [note, setNote] = useState(''), [decision, setDecision] = useState('accepted')
  const [engineering, setEngineering] = useState(''), [service, setService] = useState(''), [saving, setSaving] = useState(false), [error, setError] = useState('')
  const latest = action.review_history.at(-1)
  const edits = action.review_history.reduce((all, e) => ({ ...all, ...e.edits }), {})
  async function save(e) {
    e.preventDefault(); setSaving(true); setError('')
    try {
      await call('/insights/' + action.id + '/review', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ expected_version: action.review_version, reviewer, note, decision,
          ...(decision === 'edited' ? { engineering_recommendation: engineering || null, service_recommendation: service || null } : {}) }) })
      await onSaved()
    } catch (e) { setError(e.message) } finally { setSaving(false) }
  }
  return <article className="card"><div><span className={'severity ' + action.severity.toLowerCase()}>{action.severity}</span><small>{action.provider}{action.model ? ' / ' + action.model : ''}</small></div>
    <h3>{action.theme_name}</h3><p>{action.main_issue}</p>
    {action.fallback_reason && <p className="fallback">Fallback: {action.fallback_reason}</p>}
    <p className="muted">Rule/source: {action.rule_id} · {latest ? latest.decision + ' by ' + latest.reviewer : 'Awaiting human review'}</p>
    <b>ENGINEERING</b><p>{edits.engineering_recommendation || action.engineering_recommendation}</p><b>SERVICE OPERATIONS</b><p>{edits.service_recommendation || action.service_recommendation}</p>
    <button onClick={onEvidence}>Open theme evidence</button>
    <details><summary>Selected source evidence ({action.evidence.length})</summary>{action.evidence.map(r => <blockquote key={r.id}>“{r.review_text}”<small>Source row {r.source_row} · {r.selection}</small></blockquote>)}</details>
    <details><summary>Record a human review</summary><form onSubmit={save}>
      <label>Reviewer name or pseudonym<input required minLength="2" maxLength="80" value={reviewer} onChange={e => setReviewer(e.target.value)} /></label>
      <label>Decision<select value={decision} onChange={e => setDecision(e.target.value)}><option value="accepted">Accept for further investigation</option><option value="edited">Edit advisory text</option><option value="rejected">Reject advisory</option></select></label>
      {decision === 'edited' && <><label>Replacement engineering advice<textarea minLength="8" maxLength="3000" value={engineering} onChange={e => setEngineering(e.target.value)} /></label><label>Replacement service advice<textarea minLength="8" maxLength="3000" value={service} onChange={e => setService(e.target.value)} /></label><small>Enter at least one replacement.</small></>}
      <label>Reason and evidence checked<textarea required minLength="8" maxLength="2000" value={note} onChange={e => setNote(e.target.value)} /></label>
      {error && <p role="alert">{error}</p>}<button disabled={saving}>{saving ? 'Saving…' : 'Save review event'}</button>
    </form></details>
    {!!action.review_history.length && <details><summary>Review history ({action.review_history.length})</summary>{action.review_history.map(e => <p key={e.id}>v{e.version} · {e.decision} · {e.reviewer} · {e.created_at}<br />{e.note}</p>)}<p>Original advice is retained in the evidence export.</p></details>}
  </article>
}
const Metric = ({ title, value, note, danger }) => <article className={danger ? 'metric danger' : 'metric'}><p>{title}</p><h2>{value}</h2><small>{note}</small></article>
export default App
