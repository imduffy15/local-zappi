'use strict';
const $ = id => document.getElementById(id);
const names = {fast:'Fast',eco:'Eco',eco_plus:'Eco+',stop:'Stop'};
let token = sessionStorage.getItem('local-zappi-key') || '', snapshot = null, busy = false;
const ago = value => value ? `${Math.max(0,Math.round(Date.now()/1000-value))}s ago` : 'Not yet observed';
function message(text) { $('message').textContent=text; $('message').classList.toggle('hidden',!text); }
async function api(path, body) {
  const headers={}; if(token) headers.Authorization=`Bearer ${token}`;
  if(body!==undefined) headers['Content-Type']='application/json';
  const response=await fetch(path,{method:body===undefined?'GET':'POST',headers,body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(6000)});
  const result=await response.json();
  if(!response.ok) { const e=new Error(result.error || `HTTP ${response.status}`);e.status=response.status;throw e; }
  return result;
}
function pairs(element, data) {
  element.replaceChildren();
  for(const [key,value] of Object.entries(data || {})) {
    const row=document.createElement('div');row.className='statrow';
    const label=document.createElement('span');label.textContent=key.replaceAll('_',' ');
    const number=document.createElement('strong');number.textContent=String(value);
    row.append(label,number);element.append(row);
  }
}
function render(s) {
  snapshot=s; const p=s.protocol || {};
  $('dashboard').classList.remove('hidden');$('locked').classList.add('hidden');
  $('connection').textContent=p.local_mode_control_ready?'Charger connected':'Waiting for verified session';
  $('connection').className=`badge ${p.local_mode_control_ready?'good':'warn'}`;
  const observed=p.last_mode_command;
  $('mode').textContent=names[observed?.mode] || 'Not yet observed';
  $('mode-detail').textContent=observed?.mode?`Observed ${ago(observed.received_at)}`:'Use the app or local controls to issue a mode command.';
  $('control-state').textContent=p.local_mode_control_ready?'Local mode controls are available.':'Waiting for recent, successfully decrypted charger traffic.';
  document.querySelectorAll('[data-mode]').forEach(button=>button.disabled=busy || !s.forward_upstream || !p.local_mode_control_ready);
  const last=p.last_local_command;
  $('command-result').textContent=last?`${names[last.mode]} sent ${ago(last.sent_at)}. Device confirmation pending.`:'';
  $('forwarding').textContent=s.forward_upstream?'On':'Off';
  $('session').textContent=p.local_mode_control_ready?'Verified':p.key_loaded?'Key loaded, awaiting validation':'No key loaded';
  $('verified').textContent=ago(p.last_valid_upstream_at);
  $('uptime').textContent=`${Math.floor(s.uptime_seconds/3600)}h ${Math.floor(s.uptime_seconds/60)%60}m`;
  $('forward-toggle').textContent=s.forward_upstream?'Disable app forwarding':'Enable app forwarding';
  $('forward-toggle').disabled=busy;
  const green=p.observed_cloud_config?.minimum_green_percent;
  $('green').textContent=green===undefined?'Not yet observed':`${green}% green / ${100-green}% grid`;
  pairs($('traffic'),s.counters);pairs($('crypto'),p.counters);
  $('cts').replaceChildren();
  for(const r of Object.values(s.last_telemetry || {})) for(const ct of r.ct_records || []) {
    const tr=document.createElement('tr');
    for(const value of [r.harvi_serial,ct.channel,ct.value_a_s16,ct.value_b_s16,`${ct.type_code} / ${ct.status_byte}`,ago(r.received_at)]) {
      const td=document.createElement('td');td.textContent=String(value);tr.append(td);
    }
    $('cts').append(tr);
  }
  if(!$('cts').children.length) {const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=6;td.textContent='Waiting for Harvi telemetry';tr.append(td);$('cts').append(tr);}
  const expanded=new Set([...$('records').querySelectorAll('details[open]')].map(x=>x.dataset.key));
  $('records').replaceChildren();
  for(const [source,records] of [['Ethernet',s.last_telemetry],['UDP',p.udp_records]]) for(const [id,record] of Object.entries(records || {})) {
    const card=document.createElement('section');card.className='card';
    const heading=document.createElement('h3');heading.textContent=`${source} · ${record.type}`;
    const sub=document.createElement('small');sub.textContent=`${record.length} bytes · ${ago(record.received_at)}`;
    const detail=document.createElement('details');detail.dataset.key=source+id;detail.open=expanded.has(detail.dataset.key);
    const summary=document.createElement('summary');summary.textContent='View fields and raw record';
    const pre=document.createElement('pre');pre.textContent=JSON.stringify(record,null,2);
    detail.append(summary,pre);card.append(heading,sub,detail);$('records').append(card);
  }
}
async function refresh() {
  try { render(await api('/status')); }
  catch(e) {
    document.querySelectorAll('[data-mode]').forEach(button=>button.disabled=true);
    $('forward-toggle').disabled=true;
    $('connection').textContent=e.status===401?'Access key required':'Connection lost';
    $('connection').className='badge warn';
    if(e.status===401){$('locked').classList.remove('hidden');$('dashboard').classList.add('hidden');}
  }
}
$('login').addEventListener('submit',async e=>{e.preventDefault();token=$('token').value.trim();try{render(await api('/status'));sessionStorage.setItem('local-zappi-key',token);$('token').value='';message('');}catch(e){message(e.message);}});
document.querySelectorAll('[data-mode]').forEach(button=>button.addEventListener('click',async()=>{
  if(busy)return;busy=true;render(snapshot);
  try{const result=await api('/mode',{mode:button.dataset.mode});message(`${names[result.mode]} command sent. Check the charger display to confirm.`);}
  catch(e){message(`Command not sent: ${e.message}`);}finally{busy=false;await refresh();}
}));
$('forward-toggle').addEventListener('click',async()=>{if(busy || !snapshot)return;busy=true;render(snapshot);try{await api('/config',{forward_upstream:!snapshot.forward_upstream});message('App forwarding updated.');}catch(e){message(e.message);}finally{busy=false;await refresh();}});
$('logout').addEventListener('click',()=>{token='';sessionStorage.removeItem('local-zappi-key');snapshot=null;$('dashboard').classList.add('hidden');$('locked').classList.remove('hidden');});
$('download').addEventListener('click',()=>{if(!snapshot)return;const url=URL.createObjectURL(new Blob([JSON.stringify(snapshot,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='local-zappi-snapshot.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
refresh();setInterval(refresh,3000);
