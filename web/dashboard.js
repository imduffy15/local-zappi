'use strict';
const $ = id => document.getElementById(id);
const names = {fast:'Fast',eco:'Eco',eco_plus:'Eco+',stop:'Stopped'};
let snapshot = null, busy = false, error = '';
sessionStorage.removeItem('local-zappi-key');
async function api(path, body) {
  const response = await fetch(path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: body === undefined ? {} : {'Content-Type':'application/json'},
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(6000)
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Unable to connect');
  return result;
}
function render(s) {
  snapshot = s;
  const p = s.protocol || {}, observed = p.device_mode;
  const fresh = observed && Date.now()/1000-observed.received_at < 30;
  const ready = s.forward_upstream && p.local_mode_control_ready;
  const request = p.last_local_command;
  const pending = request?.status === 'sent_unconfirmed';
  $('connection').textContent = ready ? 'Connected' : 'Reconnecting…';
  $('mode').textContent = fresh ? names[observed.mode] || 'Unknown' : 'Unavailable';
  document.querySelectorAll('[data-mode]').forEach(button => {
    button.disabled = busy || pending || !ready;
    button.setAttribute('aria-pressed', String(Boolean(fresh && observed.mode === button.dataset.mode)));
  });
  $('message').textContent = error || (busy ? 'Sending…' : pending ? `Changing to ${names[request.mode]}…` :
    request?.status === 'not_confirmed' ? 'The charger did not confirm that change. Please try again.' :
    !ready ? 'Waiting for the charger to connect.' : '');
}
async function refresh() {
  try { render(await api('/status')); }
  catch (e) {
    $('connection').textContent = 'Disconnected';
    $('mode').textContent = 'Unavailable';
    $('message').textContent = 'Unable to reach your charger. Retrying…';
    document.querySelectorAll('[data-mode]').forEach(button => {
      button.disabled = true;
      button.setAttribute('aria-pressed', 'false');
    });
  }
}
document.querySelectorAll('[data-mode]').forEach(button => button.addEventListener('click', async () => {
  if (busy || !snapshot) return;
  busy = true; error = ''; render(snapshot);
  try { await api('/mode', {mode:button.dataset.mode}); }
  catch (e) { error = `Unable to change mode: ${e.message}`; }
  finally { busy = false; await refresh(); }
}));
refresh(); setInterval(refresh, 3000);
