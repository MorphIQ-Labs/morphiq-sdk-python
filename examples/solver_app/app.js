/* UI only: request construction and rendering, no local pricing/root finding. */
const $ = id => document.getElementById(id);
const form = $('controls');
let quote = null;
let busy = false;
const n = id => Number($(id).value);
const text = value => value == null ? 'Not reported' : String(value);
const pretty = value => JSON.stringify(value, null, 2);
function request() {
  const american = $('model').value === 'bs1993';
  const contract = {
    pricing_model: american ? 'bjerksund_stensland_1993' : 'black_scholes_merton',
    exercise_style: american ? 'american' : 'european', option_type: $('option_type').value,
    spot: n('spot'), strike: n('strike'), time_to_expiry_years: n('time_to_expiry_years'),
    volatility: n('volatility') / 100, risk_free_rate: n('risk_free_rate') / 100,
    dividend_yield: n('dividend_yield') / 100,
  };
  const target = {kind: $('target_kind').value, value: n('target_value')};
  if (target.kind === 'position_pnl') target.position = {quantity: n('quantity'), multiplier: n('multiplier')};
  const body = {contract, target, min_spot: n('min_spot'), max_spot: n('max_spot'),
    elapsed_time_years: n('elapsed_time_years'), spot_tolerance: n('spot_tolerance'), value_tolerance: n('value_tolerance')};
  if ($('scenario_volatility').value !== '') body.volatility = n('scenario_volatility') / 100;
  return body;
}
function refresh() {
  for (const input of form.querySelectorAll('input,select,button')) input.disabled = busy;
  $('solve').disabled = busy || !quote;
}
form.addEventListener('submit', event => event.preventDefault());
form.addEventListener('input', event => {
  if (event.target.id === 'max_cu') return;
  quote = null;
  $('quoted-cu').textContent = '—';
  $('outcome').hidden = true;
  $('result-title').textContent = 'Inputs changed.';
  $('status').textContent = 'Get a new quote. Earlier responses remain in request receipts.';
  const pnl = $('target_kind').value === 'position_pnl';
  $('position').hidden = !pnl;
  $('target-help').textContent = pnl ? 'Total position P&L relative to its base model mark, in the contract’s currency.' : 'Price is per underlying unit in the contract’s currency.';
  refresh();
});
function table(id, rows, columns, empty) {
  const host = $(id); host.replaceChildren();
  if (!rows.length) { const p = document.createElement('p'); p.className = 'empty'; p.textContent = empty; host.append(p); return; }
  const wrap = document.createElement('div'); wrap.className = 'table-wrap';
  const table = document.createElement('table');
  const head = table.createTHead().insertRow();
  for (const [label] of columns) { const th = document.createElement('th'); th.textContent = label; head.append(th); }
  const body = table.createTBody();
  for (const row of rows) { const tr = body.insertRow(); for (const [, value] of columns) tr.insertCell().textContent = text(value(row)); }
  wrap.append(table); host.append(wrap);
}
function outcome(result) {
  $('outcome').hidden = false;
  $('result-title').textContent = result.coverage.status === 'unresolved' ? 'Search incomplete.' : result.boundaries.length ? 'Target boundaries returned.' : 'No boundary found in this scan.';
  $('status').textContent = `API coverage: ${result.coverage.status}. Model: ${result.pricing_model}. Results apply to the submitted inputs.`;
  $('metrics').replaceChildren();
  for (const [label, value] of [['Search range', `${result.min_spot} – ${result.max_spot}`], ['Target', `${result.target.kind}: ${result.target.value}`], ['Base option price', result.base.result.price], ['Price evaluations', result.price_evaluations]]) {
    const card = document.createElement('div'); card.className = 'metric';
    const caption = document.createElement('span'); caption.textContent = label;
    const content = document.createElement('strong'); content.textContent = text(value);
    card.append(caption, content); $('metrics').append(card);
  }
  table('boundaries', result.boundaries, [['Kind', r => r.kind], ['Spot / interval', r => r.kind === 'point' ? r.spot : `${r.min_spot} – ${r.max_spot}`], ['Value', r => r.value], ['Value − target', r => r.value - result.target.value]], 'No boundaries returned. Review coverage and sign regions.');
  table('regions', result.regions, [['From', r => r.min_spot], ['To', r => r.max_spot], ['Sign', r => r.sign]], 'No sign regions returned.');
  table('cells', result.coverage.cells || [], [['From', r => r.lower_spot], ['To', r => r.upper_spot], ['Best spot', r => r.best_spot], ['Absolute error', r => r.best_abs_value_error], ['Reason', r => r.reason]], 'No unresolved cells reported.');
  $('assumptions').textContent = pretty({base: result.base, inputs: result.inputs, target: result.target, reference_net_value: result.reference_net_value, profile: result.profile, spot_tolerance: result.spot_tolerance, value_tolerance: result.value_tolerance});
}
function receipt(action, payload, submitted) {
  const host = $('history'); host.querySelector('.empty')?.remove();
  const entry = document.createElement('div'); entry.className = 'receipt';
  const title = document.createElement('strong'); title.textContent = `${action === 'quote' ? 'Quote' : 'Solve'} · ${new Date().toLocaleTimeString()} · ${payload.ok ? 'response received' : 'refused / failed'}`;
  let body;
  try { body = JSON.parse(payload.raw_response); } catch { body = null; }
  const metadata = payload.metadata || body?.metadata;
  // The Python adapter sends the charge as a decimal string, preserving large
  // integers exactly. Full raw responses remain available as source records.
  const charge = payload.charged_cu;
  const chargeLine = document.createElement('p'); chargeLine.textContent = `Charged CU: ${payload.local_refusal ? '0 (no upstream request)' : charge ?? 'unknown / not reported'} · Request ID: ${text(payload.request_id || metadata?.request_id)}`;
  const message = document.createElement('p'); message.textContent = payload.message || `Quoted CU: ${payload.quoted_cu ?? metadata?.fcu_quoted ?? 'not reported'} · Schedule: ${text(metadata?.fcu_schedule_id)} / ${text(metadata?.fcu_schedule_version)}`;
  const details = document.createElement('details');
  const summary = document.createElement('summary'); summary.textContent = 'Submitted inputs & complete API response';
  const raw = document.createElement('pre'); raw.textContent = pretty(submitted) + '\n\n' + (payload.raw_response || pretty(payload));
  details.append(summary, raw); entry.append(title, chargeLine, message, details); host.prepend(entry);
  return body;
}
async function act(action) {
  if (busy || !form.reportValidity()) return;
  const submitted = {request: request()};
  if (action === 'solve') {
    if (!quote) return;
    submitted.quote_id = quote.quote_id; submitted.max_cu = $('max_cu').value;
    if (BigInt(submitted.max_cu) < BigInt(quote.quoted_cu)) {
      $('status').textContent = 'Quote exceeds the CU limit. No solve submitted; increase the limit to proceed.';
      return;
    }
  }
  busy = true; refresh(); $('outcome').hidden = true;
  $('result-title').textContent = action === 'quote' ? 'Requesting quote…' : 'Solving through the API…';
  $('status').textContent = 'One request in progress. No automatic retries.';
  quote = null; $('quoted-cu').textContent = '—';
  try {
    const response = await fetch(`/api/${action}`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(submitted)});
    const payload = await response.json();
    const body = receipt(action, payload, submitted);
    if (!payload.ok) {
      $('result-title').textContent = 'Request did not complete successfully.';
      $('status').textContent = payload.message + ' Review the receipt before submitting again.';
    } else if (action === 'quote') {
      quote = payload; $('quoted-cu').textContent = payload.quoted_cu;
      $('result-title').textContent = 'Quote ready.';
      $('status').textContent = `${payload.quoted_cu} CU for one complete solve. Check the limit, then click Solve to execute.`;
    } else outcome(body.result);
  } catch {
    const message = 'No usable app response. Execution and charge unknown. No retry attempted; reconcile before submitting again.';
    receipt(action, {ok: false, message}, submitted);
    $('result-title').textContent = 'Outcome unknown.'; $('status').textContent = message;
  } finally { busy = false; refresh(); }
}
$('quote').addEventListener('click', () => act('quote'));
$('solve').addEventListener('click', () => act('solve'));
