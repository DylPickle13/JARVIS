'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const packageJson = require('./package.json');
const {activateWith, isPiDesk, COPY_SEQUENCE} = require('./extension');

function harness(t, name = 'pi-desk') {
    const calls = [];
    const handlers = new Map();
    const events = [];
    let poll;
    let cleared = false;
    t.mock.method(global, 'setInterval', (callback, delay) => {
        assert.equal(delay, 250);
        poll = callback;
        return 123;
    });
    t.mock.method(global, 'clearInterval', id => {
        assert.equal(id, 123);
        cleared = true;
    });
    const event = callback => {
        events.push(callback);
        return {dispose() {}};
    };
    const vscode = {
        window: {activeTerminal: {name}, onDidChangeActiveTerminal: event,
            onDidOpenTerminal: event, onDidCloseTerminal: event},
        commands: {
            registerCommand(name, handler) {
                handlers.set(name, handler);
                return {dispose() {handlers.delete(name);}};
            },
            executeCommand(...args) {calls.push(args); return Promise.resolve();},
        },
    };
    const context = {subscriptions: []};
    activateWith(vscode, context);
    return {vscode, calls, handlers, events, poll,
        dispose() {context.subscriptions.forEach(value => value.dispose());},
        get cleared() {return cleared;}};
}

test('only exact app title is selected; no terminal is safe', () => {
    assert.equal(isPiDesk(undefined), false);
    assert.equal(isPiDesk({name: 'zsh'}), false);
    assert.equal(isPiDesk({name: 'pi-desk-not-really'}), false);
    assert.equal(isPiDesk({name: 'pi-desk'}), true);
});

test('copy sends one dedicated sequence, with no pasted newline or clipboard reads', async t => {
    const app = harness(t);
    await app.handlers.get('piDesk.copySelection')();
    assert.deepEqual(app.calls, [
        ['setContext', 'piDesk.selectionTerminal', true],
        ['workbench.action.terminal.sendSequence', {text: COPY_SEQUENCE}],
    ]);
    assert.equal(COPY_SEQUENCE, '\x1b[9001~');
    app.dispose();
    assert.equal(app.cleared, true);
});

test('stale title/context never injects a copy key into a normal shell', async t => {
    const app = harness(t);
    app.vscode.window.activeTerminal.name = 'zsh';
    await app.handlers.get('piDesk.copySelection')();
    assert.deepEqual(app.calls.slice(1), [
        ['setContext', 'piDesk.selectionTerminal', false],
        ['workbench.action.terminal.copySelection'],
    ]);
    app.dispose();
});

test('attach/detach title polling and active-terminal changes update only context', t => {
    const app = harness(t, 'zsh');
    app.poll();
    assert.equal(app.calls.length, 1, 'Unchanged title must not cause repeated writes');
    app.vscode.window.activeTerminal.name = 'pi-desk';
    app.poll();
    assert.deepEqual(app.calls.at(-1), ['setContext', 'piDesk.selectionTerminal', true]);
    app.vscode.window.activeTerminal = undefined;
    app.events[0]();
    assert.deepEqual(app.calls.at(-1), ['setContext', 'piDesk.selectionTerminal', false]);
    assert.ok(app.calls.every(call => call[0] === 'setContext'));
    app.dispose();
});

test('native terminal selections/editors retain their stock copy bindings', () => {
    const binding = packageJson.contributes.keybindings[0];
    assert.equal(binding.when, 'terminalFocus && piDesk.selectionTerminal && !terminalTextSelected');
    assert.equal(binding.mac, 'cmd+c');
    assert.equal(binding.key, 'ctrl+shift+c');
    assert.deepEqual(packageJson.extensionKind, ['ui']);
    assert.equal(packageJson.enabledApiProposals, undefined);
});
