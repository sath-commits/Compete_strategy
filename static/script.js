/* ── State ── */
let currentCompany = null;
let chatHistory = [];
let domainChart = null;
let seniorityChart = null;
let loadingTimers = [];
let currentInsights = [];
let currentSourceStatus = null;
let loadingQuoteTimer = null;
let loadingQuoteDeck = [];
let sourceMixChart = null;
let loadingProgressTimer = null;
let loadingStartedAt = 0;
let chartJsPromise = null;
let currentFeaturedInsight = null;
let currentJobCount = 0;

/* Tell browser we manage scroll restoration ourselves */
if ('scrollRestoration' in history) history.scrollRestoration = 'manual';

/* ── Loading progress ── */
const LOAD_STEPS = [
  { icon: 'bi-search',         label: 'Fetching job postings',         detail: 'Using job data APIs for current openings…', delay: 0 },
  { icon: 'bi-building-check', label: 'Collecting official sources',   detail: 'Checking SEC filings, company newsrooms, changelogs, and official GitHub sources when available…', delay: 6000 },
  { icon: 'bi-cpu',            label: 'Extracting structured signals', detail: 'Pulling tools, metrics, launches, and priorities from jobs and official company materials…', delay: 18000 },
  { icon: 'bi-diagram-3',      label: 'Classifying strategy domains',  detail: 'Tagging signals across growth, AI infra, enterprise, and more…', delay: 36000 },
  { icon: 'bi-lightbulb',      label: 'Generating insights',           detail: 'Combining hiring and official company signals into strategy insights…', delay: 54000 },
  { icon: 'bi-bar-chart-line', label: 'Building analysis',             detail: 'Summarizing domains, skills, seniority, and source-backed evidence…', delay: 76000 },
];

const LOADING_QUOTES = [
  { text: '“Know thyself, know thy enemy.”', author: 'Sun Tzu' },
  { text: '“Well begun is half done.”', author: 'Aristotle' },
  { text: '“Fortune favors the prepared mind.”', author: 'Louis Pasteur' },
  { text: '“The essence of strategy is choosing what not to do.”', author: 'Michael Porter' },
  { text: '“However beautiful the strategy, you should occasionally look at the results.”', author: 'Winston Churchill' },
  { text: '“Plans are only good intentions unless they immediately degenerate into hard work.”', author: 'Peter Drucker' },
  { text: '“In preparing for battle I have always found that plans are useless, but planning is indispensable.”', author: 'Dwight D. Eisenhower' },
  { text: '“What gets measured gets managed.”', author: 'Peter Drucker' },
  { text: '“The biggest risk is not taking any risk.”', author: 'Mark Zuckerberg' },
  { text: '“There is nothing so useless as doing efficiently that which should not be done at all.”', author: 'Peter Drucker' },
  { text: '“You can’t manage what you can’t measure.”', author: 'W. Edwards Deming' },
  { text: '“The best way to predict the future is to create it.”', author: 'Peter Drucker' },
  { text: '“Strategy is about making choices, trade-offs; it’s about deliberately choosing to be different.”', author: 'Michael Porter' },
  { text: '“The more you say no to, the more powerful your yes becomes.”', author: 'Unknown' },
  { text: '“If you have more than three priorities, you don’t have any.”', author: 'Jim Collins' },
  { text: '“Bad companies are destroyed by crisis. Good companies survive them. Great companies are improved by them.”', author: 'Andy Grove' },
  { text: '“Only the paranoid survive.”', author: 'Andy Grove' },
  { text: '“Focus is saying no to a hundred other good ideas.”', author: 'Steve Jobs' },
  { text: '“You have to be fast on your feet and adaptive or else a strategy is useless.”', author: 'Charles de Gaulle' },
  { text: '“Execution is strategy.”', author: 'Fred Wilson' },
  { text: '“A strategy delineates a territory in which a company seeks to be unique.”', author: 'Michael Porter' },
  { text: '“The beginning is the most important part of the work.”', author: 'Plato' },
  { text: '“What is well conceived is clearly said.”', author: 'Boileau' },
  { text: '“It is quality rather than quantity that matters.”', author: 'Seneca' },
  { text: '“The more we do, the more we can do.”', author: 'William Hazlitt' },
  { text: '“Energy and persistence conquer all things.”', author: 'Benjamin Franklin' },
  { text: '“Great acts are made up of small deeds.”', author: 'Lao Tzu' },
  { text: '“Diligence is the mother of good fortune.”', author: 'Benjamin Disraeli' },
  { text: '“By failing to prepare, you are preparing to fail.”', author: 'Benjamin Franklin' },
  { text: '“The secret of getting ahead is getting started.”', author: 'Mark Twain' },
  { text: '“Action may not always bring happiness, but there is no happiness without action.”', author: 'William James' },
  { text: '“Nothing will work unless you do.”', author: 'Maya Angelou' },
  { text: '“The future depends on what you do today.”', author: 'Mahatma Gandhi' },
  { text: '“A goal without a plan is just a wish.”', author: 'Antoine de Saint-Exupery' },
  { text: '“He who is everywhere is nowhere.”', author: 'Seneca' },
  { text: '“To choose time is to save time.”', author: 'Francis Bacon' },
];

function startLoadingSteps(company) {
  const panel = el('loading-panel');
  const container = el('loading-steps');
  container.innerHTML = LOAD_STEPS.map((s, i) => `
    <div class="load-step waiting" id="lstep-${i}">
      <div class="step-icon waiting" id="lstep-icon-${i}">
        <i class="bi ${s.icon}"></i>
      </div>
      <div class="step-text-wrap">
        <div class="step-label">${s.label}</div>
        <div class="step-detail">${s.detail}</div>
      </div>
    </div>`).join('');
  panel.classList.remove('hidden');
  loadingStartedAt = Date.now();
  startLoadingProgress();

  // Activate each step after its delay
  LOAD_STEPS.forEach((s, i) => {
    const t = setTimeout(() => activateStep(i), s.delay);
    loadingTimers.push(t);
  });

  startLoadingQuotes();
}

function activateStep(i) {
  // Mark previous step as done
  if (i > 0) {
    const prev = el(`lstep-${i-1}`);
    const prevIcon = el(`lstep-icon-${i-1}`);
    if (prev) { prev.className = 'load-step done'; }
    if (prevIcon) { prevIcon.innerHTML = '<i class="bi bi-check-lg"></i>'; prevIcon.className = 'step-icon done'; }
  }
  const step = el(`lstep-${i}`);
  const icon = el(`lstep-icon-${i}`);
  if (step) step.className = 'load-step active';
  if (icon) { icon.innerHTML = '<div class="step-spin"></div>'; icon.className = 'step-icon active'; }
}

function stopLoadingSteps() {
  loadingTimers.forEach(clearTimeout);
  loadingTimers = [];
  if (loadingQuoteTimer) {
    clearInterval(loadingQuoteTimer);
    loadingQuoteTimer = null;
  }
  if (loadingProgressTimer) {
    clearInterval(loadingProgressTimer);
    loadingProgressTimer = null;
  }
  hide('loading-panel');
  // Mark all as done cleanly
  LOAD_STEPS.forEach((_, i) => {
    const step = el(`lstep-${i}`);
    const icon = el(`lstep-icon-${i}`);
    if (step) step.className = 'load-step done';
    if (icon) { icon.innerHTML = '<i class="bi bi-check-lg"></i>'; icon.className = 'step-icon done'; }
  });
  const progress = el('loading-progress-bar');
  const elapsed = el('loading-elapsed');
  if (progress) progress.style.width = '100%';
  if (elapsed && loadingStartedAt) elapsed.textContent = `${Math.round((Date.now() - loadingStartedAt) / 1000)}s elapsed`;
}

function startLoadingQuotes() {
  const quoteEl = el('loading-quote');
  if (!quoteEl) return;

  loadingQuoteDeck = [...LOADING_QUOTES]
    .map(q => ({ q, sort: Math.random() }))
    .sort((a, b) => a.sort - b.sort)
    .map(x => x.q);
  let idx = 0;
  const render = () => {
    if (idx >= loadingQuoteDeck.length) {
      loadingQuoteDeck = [...LOADING_QUOTES]
        .map(q => ({ q, sort: Math.random() }))
        .sort((a, b) => a.sort - b.sort)
        .map(x => x.q);
      idx = 0;
    }
    const q = loadingQuoteDeck[idx];
    quoteEl.innerHTML = `<div style="font-style:italic">${q.text}</div><div style="margin-top:6px;font-size:0.8rem;letter-spacing:0.04em;text-transform:uppercase;opacity:0.72">— ${q.author}</div>`;
    idx += 1;
  };

  render();
  if (loadingQuoteTimer) clearInterval(loadingQuoteTimer);
  loadingQuoteTimer = setInterval(render, 4500);
}

function startLoadingProgress() {
  const progress = el('loading-progress-bar');
  const elapsed = el('loading-elapsed');
  const estimate = el('loading-estimate');
  if (!progress || !elapsed || !estimate) return;

  const targetSeconds = 75;
  estimate.textContent = 'Usually takes 30-75 seconds on a fresh run because jobs, official sources, and AI extraction run together.';
  progress.style.width = '4%';
  elapsed.textContent = '0s elapsed';

  if (loadingProgressTimer) clearInterval(loadingProgressTimer);
  loadingProgressTimer = setInterval(() => {
    const elapsedSeconds = Math.round((Date.now() - loadingStartedAt) / 1000);
    elapsed.textContent = `${elapsedSeconds}s elapsed`;
    const pct = Math.min(95, 4 + Math.round((elapsedSeconds / targetSeconds) * 91));
    progress.style.width = `${pct}%`;
    if (elapsedSeconds > 75) {
      estimate.textContent = 'This run is taking longer than usual because some source or AI calls are slower than normal.';
    }
  }, 500);
}

/* ── Helpers ── */
function show(id) { document.getElementById(id).classList.remove('hidden'); }
function hide(id) { document.getElementById(id).classList.add('hidden'); }
function el(id)   { return document.getElementById(id); }

function loadChartJs() {
  if (window.Chart) return Promise.resolve(window.Chart);
  if (chartJsPromise) return chartJsPromise;

  chartJsPromise = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js';
    script.async = true;
    script.onload = () => resolve(window.Chart);
    script.onerror = () => {
      chartJsPromise = null;
      reject(new Error('Failed to load Chart.js'));
    };
    document.head.appendChild(script);
  });

  return chartJsPromise;
}

function showError(msg) {
  const e = el('error-msg');
  e.textContent = msg;
  e.classList.remove('hidden');
}
function clearError() { el('error-msg').classList.add('hidden'); }

/* Allow Enter key in search box */
el('company-input').addEventListener('keydown', e => { if (e.key === 'Enter') runAnalysis(); });
el('chat-input').addEventListener('keydown', e => { if (e.key === 'Enter') sendChat(); });

/* ── Step 1: Resolve then analyze ── */
// Track names already tried this session to prevent suggestion loops
const triedNames = new Set();

async function runAnalysis(resolvedName = null, forceRefresh = false) {
  const rawQuery = el('company-input').value.trim();
  if (!rawQuery) { showError('Please enter a company name.'); return; }
  clearError();
  hide('disambig-panel');
  hide('did-you-mean');

  if (!resolvedName) triedNames.clear(); // fresh search = reset loop guard
  const query = resolvedName || rawQuery;
  // Always resolve — catches "service now" → "ServiceNow", "open ai" → "OpenAI",
  // "ms" → ambiguous, etc. The resolver is a cheap GPT call with a local alias fast-path.
  if (!resolvedName) {
    el('btn-text').classList.add('hidden');
    el('btn-spinner').style.display = 'inline';
    el('analyze-btn').disabled = true;

    try {
      const resp = await fetch('/resolve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query })
      });
      const resolution = await resp.json();

      if (resolution.status === 'ambiguous') {
        showDisambiguation(resolution.alternatives);
        el('btn-text').classList.remove('hidden');
        el('btn-spinner').style.display = 'none';
        el('analyze-btn').disabled = false;
        return;
      }
      if (resolution.canonical) {
        await runAnalyze(resolution.canonical, forceRefresh);
        return;
      }
    } catch (err) {
      // Fall through to direct analysis
    } finally {
      el('btn-text').classList.remove('hidden');
      el('btn-spinner').style.display = 'none';
      el('analyze-btn').disabled = false;
    }
  }

  // Normalize capitalization (openai → OpenAI via alias, otherwise Title Case)
  // This fallback only runs if /resolve itself fails (network error etc.)
  await runAnalyze(query.split(' ').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' '), forceRefresh);
}

function showDidYouMean(suggestions) {
  // Filter out names we already tried — prevents infinite loops
  const untried = suggestions.filter(s => !triedNames.has(s.toLowerCase()));

  const wrap = el('did-you-mean');

  if (!untried.length) {
    // Dead end — all suggestions already tried, be honest about data limits
    wrap.innerHTML =
      `<span style="font-size:0.85rem;color:#333;line-height:1.5">
        No job postings found for any variation of this company name.
        Our data source (JSearch) works best with US and European tech companies
        that post heavily on LinkedIn and Indeed. This company may not have postings
        indexed — try a major tech company like <strong>Stripe</strong>,
        <strong>Anthropic</strong>, or <strong>Salesforce</strong>.
      </span>`;
    wrap.classList.remove('hidden');
    return;
  }

  wrap.innerHTML =
    '<span style="font-size:0.85rem;font-weight:500;color:#333">Did you mean: </span>' +
    untried.map(s =>
      `<button onclick="pickCompany('${s.replace(/'/g, "\\'")}')"
        style="background:var(--black);color:var(--lime);border:none;border-radius:var(--pill);
               padding:5px 14px;font-family:Inter,sans-serif;font-size:0.85rem;font-weight:700;
               cursor:pointer;margin:2px">${escHtml(s)}</button>`
    ).join('');
  wrap.classList.remove('hidden');
}

function showDisambiguation(alternatives) {
  el('btn-text').classList.remove('hidden');
  el('btn-spinner').style.display = 'none';
  el('analyze-btn').disabled = false;

  const container = el('disambig-options');
  container.innerHTML = alternatives.map(alt => `
    <button onclick="pickCompany('${alt.name.replace(/'/g, "\\'")}')"
      style="background:#12141e;border:1px solid #3d4166;color:#e2e8f0;border-radius:8px;
             padding:8px 14px;cursor:pointer;text-align:left"
      onmouseover="this.style.borderColor='#7c86ff'"
      onmouseout="this.style.borderColor='#3d4166'">
      <div style="font-weight:600;font-size:0.9rem">${escHtml(alt.name)}</div>
      <div style="font-size:0.75rem;color:#6b7280">${escHtml(alt.description || '')}</div>
    </button>`).join('');

  show('disambig-panel');
}

function pickCompany(name) {
  el('company-input').value = name;
  hide('disambig-panel');
  runAnalysis(name, false);
}

/* ── Step 2: Run actual analysis with a confirmed company name ── */
async function runAnalyze(company, forceRefresh) {
  el('btn-text').classList.add('hidden');
  el('btn-spinner').style.display = 'inline';
  el('analyze-btn').disabled = true;
  startLoadingSteps(company);

  /* If server is cold-starting, show a friendly note after 8s */
  const wakeTimer = setTimeout(() => {
    const detail = document.querySelector('#lstep-0 .step-detail');
    if (detail) detail.textContent = 'Server is waking up on Render — usually takes 30–60s on first visit…';
  }, 8000);

  try {
    const resp = await fetch('/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ company, force_refresh: forceRefresh })
    });
    const data = await resp.json();

    clearTimeout(wakeTimer);

    if (!resp.ok) {
      stopLoadingSteps();
      showError(data.error || 'Something went wrong.');
      if (data.suggestions && data.suggestions.length) showDidYouMean(data.suggestions);
      return;
    }

    // Cache hit — result is returned immediately
    if (data.company) {
      finishAnalysis(company, data);
      return;
    }

    // Fresh fetch — server started a background job, poll until done
    if (data.job_id) {
      await pollStatus(data.job_id, company);
    }

  } catch (err) {
    clearTimeout(wakeTimer);
    stopLoadingSteps();
    showError('Network error. Make sure the Flask server is running.');
  } finally {
    el('btn-text').classList.remove('hidden');
    el('btn-spinner').style.display = 'none';
    el('analyze-btn').disabled = false;
  }
}

/* Poll /status/<job_id> every 2 seconds until done, with a 5-minute timeout */
async function pollStatus(jobId, company) {
  const TIMEOUT_MS = 5 * 60 * 1000; // 5 minutes
  const started = Date.now();

  while (true) {
    await new Promise(r => setTimeout(r, 2000));

    if (Date.now() - started > TIMEOUT_MS) {
      stopLoadingSteps();
      showError('Analysis is taking longer than expected. Please try again.');
      return;
    }

    let statusData;
    try {
      const resp = await fetch(`/status/${jobId}`);
      statusData = await resp.json();
    } catch (err) {
      stopLoadingSteps();
      showError('Network error while waiting for results.');
      return;
    }

    if (statusData.status === 'done') {
      finishAnalysis(company, statusData);
      return;
    }

    if (statusData.status === 'error') {
      stopLoadingSteps();
      showError(statusData.error || 'Something went wrong.');
      if (statusData.suggestions && statusData.suggestions.length) {
        showDidYouMean(statusData.suggestions);
      }
      return;
    }

    // status === 'running' — keep polling
  }
}

function scrollToChat() {
  el('chat-input').focus();
}

async function finishAnalysis(company, data) {
  triedNames.add(company.toLowerCase());
  stopLoadingSteps();
  currentCompany = company;
  currentSourceStatus = data.source_status || null;
  currentJobCount = data.job_count || 0;
  chatHistory = [];

  await renderResults(data);
  show('results-section');
  show('deep-scan-btn');
  el('chat-window').innerHTML = '';
  el('chat-company-name').textContent = company;
  el('chat-chip-company').textContent = company;
  el('chat-context-copy').textContent = `Grounded first in ${data.job_count} analyzed roles${currentSourceStatus?.doc_count ? `, then in ${currentSourceStatus.doc_count} official sources` : ''} for ${company}.`;

  const sourceMessage = currentSourceStatus?.mode === 'mixed_sources'
    ? 'I also pulled in official company materials to corroborate or refine the hiring read.'
    : 'This run is grounded in hiring signals only.';
  const sourceCountText = currentSourceStatus?.doc_count
    ? ` and **${currentSourceStatus.doc_count} official source documents**`
    : '';

  appendBotMessage(
    `Analyzed **${data.job_count} job postings**${sourceCountText} for **${company}**. ` +
    `Found signals across ${data.trends.domain_distribution.length} strategic domains. ` +
    `${sourceMessage} Ask me anything about what the hiring footprint suggests they are prioritizing.`,
    []
  );

  renderSuggestedQuestions(company);

  /* ── Update URL so back-navigation restores this search ── */
  const shareUrl = new URL(window.location);
  shareUrl.searchParams.set('q', company);
  history.pushState({ company }, '', shareUrl.toString());

  /* ── Update and show share bar ── */
  el('share-company-name').textContent = company;
  show('share-bar');

  /* ── Scroll: restore saved position or scroll to results ── */
  const savedScroll = sessionStorage.getItem('rbth_scroll_' + company.toLowerCase());
  if (savedScroll) {
    setTimeout(() => window.scrollTo(0, parseInt(savedScroll, 10)), 450);
  } else {
    setTimeout(() => el('results-section').scrollIntoView({ behavior: 'smooth', block: 'start' }), 200);
  }
}

function renderSuggestedQuestions(company) {
  const win = el('chat-window');
  const chips = [
    `What is ${company} most likely building in the next 2–4 quarters?`,
    `What do the hiring patterns say matters most at ${company}?`,
    `What technical and product capabilities is ${company} hiring for most aggressively?`,
    currentSourceStatus?.mode === 'mixed_sources'
      ? `Where do the official sources reinforce the hiring signal?`
      : `How is ${company} approaching enterprise sales?`,
  ];

  const wrap = document.createElement('div');
  wrap.className = 'suggested-qs';
  chips.forEach(q => {
    const btn = document.createElement('button');
    btn.className = 'sq-chip';
    btn.textContent = q;
    btn.onclick = () => {
      el('chat-input').value = q;
      wrap.remove();
      sendChat();
    };
    wrap.appendChild(btn);
  });
  win.appendChild(wrap);
  win.scrollTop = win.scrollHeight;
}

/* ── Source Provenance Banner ── */
function renderSourceProvenance(sourceCounts, jobCount) {
  const copyEl = el('source-provenance-copy');
  if (!copyEl) return;

  const SOURCE_META = {
    job:                    { icon: 'bi-briefcase-fill',     label: 'Job postings' },
    earnings_call_transcript:{ icon: 'bi-mic-fill',          label: 'Earnings calls' },
    shareholder_letter:     { icon: 'bi-envelope-open-fill', label: 'Shareholder letters' },
    investor_day:           { icon: 'bi-calendar-event-fill',label: 'Investor day' },
    quarterly_filing:       { icon: 'bi-file-earmark-text-fill', label: 'Quarterly filings' },
    earnings_release:       { icon: 'bi-graph-up-arrow',     label: 'Earnings releases' },
    sec_form_d:             { icon: 'bi-bank',               label: 'SEC Form D' },
    arxiv_paper:            { icon: 'bi-journal-text',       label: 'arXiv papers' },
    patent:                 { icon: 'bi-award-fill',         label: 'USPTO patents' },
    github_release:         { icon: 'bi-github',             label: 'GitHub releases' },
    changelog:              { icon: 'bi-clock-history',      label: 'Release notes' },
    pricing_page:           { icon: 'bi-tag-fill',           label: 'Pricing page' },
    product_doc:            { icon: 'bi-book-fill',          label: 'Product docs' },
    newsroom_post:          { icon: 'bi-newspaper',          label: 'Newsroom' },
    customer_story:         { icon: 'bi-chat-quote-fill',    label: 'Customer stories' },
    partner_page:           { icon: 'bi-diagram-2-fill',     label: 'Partner pages' },
  };

  const counts = Object.assign({}, sourceCounts || {});
  if (jobCount > 0) counts['job'] = (counts['job'] || 0) + jobCount;

  // Sort: jobs first, then by count desc
  const entries = Object.entries(counts)
    .filter(([, n]) => n > 0)
    .sort(([a], [b]) => {
      if (a === 'job') return -1;
      if (b === 'job') return 1;
      return counts[b] - counts[a];
    });

  if (!entries.length) return;

  const chips = entries.map(([type, count]) => {
    const meta = SOURCE_META[type] || { icon: 'bi-file-earmark', label: type.replace(/_/g, ' ') };
    const countLabel = type === 'job' ? `${count} roles` : `${count} doc${count !== 1 ? 's' : ''}`;
    return `<span class="source-chip"><i class="bi ${meta.icon}"></i>${meta.label} <span style="opacity:0.6">(${countLabel})</span></span>`;
  }).join('');

  const hasOfficialSources = entries.some(([t]) => t !== 'job');
  const intro = hasOfficialSources
    ? '<strong>Sources used for this analysis:</strong>'
    : '<strong>Hiring data is the primary signal.</strong> No official company documents were found for this company.';

  copyEl.innerHTML = `${intro}<div class="source-chips">${chips}</div>`;
}

/* ── Render Results ── */
async function renderResults(data) {
  const { trends, insights } = data;
  currentSourceStatus = data.source_status || null;

  el('stat-jobs').textContent = data.job_count;
  el('stat-sources').textContent = currentSourceStatus?.doc_count || 0;
  el('stat-domains').textContent = trends.domain_distribution.length;
  el('stat-insights').textContent = insights.length;

  el('cache-badge').classList.add('hidden');

  let chartsAvailable = true;
  try {
    await loadChartJs();
  } catch (err) {
    chartsAvailable = false;
    console.error('Chart.js failed to load', err);
  }

  renderSourceProvenance(currentSourceStatus?.source_counts || {}, data.job_count);
  renderDomains(trends.domain_distribution, trends.tagged_jobs || 0, data.job_count);
  renderInsights(insights);
  renderSkills(trends.top_skills);
  if (chartsAvailable) {
    renderSourceMix(currentSourceStatus?.source_counts || {}, data.job_count);
    renderSeniorityChart(trends.seniority_distribution);
  }

  const note = el('analysis-source-note');
  if (currentSourceStatus && currentSourceStatus.message) {
    note.textContent = currentSourceStatus.message;
    note.classList.remove('hidden');
  } else {
    note.textContent = '';
    note.classList.add('hidden');
  }

  if (!chartsAvailable) {
    showChartFallback('source-mix-chart', 'Chart preview unavailable right now, but the analysis results loaded successfully.');
    showChartFallback('seniority-chart', 'Seniority chart unavailable right now, but the analysis results loaded successfully.');
  }
}

function showChartFallback(canvasId, message) {
  const canvas = el(canvasId);
  if (!canvas) return;
  canvas.style.display = 'none';
  canvas.parentNode.querySelectorAll('.chart-load-fallback').forEach(n => n.remove());

  const msg = document.createElement('p');
  msg.className = 'chart-load-fallback';
  msg.style.cssText = 'font-size:0.82rem;color:var(--text-3);margin-top:8px';
  msg.textContent = message;
  canvas.parentNode.appendChild(msg);
}

function renderSourceMix(sourceCounts, totalJobs) {
  const ctx = el('source-mix-chart').getContext('2d');
  if (sourceMixChart) sourceMixChart.destroy();
  ctx.canvas.parentNode.querySelectorAll('.source-mix-fallback').forEach(n => n.remove());

  const entries = Object.entries(sourceCounts || {});
  const combinedEntries = totalJobs ? [['job', totalJobs], ...entries] : entries;
  if (!combinedEntries.length) {
    ctx.canvas.style.display = 'none';
    const msg = document.createElement('p');
    msg.className = 'source-mix-fallback';
    msg.style.cssText = 'font-size:0.82rem;color:var(--text-3);margin-top:8px';
    msg.textContent = 'No signal mix data is available for this run.';
    ctx.canvas.parentNode.appendChild(msg);
    return;
  }
  ctx.canvas.style.display = '';

  const palette = ['#111111', '#C5F135', '#8F8F8F', '#D8D0C3', '#5B5B5B', '#9FB4C9'];
  sourceMixChart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: combinedEntries.map(([key]) => prettySourceType(key)),
      datasets: [{
        data: combinedEntries.map(([, count]) => count),
        backgroundColor: combinedEntries.map((_, i) => palette[i % palette.length]),
        borderWidth: 2,
        borderColor: '#FFFFFF'
      }]
    },
    options: {
      plugins: {
        legend: { position: 'right', labels: { color: '#555', font: { size: 11 }, padding: 10 } }
      }
    }
  });
}

function renderDomains(domains, taggedJobs, totalJobs) {
  const note = el('domains-coverage-note');
  if (note) {
    const tagged = taggedJobs || 0;
    const total = totalJobs || 0;
    if (tagged > 0 && total > 0) {
      note.textContent = `${tagged} of ${total} analyzed jobs mapped into the current strategy taxonomy. Domain percentages below are based on tagged jobs, not all fetched jobs.`;
      note.classList.remove('hidden');
    } else if (total > 0) {
      note.textContent = `None of the ${total} analyzed jobs mapped cleanly into the current strategy taxonomy yet.`;
      note.classList.remove('hidden');
    } else {
      note.textContent = '';
      note.classList.add('hidden');
    }
  }

  if (!domains || !domains.length) {
    el('domains-pills').innerHTML = '<p style="color:var(--text-3);font-size:0.9rem">No jobs mapped cleanly into the current strategy domains for this run.</p>';
    return;
  }
  const max = Math.max(...domains.map(d => d.count));
  el('domains-pills').innerHTML = domains.map(d => `
    <div class="domain-pill">
      <div class="domain-pill-name">${escHtml(d.domain.replace(/_/g, ' '))}</div>
      <div class="domain-pill-count">${Math.max(1, Math.round((d.count / Math.max(taggedJobs || 1, 1)) * 100))}<span class="domain-pill-unit">%</span></div>
      <div class="domain-pill-sub">${d.count} tagged hiring roles</div>
      <div class="domain-pill-bar"><div class="domain-pill-fill" style="width:${Math.round((d.count/max)*100)}%"></div></div>
    </div>`).join('');
}

function renderSkills(skills) {
  if (!skills || !skills.length) {
    el('skills-list').innerHTML = '<p class="text-muted small">No skills data.</p>';
    return;
  }
  const max = skills[0].count;
  el('skills-list').innerHTML = skills.slice(0, 12).map(s => `
    <div class="skill-row">
      <div class="skill-meta"><span>${escHtml(s.skill)}</span><span>${s.count}</span></div>
      <div class="skill-track"><div class="skill-fill" style="width:${Math.round((s.count/max)*100)}%"></div></div>
    </div>`).join('');
}

function renderSeniorityChart(seniority) {
  const ctx = el('seniority-chart').getContext('2d');
  if (seniorityChart) seniorityChart.destroy();
  // Clear any previous fallback messages
  ctx.canvas.parentNode.querySelectorAll('.seniority-fallback').forEach(n => n.remove());
  if (!seniority || !seniority.length) {
    ctx.canvas.style.display = 'none';
    const msg = document.createElement('p');
    msg.className = 'seniority-fallback';
    msg.style.cssText = 'font-size:0.82rem;color:var(--text-3);margin-top:8px';
    msg.textContent = 'Seniority data unavailable. Try a fresh fetch to reanalyse.';
    ctx.canvas.parentNode.appendChild(msg);
    return;
  }
  ctx.canvas.style.display = '';

  const palette = ['#0A0A0A','#C5F135','#555555','#AAAAAA','#E2DDD4','#333','#888'];
  seniorityChart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: seniority.map(s => s.level),
      datasets: [{
        data: seniority.map(s => s.count),
        backgroundColor: seniority.map((_, i) => palette[i % palette.length]),
        borderWidth: 2,
        borderColor: '#FFFFFF'
      }]
    },
    options: {
      plugins: {
        legend: { position: 'right', labels: { color: '#555', font: { size: 11 }, padding: 10 } }
      }
    }
  });
}

function parseInsight(text) {
  const initMatch  = text.match(/\*\*Strategic Initiative:\*\*\s*([^\n]+)/);
  const confMatch  = text.match(/\*\*Confidence:\*\*\s*(HIGH|MEDIUM|LOW)/i);
  const soWhatMatch = text.match(/\*\*So What:\*\*\s*([\s\S]+?)(?:\n\n|\n\*\*|$)/);
  const evBlock    = text.match(/\*\*Evidence Chain:\*\*([\s\S]+?)\*\*Confidence:/);
  const citations  = evBlock
    ? (evBlock[1].match(/^- .+$/gm) || []).map(l => l.replace(/^- /, '').trim())
    : [];
  return {
    initiative: initMatch  ? initMatch[1].trim()  : '',
    confidence: confMatch  ? confMatch[1].toUpperCase() : 'MEDIUM',
    soWhat:     soWhatMatch ? soWhatMatch[1].trim() : '',
    citations
  };
}

function toggleCitations(btn) {
  const list = btn.nextElementSibling;
  const opening = list.classList.contains('hidden');
  list.classList.toggle('hidden');
  btn.querySelector('i').className = opening ? 'bi bi-chevron-up' : 'bi bi-chevron-down';
  const n = list.children.length;
  btn.querySelector('.toggle-label').textContent = opening
    ? 'Hide supporting sources'
    : `${n} supporting source${n !== 1 ? 's' : ''}`;
}


function prettySourceType(sourceType) {
  const labels = {
    job: 'Job posting (primary)',
    quarterly_filing: 'Quarterly filing',
    earnings_release: 'Earnings release',
    earnings_call_transcript: 'Earnings call transcript',
    shareholder_letter: 'Shareholder letter',
    investor_day: 'Investor day',
    pricing_page: 'Pricing page',
    product_doc: 'Product doc',
    customer_story: 'Customer story',
    partner_page: 'Partner page',
    newsroom_post: 'Newsroom post',
    changelog: 'Release notes',
    github_release: 'GitHub release',
    sec_form_d: 'SEC Form D (private placement)',
    arxiv_paper: 'Research paper (arXiv)',
    patent: 'USPTO Patent',
  };
  return labels[sourceType] || sourceType || 'Source';
}

function getInsightSourceTone(evidence) {
  const types = [...new Set((evidence || []).map(e => e.source_type || 'job'))];
  if (!types.length || (types.length === 1 && types[0] === 'job')) {
    return { label: 'Hiring Signal', style: 'background:#EEF1F4;color:#2E3A46' };
  }
  if (types.includes('job')) {
    return { label: 'Hiring-Led Synthesis', style: 'background:#E9F8BF;color:#243300' };
  }
  if (types.length > 1) {
    return { label: 'Official Synthesis', style: 'background:#ECE8FF;color:#4B3FA8' };
  }

  const labels = {
    quarterly_filing: { label: 'Filing Signal', style: 'background:#E8F1FF;color:#2953A6' },
    earnings_release: { label: 'Earnings Release', style: 'background:#FFF1E7;color:#A6531B' },
    earnings_call_transcript: { label: 'Investor Call', style: 'background:#EAFBF0;color:#1E7A46' },
    newsroom_post: { label: 'Newsroom Signal', style: 'background:#F4F0EA;color:#7A5A2A' },
    changelog: { label: 'Release Notes', style: 'background:#FFF9E7;color:#8A6A00' },
    github_release: { label: 'GitHub Signal', style: 'background:#EFEAFB;color:#5B3C9D' },
    sec_form_d: { label: 'Funding Signal', style: 'background:#FFF0FB;color:#8A1A6A' },
    arxiv_paper: { label: 'Research Signal', style: 'background:#F0F7FF;color:#1A4A8A' },
    patent: { label: 'Patent Signal', style: 'background:#F0FFF4;color:#1A6A3A' },
  };
  return labels[types[0]] || { label: 'Official Signal', style: 'background:#ECE8FF;color:#4B3FA8' };
}

function renderInsights(insights) {
  currentInsights = insights || [];
  currentFeaturedInsight = chooseFeaturedInsight(insights || []);
  renderFeaturedInsight(currentFeaturedInsight);
  const container = el('insights-list');
  if (!insights || !insights.length) {
    container.innerHTML = '<p style="color:var(--text-3);font-size:0.9rem">Not enough data to generate insights. Try a larger company.</p>';
    return;
  }
  const supportingInsights = insights.filter(ins => ins !== currentFeaturedInsight);
  if (!supportingInsights.length) {
    container.innerHTML = '';
    return;
  }
  container.innerHTML = supportingInsights.map((ins, i) => {
    const insightIndex = currentInsights.indexOf(ins);
    const { initiative, confidence, soWhat, citations } = parseInsight(ins.insight_text);
    const domain  = ins.domain.replace(/_/g, ' ');
    const title   = initiative || domain.toUpperCase();
    const summary = soWhat    || ins.insight_text;
    const evidence = Array.isArray(ins.evidence) ? ins.evidence : [];
    const displayEvidence = evidence.length
      ? evidence
      : citations.map(c => ({ title: c, label: c, source_type: 'job' }));
    const sourceTone = getInsightSourceTone(displayEvidence);
    const n = displayEvidence.length;
    return `
    <div class="insight-card-v2">
      <div class="insight-card-top">
        <div class="insight-main">
          <div class="insight-domain-meta"><i class="bi bi-diagram-3"></i>${escHtml(domain)}</div>
          <div style="margin-top:10px"><span class="confidence-badge" style="font-size:0.74rem;${sourceTone.style}">${escHtml(sourceTone.label)}</span></div>
          <div class="insight-initiative">${escHtml(title)}</div>
          <div class="insight-so-what">${renderMarkdown(escHtml(summary))}</div>
        </div>
        <div class="insight-aside">
          <span class="confidence-badge conf-${confidence}">${confidence}</span>
          <button class="btn-copy-inline" onclick="copyInsight(${insightIndex})" title="Copy insight"><i class="bi bi-copy"></i></button>
        </div>
      </div>
      ${n ? `
      <div class="insight-citations">
        <button class="citations-toggle" onclick="toggleCitations(this)">
          <i class="bi bi-chevron-down"></i>
          <span class="toggle-label">${n} supporting source${n !== 1 ? 's' : ''}</span>
        </button>
        <ul class="citations-list hidden">
          ${displayEvidence.map(item => {
            const label = item.label || item.title || '';
            if ((item.source_type || 'job') !== 'job') {
              const sourceLabel = `${prettySourceType(item.source_type)}${item.period ? ' • ' + item.period : ''}`;
              const content = `${label}${sourceLabel ? ' — ' + sourceLabel : ''}`;
              return item.url
                ? `<li><i class="bi bi-file-earmark-text"></i><a href="${escHtml(item.url)}" target="_blank" class="citation-link">${escHtml(content)} <i class="bi bi-box-arrow-up-right" style="font-size:0.6rem;opacity:0.5"></i></a></li>`
                : `<li><i class="bi bi-file-earmark-text"></i><span class="citation-link" style="cursor:default">${escHtml(content)}</span></li>`;
            }
            const jobUrl = safeJobUrl(item.url || '', item.label || item.title || '');
            return jobUrl
              ? `<li><i class="bi bi-person-badge"></i><a href="${escHtml(jobUrl)}" target="_blank" class="citation-link">${escHtml(label)} <i class="bi bi-box-arrow-up-right" style="font-size:0.6rem;opacity:0.5"></i></a></li>`
              : `<li><i class="bi bi-person-badge"></i><span class="citation-link" style="cursor:default">${escHtml(label)}</span></li>`;
          }).join('')}
        </ul>
      </div>` : ''}
    </div>`;
  }).join('');
}

function chooseFeaturedInsight(insights) {
  if (!insights || !insights.length) return null;

  const strategic = insights.find(ins => ins.domain === 'strategic_readout');
  if (strategic) {
    const evidenceTypes = new Set((strategic.evidence || []).map(e => e.source_type || 'job'));
    const hasJobs = evidenceTypes.has('job');
    const hasStrongOfficial = [...evidenceTypes].some(type =>
      type !== 'job' && !['github_release', 'changelog', 'newsroom_post'].includes(type)
    );
    if (hasJobs || hasStrongOfficial) return strategic;
  }

  const strongestHiring = insights.find(ins => !['official_signals', 'strategic_readout'].includes(ins.domain));
  return strongestHiring || strategic || insights[0];
}

function renderFeaturedInsight(insight) {
  const container = el('featured-insight');
  if (!container) return;
  if (!insight) {
    container.innerHTML = '';
    return;
  }

  const { initiative, confidence, soWhat, citations } = parseInsight(insight.insight_text);
  const domain = insight.domain.replace(/_/g, ' ');
  const title = initiative || domain.toUpperCase();
  const summary = soWhat || insight.insight_text;
  const evidence = Array.isArray(insight.evidence) ? insight.evidence : [];
  const displayEvidence = evidence.length
    ? evidence
    : citations.map(c => ({ title: c, label: c, source_type: 'job' }));
  const sourceTone = getInsightSourceTone(displayEvidence);
  const n = displayEvidence.length;

  container.innerHTML = `
    <div class="featured-insight-card">
      <div class="featured-top">
        <div>
          <div class="featured-kicker"><i class="bi bi-stars"></i>${escHtml(domain)}</div>
          <div style="margin-top:10px"><span class="confidence-badge" style="font-size:0.74rem;${sourceTone.style}">${escHtml(sourceTone.label)}</span></div>
        </div>
        <div class="featured-meta">
          <span class="confidence-badge conf-${confidence}">${confidence}</span>
          <button class="btn-copy-inline" onclick="copyFeaturedInsight()" title="Copy insight"><i class="bi bi-copy"></i></button>
        </div>
      </div>
      <div class="featured-title">${escHtml(title)}</div>
      <div class="featured-summary">${renderMarkdown(escHtml(summary))}</div>
      ${n ? `
      <div class="insight-citations" style="margin-top:14px">
        <button class="citations-toggle" onclick="toggleCitations(this)">
          <i class="bi bi-chevron-down"></i>
          <span class="toggle-label">${n} supporting source${n !== 1 ? 's' : ''}</span>
        </button>
        <ul class="citations-list hidden">
          ${displayEvidence.map(item => {
            const label = item.label || item.title || '';
            if ((item.source_type || 'job') !== 'job') {
              const sourceLabel = `${prettySourceType(item.source_type)}${item.period ? ' • ' + item.period : ''}`;
              const content = `${label}${sourceLabel ? ' — ' + sourceLabel : ''}`;
              return item.url
                ? `<li><i class="bi bi-file-earmark-text"></i><a href="${escHtml(item.url)}" target="_blank" class="citation-link">${escHtml(content)} <i class="bi bi-box-arrow-up-right" style="font-size:0.6rem;opacity:0.5"></i></a></li>`
                : `<li><i class="bi bi-file-earmark-text"></i><span class="citation-link" style="cursor:default">${escHtml(content)}</span></li>`;
            }
            const jobUrl = safeJobUrl(item.url || '', item.label || item.title || '');
            return jobUrl
              ? `<li><i class="bi bi-person-badge"></i><a href="${escHtml(jobUrl)}" target="_blank" class="citation-link">${escHtml(label)} <i class="bi bi-box-arrow-up-right" style="font-size:0.6rem;opacity:0.5"></i></a></li>`
              : `<li><i class="bi bi-person-badge"></i><span class="citation-link" style="cursor:default">${escHtml(label)}</span></li>`;
          }).join('')}
        </ul>
      </div>` : ''}
    </div>`;
}

/* ── Chat ── */
async function sendChat() {
  const input = el('chat-input');
  const question = input.value.trim();
  if (!question) return;

  input.value = '';
  appendUserMessage(question);
  chatHistory.push({ role: 'user', content: question });

  const typingId = appendTypingIndicator();

  try {
    const resp = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, company: currentCompany, history: chatHistory })
    });
    const data = await resp.json();
    removeTypingIndicator(typingId);

    const answer = data.answer || 'Sorry, I could not generate an answer.';
    appendBotMessage(answer, data.evidence || []);
    chatHistory.push({ role: 'assistant', content: answer });
  } catch (err) {
    removeTypingIndicator(typingId);
    appendBotMessage('Network error. Please try again.', []);
  }
}

function appendUserMessage(text) {
  const win = el('chat-window');
  const row = document.createElement('div');
  row.className = 'msg-row msg-row-user';
  const meta = document.createElement('div');
  meta.className = 'msg-meta';
  meta.textContent = 'You';
  const div = document.createElement('div');
  div.className = 'msg-bubble msg-user';
  div.textContent = text;
  row.appendChild(meta);
  row.appendChild(div);
  win.appendChild(row);
  win.scrollTop = win.scrollHeight;
}

function appendBotMessage(text, evidence) {
  const win = el('chat-window');
  const row = document.createElement('div');
  row.className = 'msg-row msg-row-bot';
  const meta = document.createElement('div');
  meta.className = 'msg-meta';
  meta.textContent = `${currentCompany || 'Company'} signal analyst`;
  const div = document.createElement('div');
  div.className = 'msg-bubble msg-bot';

  const textDiv = document.createElement('div');
  textDiv.innerHTML = renderMarkdown(text);
  div.appendChild(textDiv);

  if (evidence && evidence.length) {
    const evDiv = document.createElement('div');
    evDiv.className = 'evidence-block';
    evDiv.innerHTML =
      '<div style="font-size:0.75rem;color:#6b7280;margin-bottom:4px;text-transform:uppercase;letter-spacing:1px">Evidence</div>' +
      evidence.map(e => {
        const sourceLabel = prettySourceType(e.source_type || 'job');
        const period = e.period ? ` • ${escHtml(e.period)}` : '';
        const label = `<i class="bi bi-file-earmark-text me-1"></i>${escHtml(e.title)} — ${escHtml(sourceLabel)}${period}`;
        return e.url
          ? `<a href="${escHtml(safeJobUrl(e.url, e.title))}" target="_blank" class="evidence-link">${label} <i class="bi bi-box-arrow-up-right" style="font-size:0.65rem"></i></a>`
          : `<span class="evidence-link" style="cursor:default">${label}</span>`;
      }).join('');
    div.appendChild(evDiv);
  }

  /* Copy button */
  const copyBtn = document.createElement('button');
  copyBtn.className = 'btn-copy-inline msg-copy-btn';
  copyBtn.innerHTML = '<i class="bi bi-copy"></i> Copy';
  copyBtn.title = 'Copy this message';
  copyBtn.onclick = () => {
    const shareUrl = currentCompany ? getShareUrl(currentCompany) : window.location.href;
    const shareText = currentCompany
      ? `${text}\n\n— ${currentCompany} hiring analysis: ${shareUrl}`
      : text;
    copyToClipboard(shareText, 'Message copied!');
  };
  div.appendChild(copyBtn);

  row.appendChild(meta);
  row.appendChild(div);
  win.appendChild(row);
  win.scrollTop = win.scrollHeight;
}

function appendTypingIndicator() {
  const win = el('chat-window');
  const id = 'typing-' + Date.now();
  const row = document.createElement('div');
  row.className = 'msg-row msg-row-bot';
  row.id = id;
  const meta = document.createElement('div');
  meta.className = 'msg-meta';
  meta.textContent = `${currentCompany || 'Company'} signal analyst`;
  const div = document.createElement('div');
  div.className = 'msg-bubble msg-bot typing-indicator';
  div.innerHTML = '<span></span><span></span><span></span>';
  row.appendChild(meta);
  row.appendChild(div);
  win.appendChild(row);
  win.scrollTop = win.scrollHeight;
  return id;
}

function removeTypingIndicator(id) {
  const e = document.getElementById(id);
  if (e) e.remove();
}

/* ── Utilities ── */
function escHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// Adzuna redirect_url links are click-tracking URLs that trigger bot detection
// when accessed from third-party apps. Replace them with a Google Jobs search.
function safeJobUrl(url, title) {
  if (!url || !url.includes('adzuna.com')) return url;
  const q = encodeURIComponent((title || '') + (currentCompany ? ' ' + currentCompany : '') + ' jobs');
  return `https://www.google.com/search?q=${q}&ibp=htl;jobs`;
}

function renderMarkdown(text) {
  return text
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>');
}

/* ── Scroll position persistence ── */
let _scrollSaveTimer = null;
window.addEventListener('scroll', () => {
  if (!currentCompany) return;
  clearTimeout(_scrollSaveTimer);
  _scrollSaveTimer = setTimeout(() => {
    sessionStorage.setItem('rbth_scroll_' + currentCompany.toLowerCase(), String(window.scrollY));
  }, 200);
});

/* Restore scroll when page is restored from bfcache (mobile back/forward) */
window.addEventListener('pageshow', (e) => {
  if (e.persisted && currentCompany) {
    const saved = sessionStorage.getItem('rbth_scroll_' + currentCompany.toLowerCase());
    if (saved) setTimeout(() => window.scrollTo(0, parseInt(saved, 10)), 100);
  }
});

/* Restore state from URL on page load + keepalive ping */
document.addEventListener('DOMContentLoaded', () => {
  const params = new URLSearchParams(window.location.search);
  const q = params.get('q');
  if (q) {
    el('company-input').value = q;
    runAnalysis(q, false);
  }

  /* Ping every 8 minutes to prevent Render cold starts */
  const ping = () => fetch('/ping').catch(() => {});
  ping();
  setInterval(ping, 8 * 60 * 1000);
});

/* ── Social sharing ── */
function getShareUrl(company) {
  return window.location.origin + window.location.pathname + '?q=' + encodeURIComponent(company);
}

function trackShare(platform) {
  fetch('/track/share', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ platform, company: currentCompany || '' })
  }).catch(() => {});
}

function shareTwitter() {
  if (!currentCompany) return;
  trackShare('twitter');
  const url = getShareUrl(currentCompany);
  const text = `🔍 I analyzed ${currentCompany}'s hiring data and uncovered their product strategy — before they've announced it.\n\nPowered by AI · Read Between The Hires`;
  window.open(
    `https://twitter.com/intent/tweet?text=${encodeURIComponent(text)}&url=${encodeURIComponent(url)}`,
    '_blank'
  );
}

function shareLinkedIn() {
  if (!currentCompany) return;
  trackShare('linkedin');
  const url = getShareUrl(currentCompany);
  window.open(
    `https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(url)}`,
    '_blank'
  );
}

function copyShareLink() {
  if (!currentCompany) return;
  trackShare('copy_link');
  copyToClipboard(getShareUrl(currentCompany), 'Link copied!');
}

function copyInsight(i) {
  const ins = currentInsights[i];
  if (!ins) return;
  const url = getShareUrl(currentCompany);
  const message =
    `${ins.domain.replace(/_/g, ' ').toUpperCase()}\n\n${ins.insight_text}\n\n` +
    `— ${currentCompany} hiring analysis · Read Between The Hires\n${url}`;
  copyToClipboard(message, 'Insight copied!');
}

function copyFeaturedInsight() {
  if (!currentFeaturedInsight) return;
  const idx = currentInsights.indexOf(currentFeaturedInsight);
  if (idx >= 0) {
    copyInsight(idx);
  }
}

function copyToClipboard(text, successMsg) {
  const done = () => showToast(successMsg || 'Copied!');
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(done).catch(() => fallbackCopy(text, done));
  } else {
    fallbackCopy(text, done);
  }
}

function fallbackCopy(text, done) {
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.cssText = 'position:fixed;opacity:0;top:0;left:0';
  document.body.appendChild(ta);
  ta.select();
  try { document.execCommand('copy'); done(); } catch (_) {}
  document.body.removeChild(ta);
}

let _toastTimer = null;
function showToast(msg) {
  const toast = el('copy-toast');
  toast.textContent = msg;
  toast.classList.add('show');
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => toast.classList.remove('show'), 2200);
}
