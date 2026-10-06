// Exercise the real browser orchestration with controlled HTTP responses.
// DOM stubs isolate timing and errors; actual rendering is checked in a browser.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const web = path.join(__dirname, '../src/mcdxkit/web');
function element() {
  return {
    hidden: false, value: '', textContent: '', dataset: {}, children: [], attributes: {}, listeners: {},
    classList: {add() {}, remove() {}, toggle() {}},
    addEventListener(type, callback) { this.listeners[type] = callback; },
    setAttribute(key, value) { this.attributes[key] = String(value); },
    removeAttribute(key) { delete this.attributes[key]; if (key === 'value') delete this.value; },
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; },
    querySelector() { return null; }, contains() { return false; }, closest() { return {}; }, close() {}, show() {}, focus() {},
  };
}

async function browser(action, count, setup = '') {
  const html = fs.readFileSync(path.join(web, 'index.html'), 'utf8');
  const nodes = new Map([...html.matchAll(/id="([^"]+)"/g)].map(match => [match[1], element()]));
  nodes.get('basis').value = 'effects';
  const requests = [];
  const context = vm.createContext({
    document: {
      getElementById: id => nodes.get(id), querySelectorAll: () => [], addEventListener() {},
      createElement: element, createTextNode: text => ({textContent: text}), body: element(),
    },
    window: {matchMedia: () => ({matches:false})},
    setTimeout, clearTimeout, URL, URLSearchParams,
    fetch(url, options) {
      if (url === '/api/session') return Promise.resolve({status: 401});
      return new Promise(resolve => requests.push({url, options, resolve}));
    },
  });
  vm.runInContext(fs.readFileSync(path.join(web, 'app.js'), 'utf8'), context);
  await Promise.resolve();
  vm.runInContext(`
    session = {token:'synthetic'}; hasTemplate = true;
    inspect = async () => {}; inspectDiff = async () => {};
    for (let n = 1; n <= ${count}; n++) items.push({
      id:'r'+n, name:'report-'+n+'.gp11t', selected:[1],
      inspection:{cases:[{id:1,name:'STR test'}], envelope:{P:10}},
      preview:${action === 'convert' ? '{worksheet:{id:"preview"},diff:{changes:[]}}' : 'null'}
    });
    ${setup}
  `, context);
  const finished = nodes.get(action === 'convert' ? 'convert-all' : 'compare-next').listeners.click();
  async function respond(index, ok, message = 'Synthetic calculation failure') {
    assert.ok(requests[index], 'Expected the next request');
    requests[index].resolve({ok, json: async () => ok
      ? {worksheet:{id:'out'+index}, diff:{changes:[]}, calculation:{calculated:true}}
      : {error:message}});
    await new Promise(resolve => setImmediate(resolve));
  }
  return {nodes, requests, respond, finished, context};
}

for (const action of ['preview', 'convert']) {
  test(`${action}: single-file progress stays indeterminate until the response`, async () => {
    const app = await browser(action, 1);
    const panel = app.nodes.get('operation-progress');
    assert.ok(panel, 'A browser progress region must exist');
    assert.equal(panel.hidden, false);
    assert.equal(panel.dataset.running, 'true');
    assert.equal(app.nodes.get('operation-bar').attributes.value, undefined);
    assert.match(app.nodes.get('operation-current').textContent, /report-1/);
    assert.match(app.nodes.get('operation-count').textContent, /0 of 1/);
    assert.equal(app.requests.length, 1);
    assert.deepEqual(Object.keys(JSON.parse(app.requests[0].options.body)).sort(),
      ['cases','id','load_source','overrides','template_id']);
    await app.respond(0, true);
    await app.finished;
    assert.equal(panel.dataset.running, 'false');
    assert.equal(app.nodes.get('operation-bar').attributes.value, '1');
    assert.match(app.nodes.get('operation-current').textContent, /1 ready/);
  });
}

test('batch progress counts finished files and reports partial failures', async () => {
  const app = await browser('convert', 2);
  assert.ok(app.nodes.get('operation-progress'), 'A browser progress region must exist');
  assert.equal(app.nodes.get('operation-bar').attributes.value, '0');
  await app.respond(0, false);
  assert.equal(app.nodes.get('operation-bar').attributes.value, '1');
  assert.match(app.nodes.get('operation-count').textContent, /1 of 2/);
  assert.match(app.nodes.get('operation-current').textContent, /report-2/);
  await app.respond(1, true);
  await app.finished;
  assert.equal(app.nodes.get('operation-bar').attributes.value, '2');
  assert.equal(app.nodes.get('operation-progress').dataset.running, 'false');
  assert.match(app.nodes.get('operation-current').textContent, /1 ready.*1 failed/);
});

test('retry resets progress and clears a previous file failure', async () => {
  const app = await browser('convert', 1);
  await app.respond(0, false);
  await app.finished;
  assert.ok(app.nodes.get('operation-progress'), 'A browser progress region must exist');
  assert.match(app.nodes.get('operation-current').textContent, /0 ready.*1 failed/);
  const retry = app.nodes.get('convert-all').listeners.click();
  assert.equal(app.nodes.get('operation-progress').dataset.running, 'true');
  assert.equal(app.nodes.get('operation-bar').attributes.value, undefined);
  assert.match(app.nodes.get('operation-count').textContent, /0 of 1/);
  await app.respond(1, true);
  await retry;
  assert.match(app.nodes.get('operation-current').textContent, /^1 ready$/);
  assert.doesNotMatch(app.nodes.get('notice').textContent, /failed/);
});


test('rejected template overrides return to Inputs and stop the activity indicator', async () => {
  const app = await browser('preview', 1);
  await app.respond(0, false, 'Unsupported override: synthetic');
  await app.finished;
  assert.equal(app.nodes.get('operation-progress').dataset.running, 'false');
  assert.equal(app.nodes.get('step-2').hidden, false);
  assert.equal(app.nodes.get('overrides').attributes['aria-invalid'], 'true');
  assert.match(app.nodes.get('notice').textContent, /Fix the template input overrides/);
});

// Review decisions are advisory: only a decision the engineer made reaches the request.
const flag = (rule, c) => `{rule:'${rule}', case:${c}, component:'P', message:'m', impact:{envelope:true, selection:true, magnitude:0.2, components:['P']}}`;
const decided = `
    const item = items[0]; item.sha = 'abc'; item.inspection.load_source = 'effects';
    const [kept, copied, later] = [${flag('service_axial_above_strength', 3)}, ${flag('duplicate_case', 4)}, ${flag('ratio_outlier', 3)}];
    item.inspection.review_checks = {flags:[kept, copied]};
    item.keepNote = '  checked the factors  ';
    decide(item, {case:3, flags:[kept]}, 'kept_service');
    // A card decision is never overwritten, and covers flags raised later for the same case.
    globalThis.overwrote = decide(item, {case:3, flags:[kept]}, 'will_fix_in_group');
    globalThis.coversLater = Boolean(reviewGroups(item, {flags:[kept, later]}).find(g => g.case === 3).record);
    // An "added" decision for a case that is no longer selected does not stand.
    decide(item, {case:4, flags:[copied]}, 'included_case', 'r1');
`;
test('review decisions are sent only after the engineer decides, without local state', async () => {
  const app = await browser('preview', 1, decided);
  assert.equal(vm.runInContext('overwrote', app.context), false);
  assert.equal(vm.runInContext('coversLater', app.context), true);
  const body = JSON.parse(app.requests[0].options.body);
  assert.equal(body.review_decisions.length, 1);
  const [sent] = body.review_decisions;
  assert.deepEqual(Object.keys(sent).sort(), ['case', 'component', 'decided_at', 'decision', 'note', 'rule']);
  assert.equal(sent.decision, 'kept_service');
  assert.equal(sent.note, 'checked the factors');
  assert.match(sent.decided_at, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
  await app.respond(0, true);
  await app.finished;
  // A decision is keyed by load source: on another basis it is not reused.
  vm.runInContext(`items[0].inspection.load_source = 'reactions'`, app.context);
  assert.equal(vm.runInContext(`reviewDecisions(items[0], items[0].inspection.review_checks.flags).length`, app.context), 0);
  // Checks that could not run stay visible on Changes and Outputs.
  assert.match(vm.runInContext(`reviewChip({flags:[], errors:[{id:'my_check', message:'boom'}]}).children[0].textContent`, app.context),
    /could not run; check the GROUP input yourself.*my_check: boom/);
  assert.match(vm.runInContext(`items[0].preview = {review_checks:{flags:[], errors:[{id:null, message:'view failed'}]}}; pendingView(items[0]).children[0].textContent`, app.context),
    /could not run/);
});

test('a stale review decision never blocks the preview, and outputs repeat the preview decisions', async () => {
  const app = await browser('preview', 1, decided);
  assert.ok(JSON.parse(app.requests[0].options.body).review_decisions);
  await app.respond(0, false, "Review decision does not match a raised flag: ('service_axial_above_strength', 3, 'P')");
  assert.equal(JSON.parse(app.requests[1].options.body).review_decisions, undefined);
  await app.respond(1, true);
  await app.finished;
  assert.equal(app.nodes.get('step-3').hidden, false);
  const convert = await browser('convert', 1, decided + `item.preview = {worksheet:{id:'preview'}, diff:{changes:[]}}; item.previewDecisions = reviewDecisions(item, item.inspection.review_checks.flags);`);
  assert.equal(JSON.parse(convert.requests[0].options.body).review_decisions[0].decision, 'kept_service');
  await convert.respond(0, true);
  await convert.finished;
});
