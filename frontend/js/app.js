// /* ==========================================================
//    AniDub Studio — Frontend v2
//    ========================================================== */

// const API = 'http://localhost:5050/api';

// let state = {
//   apiKey:   '',
//   keyValid: false,
//   file:     null,
//   jobId:    null,
//   evtSrc:   null,
//   polling:  null,
//   lastLogCount: 0,
// };

// // ── Server Health ──────────────────────────────────────────
// async function checkServer() {
//   const dot  = document.getElementById('statusDot');
//   const text = document.getElementById('statusText');
//   try {
//     const r = await fetch(`${API}/health`, { signal: AbortSignal.timeout(3000) });
//     if (r.ok) {
//       dot.className = 'status-dot online';
//       text.textContent = 'Backend online';
//       return true;
//     }
//   } catch (_) {}
//   dot.className = 'status-dot offline';
//   text.textContent = 'Backend offline';
//   return false;
// }

// // ── API Key ────────────────────────────────────────────────
// async function validateKey() {
//   const key    = document.getElementById('apiKey').value.trim();
//   const status = document.getElementById('keyStatus');
//   const btn    = document.getElementById('btnValidate');
//   if (!key) { toast('Enter your Groq API key first', 'error'); return; }

//   state.apiKey  = key;
//   state.keyValid = false;
//   status.className = 'key-status loading';
//   status.textContent = '⏳ Verifying...';
//   btn.disabled = true;

//   try {
//     const r    = await fetch(`${API}/validate-key`, {
//       method: 'POST',
//       headers: { 'Content-Type': 'application/json' },
//       body: JSON.stringify({ api_key: key }),
//     });
//     const data = await r.json();
//     if (data.valid) {
//       state.keyValid = true;
//       status.className = 'key-status valid';
//       status.textContent = '✓ Valid — Ready to dub!';
//       toast('API key verified ✓', 'success');
//     } else {
//       status.className = 'key-status invalid';
//       status.textContent = `✗ ${data.error || 'Invalid key'}`;
//       toast(data.error || 'Invalid API key', 'error');
//     }
//   } catch (e) {
//     status.className = 'key-status invalid';
//     status.textContent = '✗ Cannot reach server — is backend running?';
//     toast('Backend not running. Start it with: python backend/app.py', 'error');
//   }

//   btn.disabled = false;
//   updateDubButton();
// }

// // ── Tab Switch ─────────────────────────────────────────────
// function switchTab(tab) {
//   const isVideo = tab === 'video';
//   document.getElementById('videoTab').style.display = isVideo ? '' : 'none';
//   document.getElementById('textTab').style.display  = isVideo ? 'none' : '';
//   document.getElementById('tabVideo').className = 'tab-btn' + (isVideo ? ' tab-active' : '');
//   document.getElementById('tabText').className  = 'tab-btn' + (!isVideo ? ' tab-active' : '');
// }

// // ── File Handling ──────────────────────────────────────────
// function handleFile(file) {
//   if (!file) return;
//   const sizeMB = file.size / (1024 * 1024);
//   state.file = file;

//   document.getElementById('fileInfo').style.display = 'flex';
//   document.getElementById('fileInfo').innerHTML = `
//     <span class="file-icon">🎬</span>
//     <div class="file-meta">
//       <div class="file-name">${escHtml(file.name)}</div>
//       <div class="file-size">${sizeMB.toFixed(1)} MB · ${file.type || 'video'}</div>
//     </div>
//     <button class="file-remove" onclick="removeFile()">✕</button>
//   `;
//   document.getElementById('dropZone').style.display = 'none';
//   updateDubButton();
// }

// function removeFile() {
//   state.file = null;
//   document.getElementById('fileInfo').style.display = 'none';
//   document.getElementById('dropZone').style.display = '';
//   document.getElementById('fileInput').value = '';
//   updateDubButton();
// }

// function setupDrop() {
//   const zone = document.getElementById('dropZone');
//   zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('drag-over'); });
//   zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
//   zone.addEventListener('drop', e => {
//     e.preventDefault();
//     zone.classList.remove('drag-over');
//     const f = e.dataTransfer.files[0];
//     if (f) handleFile(f);
//   });
//   zone.addEventListener('click', () => document.getElementById('fileInput').click());
// }

// // ── Dub Button State ───────────────────────────────────────
// function updateDubButton() {
//   const btn = document.getElementById('btnDub');
//   const sub = btn.querySelector('.btn-dub-sub');
//   const ok  = state.keyValid && !!state.file;
//   btn.disabled = !ok;
//   if (!state.keyValid && !state.file)   sub.textContent = 'Add API key & upload video to begin';
//   else if (!state.keyValid)              sub.textContent = 'Verify your Groq API key first';
//   else if (!state.file)                  sub.textContent = 'Upload a video file to begin';
//   else                                   sub.textContent = 'Click to start dubbing!';
// }

// // ── Start Dubbing ──────────────────────────────────────────
// async function startDub() {
//   if (!state.file)                    { toast('Upload a video file first', 'error'); return; }
//   if (!state.apiKey || !state.keyValid) { toast('Verify API key first', 'error'); return; }

//   const online = await checkServer();
//   if (!online) {
//     toast('Backend not running. Run: python backend/app.py', 'error');
//     return;
//   }

//   const fd = new FormData();
//   fd.append('video',           state.file);
//   fd.append('api_key',         state.apiKey);
//   fd.append('src_lang',        document.getElementById('srcLang').value);
//   fd.append('tgt_lang',        document.getElementById('tgtLang').value);
//   fd.append('style',           document.querySelector('input[name="style"]:checked').value);
//   fd.append('voice',           document.getElementById('voiceProfile').value);
//   fd.append('speed',           document.getElementById('speedSlider').value);
//   fd.append('original_volume', document.getElementById('origVolSlider').value);

//   showProgressPanel();

//   let data;
//   try {
//     const r = await fetch(`${API}/start`, { method: 'POST', body: fd });
//     data = await r.json();
//     if (!r.ok || data.error) {
//       hideProgressPanel();
//       toast(data.error || `Server error ${r.status}`, 'error');
//       return;
//     }
//   } catch (e) {
//     hideProgressPanel();
//     toast(`Upload failed: ${e.message}`, 'error');
//     return;
//   }

//   state.jobId = data.job_id;
//   state.lastLogCount = 0;
//   document.getElementById('progressJobId').textContent = `Job: ${data.job_id.slice(0,8)}`;
//   startSSE(data.job_id);
// }

// // ── Real-time Updates via SSE ──────────────────────────────
// function startSSE(jobId) {
//   stopPolling();
//   if (state.evtSrc) state.evtSrc.close();

//   let sseOk = false;
//   state.evtSrc = new EventSource(`${API}/job/${jobId}/stream`);

//   state.evtSrc.onopen = () => { sseOk = true; };

//   state.evtSrc.onmessage = e => {
//     sseOk = true;
//     const data = JSON.parse(e.data);
//     applyUpdate(data);
//     if (data.status === 'done') {
//       state.evtSrc.close();
//       showResult(data);
//     } else if (data.status === 'error') {
//       state.evtSrc.close();
//       hideProgressPanel();
//       toast(`Dubbing failed: ${data.error}`, 'error');
//     }
//   };

//   state.evtSrc.onerror = () => {
//     state.evtSrc.close();
//     // Fall back to polling if SSE unavailable
//     startPolling(jobId);
//   };
// }

// function startPolling(jobId) {
//   stopPolling();
//   state.polling = setInterval(async () => {
//     try {
//       const r    = await fetch(`${API}/job/${jobId}`);
//       const data = await r.json();
//       applyUpdate(data);
//       if (data.status === 'done') {
//         stopPolling();
//         showResult(data);
//       } else if (data.status === 'error') {
//         stopPolling();
//         hideProgressPanel();
//         toast(`Dubbing failed: ${data.error}`, 'error');
//       }
//     } catch (e) {
//       stopPolling();
//       toast('Lost connection to backend', 'error');
//     }
//   }, 1500);
// }

// function stopPolling() {
//   if (state.polling) { clearInterval(state.polling); state.polling = null; }
// }

// // ── Apply Job Update to UI ─────────────────────────────────
// // Map progress % to which pipeline step is active/done
// const STEPS = [
//   { id: 'step-extract',    active: 3,  done: 14 },
//   { id: 'step-transcribe', active: 14, done: 31 },
//   { id: 'step-translate',  active: 31, done: 51 },
//   { id: 'step-tts',        active: 51, done: 76 },
//   { id: 'step-mix',        active: 76, done: 100 },
// ];

// function applyUpdate(data) {
//   const pct = data.progress || 0;
//   document.getElementById('progressPct').textContent = `${pct}%`;
//   document.getElementById('progressBar').style.width = `${pct}%`;

//   const titles = { queued:'Queued...', running:'Dubbing in progress...', done:'Done!', error:'Failed' };
//   document.getElementById('progressTitle').textContent = titles[data.status] || 'Processing...';

//   STEPS.forEach(s => {
//     const el = document.getElementById(s.id);
//     if (!el) return;
//     if (pct >= s.done)   el.className = 'prog-step done';
//     else if (pct >= s.active) el.className = 'prog-step active';
//     else                 el.className = 'prog-step';
//   });

//   // Append new log lines
//   if (Array.isArray(data.logs) && data.logs.length > 0) {
//     const panel = document.getElementById('logPanel');
//     data.logs.forEach(line => {
//       const div = document.createElement('div');
//       const lo  = line.toLowerCase();
//       div.className = 'log-line' +
//         (line.startsWith('✅') || line.startsWith('🎉') ? ' log-ok' :
//          line.startsWith('❌')  ? ' log-err' :
//          line.startsWith('⚠️') ? ' log-warn' :
//          (line.startsWith('🎬') || line.startsWith('🎤') ||
//           line.startsWith('🌐') || line.startsWith('🔊') ||
//           line.startsWith('🎵') || line.startsWith('📼')) ? ' log-info' : '');
//       div.textContent = line;
//       panel.appendChild(div);
//     });
//     panel.scrollTop = panel.scrollHeight;
//   }
// }

// // ── Panels ─────────────────────────────────────────────────
// function showProgressPanel() {
//   document.getElementById('progressPanel').style.display = 'flex';
//   document.getElementById('logPanel').innerHTML = '';
//   document.getElementById('progressPct').textContent = '0%';
//   document.getElementById('progressBar').style.width = '0%';
//   STEPS.forEach(s => { const el = document.getElementById(s.id); if (el) el.className = 'prog-step'; });
// }

// function hideProgressPanel() {
//   document.getElementById('progressPanel').style.display = 'none';
//   stopPolling();
//   if (state.evtSrc) { state.evtSrc.close(); state.evtSrc = null; }
// }

// function showResult(data) {
//   hideProgressPanel();
//   document.getElementById('resultPanel').style.display = 'flex';
//   const src = document.getElementById('srcLang').value;
//   const tgt = document.getElementById('tgtLang').value;
//   document.getElementById('resultSub').textContent =
//     `${src} → ${tgt}  ·  ${state.file ? state.file.name : 'script'} dubbed successfully`;
// }

// function cancelJob() {
//   hideProgressPanel();
//   toast('Job cancelled', 'error');
// }

// function resetAll() {
//   state.jobId  = null;
//   document.getElementById('resultPanel').style.display = 'none';
//   removeFile();
// }

// // ── Download ───────────────────────────────────────────────
// function downloadVideo() {
//   if (!state.jobId) return;
//   const a = document.createElement('a');
//   a.href = `${API}/download/${state.jobId}`;
//   a.download = '';
//   document.body.appendChild(a);
//   a.click();
//   document.body.removeChild(a);
// }

// // ── Transcript ─────────────────────────────────────────────
// async function viewTranscript() {
//   if (!state.jobId) return;
//   try {
//     const r    = await fetch(`${API}/transcript/${state.jobId}`);
//     const data = await r.json();
//     renderTranscript(data);
//     document.getElementById('transcriptModal').style.display = 'flex';
//   } catch (e) {
//     toast('Could not load transcript', 'error');
//   }
// }

// function renderTranscript(data) {
//   const segs = data.translated && data.translated.length ? data.translated : data.segments || [];
//   const src  = document.getElementById('srcLang').value;
//   const tgt  = document.getElementById('tgtLang').value;
//   const body = document.getElementById('transcriptBody');

//   body.innerHTML = `
//     <div class="transcript-header">
//       <span>Time</span><span>${escHtml(src)}</span><span>${escHtml(tgt)}</span>
//     </div>`;

//   segs.forEach(seg => {
//     const div = document.createElement('div');
//     div.className = 'transcript-seg';
//     div.innerHTML = `
//       <span class="ts-time">${formatTime(seg.start || 0)}</span>
//       <span class="ts-orig">${escHtml(seg.text || '')}</span>
//       <span class="ts-trans">${escHtml(seg.translated || seg.text || '')}</span>`;
//     body.appendChild(div);
//   });
// }

// function closeModal() {
//   document.getElementById('transcriptModal').style.display = 'none';
// }

// // ── Text Dub ───────────────────────────────────────────────
// async function runTextDub() {
//   const text = document.getElementById('dialogueText').value.trim();
//   if (!text)                          { toast('Paste some dialogue first', 'error'); return; }
//   if (!state.apiKey || !state.keyValid) { toast('Verify API key first', 'error'); return; }

//   const online = await checkServer();
//   if (!online) { toast('Backend not running', 'error'); return; }

//   showProgressPanel();
//   document.getElementById('progressTitle').textContent = 'Dubbing script...';

//   try {
//     const r = await fetch(`${API}/text-dub`, {
//       method: 'POST',
//       headers: { 'Content-Type': 'application/json' },
//       body: JSON.stringify({
//         api_key:  state.apiKey,
//         text,
//         src_lang: document.getElementById('srcLang').value,
//         tgt_lang: document.getElementById('tgtLang').value,
//         style:    document.querySelector('input[name="style"]:checked').value,
//         voice:    document.getElementById('voiceProfile').value,
//         speed:    parseFloat(document.getElementById('speedSlider').value),
//       }),
//     });

//     if (!r.ok) {
//       const err = await r.json().catch(() => ({ error: 'Unknown error' }));
//       throw new Error(err.error || `Server error ${r.status}`);
//     }

//     const blob = await r.blob();
//     const url  = URL.createObjectURL(blob);
//     const a    = document.createElement('a');
//     a.href = url;
//     a.download = `dubbed_${document.getElementById('tgtLang').value.toLowerCase()}.mp3`;
//     document.body.appendChild(a);
//     a.click();
//     document.body.removeChild(a);
//     URL.revokeObjectURL(url);

//     hideProgressPanel();
//     toast('✓ Dubbed audio downloaded!', 'success');
//   } catch (e) {
//     hideProgressPanel();
//     toast(`Text dub failed: ${e.message}`, 'error');
//   }
// }

// // ── Style Cards ────────────────────────────────────────────
// function setupStyleCards() {
//   document.querySelectorAll('.style-card').forEach(card => {
//     card.addEventListener('click', () => {
//       document.querySelectorAll('.style-card').forEach(c => c.classList.remove('style-card-active'));
//       card.classList.add('style-card-active');
//     });
//   });
// }

// // ── Utilities ──────────────────────────────────────────────
// function formatTime(secs) {
//   const m = Math.floor(secs / 60).toString().padStart(2, '0');
//   const s = Math.floor(secs % 60).toString().padStart(2, '0');
//   return `${m}:${s}`;
// }
// function escHtml(s) {
//   return String(s)
//     .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
// }
// function toast(msg, type = 'info') {
//   const wrap = document.getElementById('toastWrap');
//   const div  = document.createElement('div');
//   div.className = `toast toast-${type}`;
//   div.textContent = msg;
//   wrap.appendChild(div);
//   setTimeout(() => div.remove(), 5000);
// }

// // ── Enter key on API field ─────────────────────────────────
// document.getElementById('apiKey').addEventListener('keydown', e => {
//   if (e.key === 'Enter') validateKey();
//   else {
//     document.getElementById('keyStatus').textContent = '';
//     state.keyValid = false;
//     updateDubButton();
//   }
// });

// // ── Init ───────────────────────────────────────────────────
// (function init() {
//   setupDrop();
//   setupStyleCards();
//   updateDubButton();
//   checkServer();
//   setInterval(checkServer, 10000);
// })();
/* ==========================================================
   AniDub Studio — Frontend v3.0
   New in v3:
    - Segment editor: edit translations before TTS is regenerated
    - Demucs toggle: choose vocal separation vs volume blend
    - SRT export button
    - Duration fitting progress step
    - Demucs status shown in server health
   ========================================================== */
/* ============================================================
   AniDub Studio — Frontend v4.0
   ============================================================ */

const API = 'http://localhost:5050/api';

const state = {
  apiKey:      '',
  keyValid:    false,
  file:        null,
  jobId:       null,
  evtSrc:      null,
  polling:     null,
  segments:    [],
  translated:  [],
  demucsAvail: false,
};

// ── Server Health ──────────────────────────────────────────────────────────
async function checkServer() {
  const dot  = document.getElementById('badgeDot');
  const text = document.getElementById('badgeText');
  const dtag = document.getElementById('demucsTag');
  const drow = document.getElementById('demucsRow');
  try {
    const r    = await fetch(`${API}/health`, { signal: AbortSignal.timeout(3000) });
    const data = await r.json();
    if (r.ok) {
      dot.className = 'badge-dot online';
      text.textContent = 'Backend online';
      state.demucsAvail = !!data.demucs;
      if (dtag) {
        dtag.style.display = '';
        dtag.textContent   = data.demucs ? '✅ Demucs' : '⚠️ No Demucs';
        dtag.style.background = data.demucs
          ? 'rgba(34,197,94,0.12)' : 'rgba(245,158,11,0.12)';
        dtag.style.color = data.demucs ? '#22c55e' : '#f59e0b';
        dtag.style.border = data.demucs
          ? '1px solid rgba(34,197,94,0.25)' : '1px solid rgba(245,158,11,0.25)';
      }
      if (drow) drow.style.display = '';
      return true;
    }
  } catch (_) {}
  dot.className = 'badge-dot offline';
  text.textContent = 'Backend offline';
  if (dtag) dtag.style.display = 'none';
  return false;
}

// ── API Key Validation ─────────────────────────────────────────────────────
async function validateKey() {
  const key = document.getElementById('apiKey').value.trim();
  const fb  = document.getElementById('keyFeedback');
  const btn = document.getElementById('btnVerify');
  if (!key) { toast('Enter your Groq API key first', 'error'); return; }

  state.apiKey   = key;
  state.keyValid = false;
  fb.className   = 'key-feedback kf-loading';
  fb.textContent = '⏳ Verifying...';
  btn.disabled   = true;

  try {
    const r    = await fetch(`${API}/validate-key`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: key }),
    });
    const data = await r.json();
    if (data.valid) {
      state.keyValid = true;
      fb.className   = 'key-feedback kf-ok';
      fb.textContent = '✓ Valid — Ready to dub!';
      toast('API key verified ✓', 'success');
    } else {
      fb.className   = 'key-feedback kf-err';
      fb.textContent = `✗ ${data.error || 'Invalid key'}`;
      toast(data.error || 'Invalid API key', 'error');
    }
  } catch (_) {
    fb.className   = 'key-feedback kf-err';
    fb.textContent = '✗ Cannot reach server — is backend running?';
    toast('Backend offline. Run: python backend/app.py', 'error');
  }

  btn.disabled = false;
  updateLaunchBtn();
}

// ── Tab Switch ─────────────────────────────────────────────────────────────
function switchTab(tab) {
  const isVideo = tab === 'video';
  document.getElementById('videoTabContent').style.display = isVideo ? '' : 'none';
  document.getElementById('textTabContent').style.display  = isVideo ? 'none' : '';
  document.getElementById('itabVideo').className = 'itab' + (isVideo ? ' itab-active' : '');
  document.getElementById('itabText').className  = 'itab' + (!isVideo ? ' itab-active' : '');
}

// ── File Handling ──────────────────────────────────────────────────────────
function handleFile(file) {
  if (!file) return;
  const mb = file.size / (1024 * 1024);
  state.file = file;

  const card = document.getElementById('fileCard');
  card.style.display = 'flex';
  card.innerHTML = `
    <span class="file-icon2">🎬</span>
    <div class="file-meta">
      <div class="file-name">${escHtml(file.name)}</div>
      <div class="file-size">${mb.toFixed(1)} MB · ${file.type || 'video'}</div>
    </div>
    <button class="file-rm" onclick="removeFile()" title="Remove">✕</button>`;
  document.getElementById('dropzone').style.display = 'none';
  updateLaunchBtn();
}

function removeFile() {
  state.file = null;
  document.getElementById('fileCard').style.display = 'none';
  document.getElementById('dropzone').style.display = '';
  document.getElementById('fileInput').value = '';
  updateLaunchBtn();
}

function setupDrop() {
  const dz = document.getElementById('dropzone');
  dz.addEventListener('dragover', e => { e.preventDefault(); dz.classList.add('drag-over'); });
  dz.addEventListener('dragleave', () => dz.classList.remove('drag-over'));
  dz.addEventListener('drop', e => {
    e.preventDefault(); dz.classList.remove('drag-over');
    const f = e.dataTransfer.files[0];
    if (f) handleFile(f);
  });
  dz.addEventListener('click', e => {
    if (e.target.tagName !== 'BUTTON') document.getElementById('fileInput').click();
  });
}

// ── Launch Button State ────────────────────────────────────────────────────
function updateLaunchBtn() {
  const btn = document.getElementById('btnDub');
  const sub = document.getElementById('launchSub');
  const ok  = state.keyValid && !!state.file;
  btn.disabled = !ok;
  if (!state.keyValid && !state.file) sub.textContent = 'Add API key & upload video to begin';
  else if (!state.keyValid)            sub.textContent = 'Verify your Groq API key first';
  else if (!state.file)                sub.textContent = 'Upload a video file to begin';
  else                                 sub.textContent = 'All set — click to start dubbing!';
}

// ── Start Dubbing ──────────────────────────────────────────────────────────
async function startDub() {
  if (!state.file)                      { toast('Upload a video file first', 'error'); return; }
  if (!state.apiKey || !state.keyValid) { toast('Verify API key first', 'error'); return; }

  const online = await checkServer();
  if (!online) { toast('Backend offline. Run: python backend/app.py', 'error'); return; }

  const useDemucs = document.getElementById('demucsToggle')?.checked ?? true;
  const fd = new FormData();
  fd.append('video',           state.file);
  fd.append('api_key',         state.apiKey);
  fd.append('src_lang',        document.getElementById('srcLang').value);
  fd.append('tgt_lang',        document.getElementById('tgtLang').value);
  fd.append('style',           document.querySelector('input[name="style"]:checked').value);
  fd.append('voice',           document.getElementById('voiceProfile').value);
  fd.append('speed',           document.getElementById('speedSlider').value);
  fd.append('original_volume', document.getElementById('origVolSlider').value);
  fd.append('use_demucs',      useDemucs ? 'true' : 'false');

  showProgress();

  let data;
  try {
    const r = await fetch(`${API}/start`, { method: 'POST', body: fd });
    data = await r.json();
    if (!r.ok || data.error) {
      hideProgress();
      toast(data.error || `Server error ${r.status}`, 'error');
      return;
    }
  } catch (e) {
    hideProgress();
    toast(`Upload failed: ${e.message}`, 'error');
    return;
  }

  state.jobId = data.job_id;
  document.getElementById('progressJobId').textContent = `Job: ${data.job_id.slice(0, 8)}`;
  startSSE(data.job_id);
}

// ── SSE / Polling ──────────────────────────────────────────────────────────
function startSSE(jobId) {
  stopPolling();
  if (state.evtSrc) state.evtSrc.close();

  state.evtSrc = new EventSource(`${API}/job/${jobId}/stream`);
  state.evtSrc.onmessage = e => {
    const data = JSON.parse(e.data);
    applyUpdate(data);
    if (data.status === 'done') {
      state.evtSrc.close();
      loadSegments(jobId).then(() => showResult(data));
    } else if (data.status === 'error') {
      state.evtSrc.close();
      hideProgress();
      toast(`Dubbing failed: ${data.error}`, 'error');
    }
  };
  state.evtSrc.onerror = () => {
    if (state.evtSrc) { state.evtSrc.close(); state.evtSrc = null; }
    startPolling(jobId);
  };
}

function startPolling(jobId) {
  stopPolling();
  state.polling = setInterval(async () => {
    try {
      const r    = await fetch(`${API}/job/${jobId}`);
      const data = await r.json();
      applyUpdate(data);
      if (data.status === 'done') {
        stopPolling();
        await loadSegments(jobId);
        showResult(data);
      } else if (data.status === 'error') {
        stopPolling();
        hideProgress();
        toast(`Dubbing failed: ${data.error}`, 'error');
      }
    } catch (_) {
      stopPolling();
      toast('Lost connection to backend', 'error');
    }
  }, 1500);
}

function stopPolling() {
  if (state.polling) { clearInterval(state.polling); state.polling = null; }
}

// ── Apply Update to UI ─────────────────────────────────────────────────────
const STEPS = [
  { id: 'step-separate',  active: 3,  done: 14 },
  { id: 'step-transcribe',active: 14, done: 30 },
  { id: 'step-translate', active: 30, done: 48 },
  { id: 'step-tts',       active: 48, done: 68 },
  { id: 'step-fit',       active: 68, done: 79 },
  { id: 'step-mix',       active: 79, done: 100 },
];

function applyUpdate(data) {
  const pct = data.progress || 0;
  document.getElementById('pctBadge').textContent  = `${pct}%`;
  document.getElementById('pbarFill').style.width  = `${pct}%`;
  const titles = { queued: 'Queued...', running: 'Dubbing in progress...', done: 'Done!', error: 'Failed' };
  document.getElementById('progressTitle').textContent = titles[data.status] || 'Processing...';

  STEPS.forEach(s => {
    const el = document.getElementById(s.id);
    if (!el) return;
    el.className = 'step' + (pct >= s.done ? ' done' : pct >= s.active ? ' active' : '');
  });

  if (Array.isArray(data.logs) && data.logs.length > 0) {
    const box = document.getElementById('logBox');
    data.logs.forEach(line => {
      const div = document.createElement('div');
      div.className = 'log-line' +
        (/^[✅🎉]/.test(line) ? ' log-ok'   :
         /^❌/.test(line)      ? ' log-err'  :
         /^⚠️/.test(line)     ? ' log-warn' :
         /^[🎬🎤🌐🔊🎵📼🎛️⏱️]/.test(line) ? ' log-info' : '');
      div.textContent = line;
      box.appendChild(div);
    });
    box.scrollTop = box.scrollHeight;
  }
}

// ── Load segments ──────────────────────────────────────────────────────────
async function loadSegments(jobId) {
  try {
    const r    = await fetch(`${API}/transcript/${jobId}`);
    const data = await r.json();
    state.segments   = data.segments   || [];
    state.translated = data.translated || [];
  } catch (_) {}
}

// ── Panel show/hide ────────────────────────────────────────────────────────
function showProgress() {
  document.getElementById('overlayProgress').style.display = 'flex';
  document.getElementById('logBox').innerHTML = '';
  document.getElementById('pctBadge').textContent = '0%';
  document.getElementById('pbarFill').style.width = '0%';
  STEPS.forEach(s => {
    const el = document.getElementById(s.id);
    if (el) el.className = 'step';
  });
}

function hideProgress() {
  document.getElementById('overlayProgress').style.display = 'none';
  stopPolling();
  if (state.evtSrc) { state.evtSrc.close(); state.evtSrc = null; }
}

function showResult(data) {
  hideProgress();
  document.getElementById('overlayResult').style.display = 'flex';
  const src = document.getElementById('srcLang').value;
  const tgt = document.getElementById('tgtLang').value;
  const fname = state.file ? state.file.name : 'script';
  const segs  = state.translated.length || state.segments.length;
  document.getElementById('resultDetail').textContent =
    `${src} → ${tgt}  ·  ${fname}  ·  ${segs} segments`;
}

function cancelJob() {
  hideProgress();
  toast('Job cancelled', 'warn');
}

function resetAll() {
  state.jobId      = null;
  state.segments   = [];
  state.translated = [];
  document.getElementById('overlayResult').style.display = 'none';
  removeFile();
}

// ── Download ───────────────────────────────────────────────────────────────
function downloadVideo() {
  if (!state.jobId) return;
  triggerDownload(`${API}/download/${state.jobId}`);
}

function downloadSRT() {
  if (!state.jobId) return;
  triggerDownload(`${API}/job/${state.jobId}/srt`);
}

function triggerDownload(url) {
  const a = document.createElement('a');
  a.href = url; a.download = '';
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
}

// ── Segment Editor ─────────────────────────────────────────────────────────
function openSegmentEditor() {
  const segs = state.translated.length ? state.translated : state.segments;
  if (!segs.length) { toast('No segments yet', 'error'); return; }
  renderEditor(segs);
  document.getElementById('overlaySegments').style.display = 'flex';
}

function closeSegmentEditor(e) {
  if (e && e.target !== document.getElementById('overlaySegments')) return;
  document.getElementById('overlaySegments').style.display = 'none';
}

function renderEditor(segs) {
  const body = document.getElementById('editorBody');
  body.innerHTML = '';

  const tightCount = segs.filter((s, i) => {
    const nxt = segs[i + 1];
    return nxt && (nxt.start - s.start) < 1.0;
  }).length;

  if (tightCount > 0) {
    const w = document.createElement('div');
    w.className = 'seg-tight-warn';
    w.textContent = `⚠️ ${tightCount} segment(s) have gaps under 1 second (shown in red). Keep translations short.`;
    body.appendChild(w);
  }

  segs.forEach((seg, i) => {
    const nxt    = segs[i + 1];
    const gapS   = nxt ? (nxt.start - seg.start) : null;
    const gapStr = gapS !== null ? `${gapS.toFixed(1)}s` : '—';
    const tight  = gapS !== null && gapS < 1.0;

    const row = document.createElement('div');
    row.className = 'seg-row';
    row.innerHTML = `
      <span class="seg-time">${fmt(seg.start || 0)}</span>
      <span class="seg-orig">${escHtml(seg.text || '')}</span>
      <textarea class="seg-edit" data-idx="${i}" rows="2">${escHtml(seg.translated || seg.text || '')}</textarea>
      <span class="seg-gap${tight ? ' tight' : ''}">${gapStr}</span>`;
    body.appendChild(row);
  });
}

function saveSegmentEdits() {
  const segs   = state.translated.length ? [...state.translated] : [...state.segments];
  document.querySelectorAll('#editorBody .seg-edit').forEach(inp => {
    const i = parseInt(inp.dataset.idx);
    if (!isNaN(i) && segs[i]) segs[i] = { ...segs[i], translated: inp.value.trim() };
  });
  state.translated = segs;
  document.getElementById('overlaySegments').style.display = 'none';
  toast('Edits saved ✓', 'success');
}

// ── Transcript viewer ──────────────────────────────────────────────────────
async function viewTranscript() {
  if (!state.jobId) return;
  try {
    const r    = await fetch(`${API}/transcript/${state.jobId}`);
    const data = await r.json();
    renderTranscript(data);
    document.getElementById('overlayTranscript').style.display = 'flex';
  } catch (_) {
    toast('Could not load transcript', 'error');
  }
}

function renderTranscript(data) {
  const segs = data.translated?.length ? data.translated : (data.segments || []);
  const src  = document.getElementById('srcLang').value;
  const tgt  = document.getElementById('tgtLang').value;
  document.getElementById('thSrc').textContent = src;
  document.getElementById('thTgt').textContent = tgt;
  const body = document.getElementById('transcriptBody');
  body.innerHTML = '';
  segs.forEach(seg => {
    const row = document.createElement('div');
    row.className = 'ts-row';
    row.innerHTML = `
      <span class="ts-time">${fmt(seg.start || 0)}</span>
      <span class="ts-orig">${escHtml(seg.text || '')}</span>
      <span class="ts-trans">${escHtml(seg.translated || seg.text || '')}</span>`;
    body.appendChild(row);
  });
}

function closeTranscript(e) {
  if (e && e.target !== document.getElementById('overlayTranscript')) return;
  document.getElementById('overlayTranscript').style.display = 'none';
}

// ── Text Dub ───────────────────────────────────────────────────────────────
async function runTextDub() {
  const text = document.getElementById('dialogueText').value.trim();
  if (!text)                            { toast('Paste some dialogue first', 'error'); return; }
  if (!state.apiKey || !state.keyValid) { toast('Verify API key first', 'error'); return; }
  const online = await checkServer();
  if (!online) { toast('Backend offline. Run: python backend/app.py', 'error'); return; }

  showProgress();
  document.getElementById('progressTitle').textContent = 'Dubbing script...';

  try {
    const r = await fetch(`${API}/text-dub`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        api_key:  state.apiKey,
        text,
        src_lang: document.getElementById('srcLang').value,
        tgt_lang: document.getElementById('tgtLang').value,
        style:    document.querySelector('input[name="style"]:checked').value,
        voice:    document.getElementById('voiceProfile').value,
        speed:    parseFloat(document.getElementById('speedSlider').value),
      }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ error: 'Unknown error' }));
      throw new Error(err.error || `Server error ${r.status}`);
    }
    const blob = await r.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href = url;
    a.download = `dubbed_${document.getElementById('tgtLang').value.toLowerCase()}.mp3`;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
    hideProgress();
    toast('✓ Dubbed audio downloaded!', 'success');
  } catch (e) {
    hideProgress();
    toast(`Text dub failed: ${e.message}`, 'error');
  }
}

// ── Style tile clicks ──────────────────────────────────────────────────────
function setupStyleTiles() {
  document.querySelectorAll('.tile').forEach(tile => {
    tile.addEventListener('click', () => {
      document.querySelectorAll('.tile').forEach(t => t.classList.remove('tile-active'));
      tile.classList.add('tile-active');
    });
  });
}

// ── Utilities ──────────────────────────────────────────────────────────────
function fmt(secs) {
  const m = Math.floor(secs / 60).toString().padStart(2, '0');
  const s = Math.floor(secs % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
}

function escHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function toast(msg, type = 'info') {
  const stack = document.getElementById('toastStack');
  const div   = document.createElement('div');
  div.className = `toast toast-${type}`;
  div.textContent = msg;
  stack.appendChild(div);
  setTimeout(() => {
    div.style.opacity = '0';
    div.style.transition = 'opacity 0.3s';
    setTimeout(() => div.remove(), 300);
  }, 4000);
}

// ── Keyboard shortcuts ─────────────────────────────────────────────────────
document.getElementById('apiKey').addEventListener('keydown', e => {
  if (e.key === 'Enter') { validateKey(); return; }
  document.getElementById('keyFeedback').textContent = '';
  state.keyValid = false;
  updateLaunchBtn();
});

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    document.getElementById('overlayProgress').style.display !== 'none'
      ? cancelJob()
      : null;
    document.getElementById('overlayResult').style.display    !== 'none'
      ? (document.getElementById('overlayResult').style.display = 'none')
      : null;
    document.getElementById('overlaySegments').style.display  !== 'none'
      ? (document.getElementById('overlaySegments').style.display = 'none')
      : null;
    document.getElementById('overlayTranscript').style.display !== 'none'
      ? (document.getElementById('overlayTranscript').style.display = 'none')
      : null;
  }
});

// ── Init ───────────────────────────────────────────────────────────────────
(function init() {
  setupDrop();
  setupStyleTiles();
  updateLaunchBtn();
  checkServer();
  setInterval(checkServer, 10000);
})();