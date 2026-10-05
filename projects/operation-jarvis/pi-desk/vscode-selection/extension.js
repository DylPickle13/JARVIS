'use strict';

// No transcript reads, subprocesses, clipboard polling, or proposed APIs.
// tmux copies its own frozen selection only after the user's copy gesture.
const COPY_SEQUENCE = '\x1b[9001~'; // User90: consumed by pi-desk, never sent to Pi.
const CONTEXT = 'piDesk.selectionTerminal';

function isPiDesk(terminal) {
    return Boolean(terminal && terminal.name === 'pi-desk');
}

function activateWith(vscode, context) {
    let enabled;
    const update = () => {
        const next = isPiDesk(vscode.window.activeTerminal);
        if (next !== enabled) {
            enabled = next;
            void vscode.commands.executeCommand('setContext', CONTEXT, next);
        }
    };
    context.subscriptions.push(
        vscode.commands.registerCommand('piDesk.copySelection', async () => {
            // Check again on invocation; title/context polling may lag detachment.
            if (!isPiDesk(vscode.window.activeTerminal)) {
                update();
                return vscode.commands.executeCommand('workbench.action.terminal.copySelection');
            }
            return vscode.commands.executeCommand(
                'workbench.action.terminal.sendSequence', {text: COPY_SEQUENCE});
        }),
        vscode.window.onDidChangeActiveTerminal(update),
        vscode.window.onDidOpenTerminal(update),
        vscode.window.onDidCloseTerminal(update),
    );
    // Stable VS Code APIs do not expose app-supplied terminal title changes.
    // This reads only the active terminal's name, including attach/detach changes.
    const timer = setInterval(update, 250);
    context.subscriptions.push({dispose() {
        clearInterval(timer);
        void vscode.commands.executeCommand('setContext', CONTEXT, false);
    }});
    update();
}

function activate(context) {
    activateWith(require('vscode'), context);
}

module.exports = {activate, activateWith, isPiDesk, COPY_SEQUENCE};
