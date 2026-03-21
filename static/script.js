/* ── State ── */
let currentCompany = null;
let chatHistory = [];
let domainChart = null;
let seniorityChart = null;
let loadingTimers = [];

/* ── Loading progress ── */
const LOAD_STEPS = [
  { icon: 'bi-search',         label: 'Fetching job postings',       detail: 'Searching across LinkedIn, Indeed, Glassdoor…',  delay: 0    },
  { icon: 'bi-cpu',            label: 'Extracting structured data',  detail: 'Reading each job for tools, metrics, team names…', delay: 6000  },
  { icon: 'bi-diagram-3',      label: 'Classifying strategy domains',detail: 'Tagging roles: mobile growth, AI infra, enterprise…', delay: 20000 },
  { icon: 'bi-lightbulb',      label: 'Generating insights',         detail: 'Reasoning like a strategy consultant…',           delay: 50000 },
  { icon: 'bi-bar-chart-line', label: 'Building trend analysis',     detail: 'Counting domains, skills, seniority levels…',     delay: 75000 },
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

  // Activate each step after its delay
  LOAD_STEPS.forEach((s, i) => {
    const t = setTimeout(() => activateStep(i), s.delay);
    loadingTimers.push(t);
  });
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
  hide('loading-panel');
  // Mark all as done cleanly
  LOAD_STEPS.forEach((_, i) => {
    const step = el(`lstep-${i}`);
    const icon = el(`lstep-icon-${i}`);
    if (step) step.className = 'load-step done';
    if (icon) { icon.innerHTML = '<i class="bi bi-check-lg"></i>'; icon.className = 'step-icon done'; }
  });
}

/* ── Helpers ── */
function show(id) { document.getElementById(id).classList.remove('hidden'); }
function hide(id) { document.getElementById(id).classList.add('hidden'); }
function el(id)   { return document.getElementById(id); }

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
  const words = query.trim().split(/\s+/);
  const isSingleShortWord = words.length === 1 && words[0].length <= 4;

  // Only call /resolve for single short ambiguous words (e.g. "dbs", "ms", "gs")
  // Multi-word queries like "DBS Bank", "open ai", "Goldman Sachs" go straight to analysis
  if (!resolvedName && isSingleShortWord) {
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
  const ALIASES = {
    'openai': 'OpenAI', 'open ai': 'OpenAI', 'anthropic': 'Anthropic',
    'deepmind': 'Google DeepMind', 'google': 'Google', 'meta': 'Meta',
    'facebook': 'Meta', 'microsoft': 'Microsoft', 'msft': 'Microsoft',
    'amazon': 'Amazon', 'apple': 'Apple', 'netflix': 'Netflix',
    'stripe': 'Stripe', 'uber': 'Uber', 'airbnb': 'Airbnb',
  };
  const canonical = ALIASES[query.toLowerCase()] ||
    query.split(' ').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');

  await runAnalyze(canonical, forceRefresh);
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

  try {
    const resp = await fetch('/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ company, force_refresh: forceRefresh })
    });
    const data = await resp.json();

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

function finishAnalysis(company, data) {
  triedNames.add(company.toLowerCase());
  stopLoadingSteps();
  currentCompany = company;
  chatHistory = [];

  renderResults(data);
  show('results-section');
  show('chat-section');
  show('deep-scan-btn');
  el('chat-window').innerHTML = '';

  const cacheNote = data.from_cache
    ? ` Results loaded from cache — <strong>0 API calls used</strong>.`
    : ` Fresh data fetched.`;

  appendBotMessage(
    `Analyzed **${data.job_count} job postings** for **${company}**.${cacheNote} ` +
    `Found signals across ${data.trends.domain_distribution.length} strategic domains. ` +
    `Ask me anything about their strategy.`,
    []
  );
}

/* ── Render Results ── */
function renderResults(data) {
  const { trends, insights } = data;

  el('stat-jobs').textContent = data.job_count;
  el('stat-domains').textContent = trends.domain_distribution.length;
  el('stat-insights').textContent = insights.length;

  // Cache badge
  if (data.from_cache) {
    el('cache-badge').classList.remove('hidden');
  } else {
    el('cache-badge').classList.add('hidden');
  }

  renderDomainChart(trends.domain_distribution);
  renderSkills(trends.top_skills);
  renderSeniorityChart(trends.seniority_distribution);
  renderInsights(insights);
}

function renderDomainChart(domains) {
  const ctx = el('domain-chart').getContext('2d');
  if (domainChart) domainChart.destroy();

  const labels = domains.map(d => d.domain);
  const values = domains.map(d => d.count);

  domainChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{ data: values, backgroundColor: '#0A0A0A', borderRadius: 6, borderSkipped: false }]
    },
    options: {
      indexAxis: 'y',
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: '#999' }, grid: { color: '#E2DDD4' } },
        y: { ticks: { color: '#111', font: { size: 11 } }, grid: { display: false } }
      }
    }
  });
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
  if (!seniority || !seniority.length) return;

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

function renderInsights(insights) {
  const container = el('insights-list');
  if (!insights || !insights.length) {
    container.innerHTML = '<p class="text-muted">Not enough data to generate insights. Try a larger company.</p>';
    return;
  }
  container.innerHTML = insights.map(ins => `
    <div class="insight-card">
      <div class="domain-tag">${escHtml(ins.domain.replace(/_/g, ' '))}</div>
      <div class="insight-text">${renderMarkdown(escHtml(ins.insight_text))}</div>
      <div class="evidence-pills">
        ${(ins.evidence || []).map(e =>
          `<span class="ev-pill"><i class="bi bi-person-badge" style="margin-right:4px"></i>${escHtml(e)}</span>`
        ).join('')}
      </div>
    </div>`).join('');
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
  const div = document.createElement('div');
  div.className = 'msg-bubble msg-user';
  div.textContent = text;
  win.appendChild(div);
  win.scrollTop = win.scrollHeight;
}

function appendBotMessage(text, evidence) {
  const win = el('chat-window');
  const div = document.createElement('div');
  div.className = 'msg-bubble msg-bot';
  div.innerHTML = renderMarkdown(text);

  if (evidence && evidence.length) {
    const evDiv = document.createElement('div');
    evDiv.className = 'evidence-block';
    evDiv.innerHTML =
      '<div style="font-size:0.75rem;color:#6b7280;margin-bottom:4px;text-transform:uppercase;letter-spacing:1px">Evidence</div>' +
      evidence.map(e => {
        const label = `<i class="bi bi-file-earmark-text me-1"></i>${escHtml(e.title)} — ${escHtml(e.company)}`;
        return e.url
          ? `<a href="${escHtml(e.url)}" target="_blank" class="evidence-link">${label} <i class="bi bi-box-arrow-up-right" style="font-size:0.65rem"></i></a>`
          : `<span class="evidence-link" style="cursor:default">${label}</span>`;
      }).join('');
    div.appendChild(evDiv);
  }

  win.appendChild(div);
  win.scrollTop = win.scrollHeight;
}

function appendTypingIndicator() {
  const win = el('chat-window');
  const id = 'typing-' + Date.now();
  const div = document.createElement('div');
  div.id = id;
  div.className = 'msg-bubble msg-bot typing-indicator';
  div.innerHTML = '<span></span><span></span><span></span>';
  win.appendChild(div);
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

function renderMarkdown(text) {
  return text
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>');
}
