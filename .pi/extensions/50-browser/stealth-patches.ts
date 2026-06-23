export const STEALTH_INIT_SCRIPT = `
(() => {
  const defineGetter = (obj, prop, value) => {
    try {
      Object.defineProperty(obj, prop, { get: () => value, configurable: true });
    } catch {}
  };

  // Hide the most common WebDriver signal. Launching real Chrome via CDP avoids
  // --enable-automation; this is a fallback for sites checking navigator.webdriver.
  defineGetter(Navigator.prototype, 'webdriver', undefined);

  // Keep these conservative: mimic ordinary desktop Chrome without claiming an
  // impossible fingerprint. Do not overwrite userAgent/platform/vendor.
  if (navigator.languages === undefined || navigator.languages.length === 0) {
    defineGetter(Navigator.prototype, 'languages', ['en-CA', 'en-US', 'en']);
  }

  if (navigator.plugins === undefined || navigator.plugins.length === 0) {
    const fakePlugins = [
      { name: 'PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
      { name: 'Chrome PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
      { name: 'Chromium PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
      { name: 'Microsoft Edge PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
      { name: 'WebKit built-in PDF', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
    ];
    defineGetter(Navigator.prototype, 'plugins', fakePlugins);
  }

  // Match normal Chrome permission behavior more closely for notification probes.
  const originalQuery = window.navigator.permissions && window.navigator.permissions.query;
  if (originalQuery) {
    window.navigator.permissions.query = (parameters) => {
      if (parameters && parameters.name === 'notifications') {
        return Promise.resolve({ state: Notification.permission, onchange: null });
      }
      return originalQuery.call(window.navigator.permissions, parameters);
    };
  }

  // Some bot tests only check that window.chrome.runtime exists.
  if (!window.chrome) {
    Object.defineProperty(window, 'chrome', { value: {}, configurable: true });
  }
  if (!window.chrome.runtime) {
    Object.defineProperty(window.chrome, 'runtime', { value: {}, configurable: true });
  }
})();
`;
