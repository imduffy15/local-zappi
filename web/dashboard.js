'use strict';
const $ = id => document.getElementById(id);
const names = {fast:'Fast',eco:'Eco',eco_plus:'Eco+',stop:'Stopped'};
let snapshot = null, busy = false, error = '', settingsBusy = false, loadedSettings = false, readRequested = false;
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
  const ready = p.local_mode_control_ready;
  const request = p.last_local_command;
  const pending = ['queued', 'sent_unconfirmed'].includes(request?.status);
  $('connection').textContent = ready ? 'Connected' : 'Reconnecting…';
  $('mode').textContent = fresh ? names[observed.mode] || 'Unknown' : 'Unavailable';
  document.querySelectorAll('[data-mode]').forEach(button => {
    button.disabled = busy || pending || !ready || s.settings?.busy || settingsBusy;
    button.setAttribute('aria-pressed', String(Boolean(fresh && observed.mode === button.dataset.mode)));
  });
  for (const name of ['grid', 'charger']) {
    const power = s.power?.[name];
    $(name+'-power').textContent = power ? `${(Math.abs(power.watts)/1000).toFixed(2)} kW` : '—';
  }
  $('grid-label').textContent = s.power?.grid?.watts < 0 ? 'Grid export' : 'Grid import';
  document.querySelectorAll('[data-setting]').forEach(b => b.disabled = !ready || pending || s.settings?.busy || settingsBusy);
  const settings=s.settings, config=settings?.configuration;
  if (config && !loadedSettings) { fillSettings(config); loadedSettings=true; }
  if (!settingsBusy) $('settings-message').textContent = settings?.request?.status==='failed' ? settings.request.error : settings?.busy ? 'Updating charger settings…' : config ? 'Settings read from charger.' : 'Waiting for charger settings.';
  if (ready && !config && !readRequested && !pending) {
    readRequested=true;
    api('/settings/read',{}).catch(e => { $('settings-message').textContent=e.message; });
  }
  $('message').textContent = error || (busy ? 'Sending…' : pending ? `Changing to ${names[request.mode]}…` :
    request?.status === 'not_confirmed' ? 'The charger did not confirm that change. Please try again.' :
    !ready ? 'Waiting for the charger to connect.' : '');
}
async function refresh() {
  try { render(await api('/status')); }
  catch (e) {
    $('connection').textContent = 'Disconnected';
    $('mode').textContent = 'Unavailable';
    $('grid-power').textContent = $('charger-power').textContent = '—';
    $('message').textContent = 'Unable to reach your charger. Retrying…';
    document.querySelectorAll('[data-mode], [data-setting]').forEach(button => {
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

const dayNames=['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
function fillSettings(c) {
  $('manual-kwh').value=c.manual_kwh || 5; $('smart-kwh').value=c.smart_kwh || 5; $('smart-time').value=c.smart_time;
  $('timers').replaceChildren();
  c.schedules.forEach((row,i)=>{
    const el=document.createElement('div');el.className='timer';
    el.innerHTML=`<h3>Timer ${i+1}</h3><div class="fields"><label>Start<input type="time" class="start" required></label><label>Duration (minutes)<input type="number" class="duration" min="0" max="1440" required></label></div><div class="days"></div>`;
    el.querySelector('.start').value=row.start;el.querySelector('.duration').value=row.duration_minutes;
    dayNames.forEach((day,d)=>{const label=document.createElement('label'),input=document.createElement('input');input.type='checkbox';input.value=d;input.checked=row.days.includes(d);label.append(input,day);el.querySelector('.days').append(label);});
    $('timers').append(el);
  });
}
document.querySelectorAll('[data-tab]').forEach(button=>button.addEventListener('click',()=>{
  document.querySelectorAll('[data-tab]').forEach(b=>{const selected=b===button;b.setAttribute('aria-selected',String(selected));$(b.dataset.tab+'-panel').classList.toggle('hidden',!selected);});
}));
async function waitSettings() {
  const end=Date.now()+150000;
  while(Date.now()<end) {
    await new Promise(r=>setTimeout(r,700));const s=await api('/status');render(s);
    if(s.settings.request?.status==='failed')throw new Error(s.settings.request.error);
    if(!s.settings.busy)return s.settings;
  }
  throw new Error('Charger settings timed out');
}
async function settingAction(path,body) {
  if(settingsBusy)return;settingsBusy=true;render(snapshot);$('settings-message').textContent='Updating charger…';
  try {
    if(path==='/schedules') {await api('/settings/read',{});await waitSettings();}
    await api(path,body);const result=await waitSettings();
    if(result.configuration)fillSettings(result.configuration);
    $('settings-message').textContent=path==='/schedules'?'Schedules saved and read back from charger.':'Command accepted; settings read back from charger.';
  }catch(e){$('settings-message').textContent=e.message;}
  finally{settingsBusy=false;}
}
$('manual-start').addEventListener('click',()=>settingAction('/boost',{kind:'manual',kwh:Number($('manual-kwh').value)}));
$('smart-start').addEventListener('click',()=>settingAction('/boost',{kind:'smart',kwh:Number($('smart-kwh').value),time:$('smart-time').value}));
$('cancel-boost').addEventListener('click',()=>settingAction('/boost',{kind:'cancel'}));
$('save-schedules').addEventListener('click',()=>settingAction('/schedules',{schedules:[...document.querySelectorAll('.timer')].map(el=>({start:el.querySelector('.start').value,duration_minutes:Number(el.querySelector('.duration').value),days:[...el.querySelectorAll('input[type=checkbox]:checked')].map(x=>Number(x.value))}))}));
