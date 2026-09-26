let job;
let busy = false;
let pollTimer;
const $ = id => document.getElementById(id);
const amount = value => `${(value / 1e6).toFixed(2)} USDC`;
function render() {
  const world = job.world;
  $('progress').textContent = `${job.rows.length} / 30`;
  $('spent').textContent = amount(job.spent_micro_usdc);
  $('remaining').textContent = amount(job.remaining_micro_usdc);
  $('bar').value = job.rows.length;
  $('state').textContent = job.state.replaceAll('_', ' ');
  $('agent').textContent = job.active_agent || 'No active worker';
  for (const [id, state] of Object.entries({start:'ready', fail:'primary_working', evaluate:'frozen', resume:'successor_working', approve:'awaiting_approval', cancel:'awaiting_approval', verify:'awaiting_approval'})) {
    $(id).disabled = busy || job.state !== state;
  }
  $('start').disabled ||= !world.owner_connected;
  $('approve').disabled ||= !world.can_approve;
  $('verify').disabled ||= !world.configured || world.status === 'pending' || world.can_approve;
  $('connect').disabled = busy || !world.configured || world.owner_connected || world.status === 'pending' || job.state !== 'ready';
  $('connect').hidden = world.owner_connected;
  $('world-setup').hidden = world.configured;
  $('world-status').textContent = !world.configured ? 'Not configured — real verification requires a registered client.' :
    world.error ? world.error.message : world.status === 'pending' ? 'Waiting for World verification…' :
    world.can_approve ? 'Same owner verified. Review the handoff and approve below.' :
    world.owner_connected ? 'Job owner connected through World sandbox.' : 'Connect the owner before starting this job.';
  $('world-attempt').hidden = world.status !== 'pending';
  $('world-code').textContent = world.user_code || '';
  if (world.verification_url) $('world-link').href = world.verification_url;
  $('world-deadline').textContent = world.expires_at ? `Complete before ${new Date(world.expires_at * 1000).toLocaleTimeString()}.` : '';
  $('world-cancel').disabled = busy;
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
  clearTimeout(pollTimer);
  if (!busy && world.status === 'pending') pollTimer = setTimeout(() => action('world/poll'), world.poll_after * 1000);
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
  } catch (error) {
    $('error').textContent = error.message;
    // Synchronize consumed/expired attempts after a failed action; never grant locally.
    try { const r = await fetch('/api/job'); if (r.ok) job = await r.json(); } catch (_) { /* Keep the network error visible. */ }
  } finally { busy = false; if (job) render(); }
}
for (const name of ['start','fail','resume','reset']) $(name).onclick = () => action(name);
$('evaluate').onclick = () => action('evaluate', {scenario:$('scenario').value});
$('connect').onclick = () => action('world/start', {purpose:'owner'});
$('verify').onclick = () => action('world/start', {purpose:'handoff', approval_hash:job.approval_hash});
$('world-cancel').onclick = () => action('world/cancel');
for (const name of ['approve','cancel']) $(name).onclick = () => action('decide', {approved:name === 'approve', approval_hash:job.approval_hash});
fetch('/api/job').then(r => { if (!r.ok) throw new Error('Could not load job'); return r.json(); }).then(data => {job = data; render();}).catch(error => { $('error').textContent = error.message; });
