// Exact, version-pinned edits applied by the existing dependency patcher only.
// Hooks observe execution; none changes focus, command payloads, or tool schemas.
export function patchObservedExecution(source) {
  const key = "globalThis[Symbol.for('jarvis.browser.execution-observer.v1')]";
  const replacements = [
    [
      'const toolResult = await backend.callTool(request2.params.name, request2.params.arguments || {}, extra.signal);',
      `// JARVIS_EXECUTION_REQUEST_V1\n      const jarvisObserver = ${key};\n      const invokeJarvisRequest = () => backend.callTool(request2.params.name, request2.params.arguments || {}, extra.signal);\n      const toolResult = await (jarvisObserver ? jarvisObserver.request(request2.params.arguments?.code, invokeJarvisRequest) : invokeJarvisRequest());`,
    ],
    [
      'context.__fn__ = import_vm.default.runInContext("(" + code + ")", context);',
      `context.__fn__ = import_vm.default.runInContext("(" + code + ")", context);\n            // JARVIS_EXECUTION_SNIPPET_V1\n            context.__jarvisRunSnippet__ = () => {\n              const observer = ${key};\n              const invoke = () => context.__fn__(context.page);\n              return observer ? observer.snippet(code, invoke) : invoke();\n            };`,
    ],
    ['const result = await __fn__(page);', 'const result = await __jarvisRunSnippet__();'],
    [
      'const id = ++this._lastId;\n        this._ws.send(JSON.stringify({ id, method, params: params2 }));\n        const error = new Error(`Protocol error: ${method}`);\n        return new Promise((resolve, reject) => {\n          this._callbacks.set(id, { resolve, reject, error });\n        });',
      `// JARVIS_EXECUTION_RELAY_V1\n        const id = ++this._lastId;\n        const jarvisReceipt = ${key}?.command(this);\n        try { this._ws.send(JSON.stringify({ id, method, params: params2 })); }\n        catch (error) { ${key}?.unknown(jarvisReceipt); throw error; }\n        const error = new Error(\`Protocol error: \${method}\`);\n        return new Promise((resolve, reject) => {\n          this._callbacks.set(id, { resolve, reject, error, jarvisReceipt });\n        });`,
    ],
    [
      'const callback = this._callbacks.get(object.id);\n          this._callbacks.delete(object.id);\n          if (object.error) {\n            const error = callback.error;',
      `const callback = this._callbacks.get(object.id);\n          // JARVIS_EXECUTION_ACK_V1\n          ${key}?.acknowledge(callback.jarvisReceipt);\n          this._callbacks.delete(object.id);\n          if (object.error) {\n            const error = callback.error;`,
    ],
    [
      'for (const callback of this._callbacks.values())\n          callback.reject(new Error("WebSocket closed"));\n        this._callbacks.clear();',
      `// JARVIS_EXECUTION_LOSS_V1\n        for (const callback of this._callbacks.values()) {\n          ${key}?.unknown(callback.jarvisReceipt);\n          callback.reject(new Error("WebSocket closed"));\n        }\n        this._callbacks.clear();`,
    ],
  ];
  for (const [index, [before, after]] of replacements.entries()) {
    const count=source.split(after).length-1;
    if (count===1) continue;
    const marker=after.match(/JARVIS_EXECUTION_\w+/)?.[0];
    if (count>1 || (marker && source.includes(marker)) || source.split(before).length !== 2) throw new Error(`Observed execution patch anchor ${index} changed`);
    source = source.replace(before, after);
  }
  return source;
}
