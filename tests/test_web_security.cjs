const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const source = fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8');
const container = {};
const context = vm.createContext({ document: { getElementById: () => container } });
vm.runInContext(source.slice(0, source.indexOf('// Initialize the app and expose globally')) +
    '\nglobalThis.conductor = Object.create(MFConductor.prototype);', context);
const app = context.conductor;
const decode = text => text.replace(/&quot;/g, '"').replace(/&#39;/g, "'")
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');

test('text and attributes round-trip quotes and HTML without adding markup', () => {
    for (const text of ['description" onmouseover="void(0)', "a'b", '<img src=x onerror=void(0)>', '&quot;', 'normal']) {
        const escaped = app.escapeHtml(text);
        assert.equal(decode(escaped), text);
        assert.equal(/[<>"']/.test(escaped), false);
        assert.equal(app.escapeAttr(text), escaped);
    }
    assert.equal(app.escapeHtml(0), '0');
});

test('browse descriptions cannot break out of the title attribute', () => {
    const description = 'description" onmouseover="void(0)';
    app.browseNodes = [{ title: 'Example', description, reference: 'https://example.com/repo', author: 'Test' }];
    app.renderBrowseNodes();
    assert.ok(container.innerHTML.includes('title="description&quot; onmouseover=&quot;void(0)"'));
    assert.ok(!container.innerHTML.includes('title="description" onmouseover='));
});

test('inline handler arguments preserve quotes, backslashes, entities and newlines', () => {
    for (const value of ["x');globalThis.injected=true;//", 'a\\b\nnext\rline', '"&quot;<tag>']) {
        const escaped = decode(app.escapeJs(value));
        const sandbox = { result: null };
        vm.runInNewContext(`result = '${escaped}';`, sandbox);
        assert.equal(sandbox.result, value);
        assert.equal(sandbox.injected, undefined);
    }
});

test('all frontend management POST requests declare JSON', () => {
    for (const text of [source, fs.readFileSync(path.join(__dirname, '../js/mf_conductor.js'), 'utf8')]) {
        const posts = [...text.matchAll(/method:\s*['"]POST['"]/g)];
        assert.ok(posts.length > 0);
        for (const post of posts) {
            assert.match(text.slice(post.index, post.index + 130), /['"]Content-Type['"]:\s*['"]application\/json['"]/);
        }
    }
});

test('a stopped response from before launch completion cannot stop new polling', async () => {
    let resolveFetch;
    context.fetch = () => new Promise(resolve => { resolveFetch = resolve; });
    const subject = Object.create(Object.getPrototypeOf(app));
    subject._consolePollEpoch = 1;
    subject.comfyStatus = 'starting';
    subject.updateComfyStatus = () => { throw new Error('Stale response changed status'); };
    subject.stopConsolePolling = () => { throw new Error('Stale response stopped polling'); };
    const pending = subject.pollConsoleOutput();
    subject._consolePollEpoch = 2;
    resolveFetch({ json: async () => ({ success: true, status: 'stopped' }) });
    await pending;
    assert.equal(subject.comfyStatus, 'starting');
});

test('readiness updates the visible status and preserves external ownership and port', async () => {
    context.fetch = async () => ({});
    context.AbortController = AbortController;
    context.setTimeout = setTimeout;
    context.clearTimeout = clearTimeout;
    const subject = Object.create(Object.getPrototypeOf(app));
    subject.comfyPort = 8190;
    subject.comfyManaged = false;
    subject.log = subject.appendToConsole = () => {};
    let observed;
    subject.updateComfyStatus = (...args) => { observed = args; };
    await subject.checkComfyServerReady();
    assert.equal(subject.comfyServerReady, true);
    assert.deepEqual(observed, ['running', null, false, 8190]);
});

for (const method of ['bulkDeactivateSelected', 'bulkRemoveSelected']) {
    test(`${method} reports partial failures and keeps failed nodes selected`, async () => {
        const subject = Object.create(Object.getPrototypeOf(app));
        subject.selectedNodes = new Set(['Good Node', 'Rejected', 'Offline']);
        subject.apiBase = '';
        subject.showConfirm = async () => true;
        subject.refreshNodes = async () => {};
        const logs = [];
        subject.log = (...args) => logs.push(args);
        let toast;
        subject.showToast = (...args) => { toast = args; };
        const urls = [];
        context.fetch = async url => {
            urls.push(url);
            if (url.includes('Offline')) throw new Error('Disconnected');
            return { ok: true, json: async () => url.includes('Rejected')
                ? { success: false, message: 'Required node' } : { success: true } };
        };
        await subject[method]();
        assert.deepEqual([...subject.selectedNodes], ['Rejected', 'Offline']);
        assert.equal(toast[0], 'warning');
        assert.match(toast[1], /1\/3/);
        assert.ok(urls[0].includes('Good%20Node'));
        assert.ok(logs.some(([text, level]) => level === 'error' && text.includes('Required node')));
        assert.ok(logs.some(([text, level]) => level === 'error' && text.includes('Disconnected')));
    });
}
