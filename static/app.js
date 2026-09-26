let job;
let busy = false;
const $ = id => document.getElementById(id);
const amount = value => `${(value / 1e6).toFixed(2)} USDC`;
function render() {
  $('progress').textContent = `${job.rows.length} / 30`;
  $('spent').textContent = amount(job.spent_micro_usdc);
  $('remaining').textContent = amount(job.remaining_micro_usdc);
  $('bar').value = job.rows.length;
  $('state').textContent = job.state.replaceAll('_', ' ');
  $('agent').textContent = job.active_agent || 'No active worker';
  for (const [id, state] of Object.entries({start:'ready', fail:'primary_working', evaluate:'frozen', resume:'successor_working', approve:'awaiting_approval', cancel:'awaiting_approval'})) {
    $(id).disabled = busy || job.state !== state;
  }
  $('reset').disabled = busy;
  $('approval').hidden = job.state !== 'awaiting_approval';
  $('approval-details').textContent = JSON.stringify(job.approval, null, 2);
  $('capsule').textContent = job.capsule ? JSON.stringify({hash:job.capsule_hash, ...job.capsule}, null, 2) : 'No checkpoint yet.';
  $('csv').hidden = job.state !== 'completed';
  $('events').replaceChildren(...job.events.map(event => {
    const li = document.createElement('li');
    const title = document.createElement('strong');
    title.textContent = event.kind.replaceAll('_', ' ');
    const reason = document.createElement('p');
    reason.textContent = event.reason;
    const meta = document.createElement('small');
    meta.textContent = `EPOCH ${event.epoch} · ${event.hash.slice(0, 16)}`;
    li.append(title, reason, meta);
    return li;
  }));
}
async function action(name, body = {}) {
  if (busy) return;
  busy = true;
  if (job) render();
  $('error').textContent = '';
  try {
    const response = await fetch(`/api/${name}`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error);
    job = result;
  } catch (error) { $('error').textContent = error.message; }
  finally { busy = false; if (job) render(); }
}
for (const name of ['start','fail','resume','reset']) $(name).onclick = () => action(name);
$('evaluate').onclick = () => action('evaluate', {scenario:$('scenario').value});
for (const name of ['approve','cancel']) $(name).onclick = () => action('decide', {approved:name === 'approve', approval_hash:job.approval_hash});
fetch('/api/job').then(r => { if (!r.ok) throw new Error('Could not load job'); return r.json(); }).then(data => {job = data; render();}).catch(error => { $('error').textContent = error.message; });
