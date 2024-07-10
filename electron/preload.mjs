const { contextBridge, ipcRenderer } = require('electron/renderer');

contextBridge.exposeInMainWorld('electronAPI', {
  // App controls
  closeApp: () => ipcRenderer.send('close-app'),
  minimizeApp: () => ipcRenderer.send('minimize-app'),
  setTrayIcon: (status) => ipcRenderer.send('tray', status),
  setAppHeight: (height) => ipcRenderer.send('set-height', height),
  // IPC communication
  ipcRenderer: {
    send: (channel, data) => ipcRenderer.send(channel, data),
    on: (channel, func) =>
      ipcRenderer.on(channel, (_event, ...args) => func(...args)),
    invoke: (channel, data) => ipcRenderer.invoke(channel, data),
    removeAllListeners: (channel) => ipcRenderer.removeAllListeners(channel),
  },
  // Store interactions
  store: {
    store: () => ipcRenderer.invoke('store'),
    get: (key) => ipcRenderer.invoke('store-get', key),
    set: (key, value) => ipcRenderer.invoke('store-set', key, value),
    delete: (key) => ipcRenderer.invoke('store-delete', key),
    clear: () => ipcRenderer.invoke('store-clear'),
  },
  // Notifications
  showNotification: (title, description) =>
    ipcRenderer.send('show-notification', title, description),

  // Log exports
  openPath: (filePath) => ipcRenderer.send('open-path', filePath),
  saveLogs: (data) => ipcRenderer.invoke('save-logs', data),

  // update downloads
  startDownload: () => ipcRenderer.send('start-download'),
  quitAndInstall: () => ipcRenderer.send('install-update'),
});
