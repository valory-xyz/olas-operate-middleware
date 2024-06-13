const { contextBridge, ipcRenderer } = require('electron/renderer');

contextBridge.exposeInMainWorld('electronAPI', {
  // for sending and recieving messages from main process
  ipcRenderer: {
    send: (channel, data) => ipcRenderer.send(channel, data),
    on: (channel, func) =>
      ipcRenderer.on(channel, (_event, ...args) => func(...args)),
    invoke: (channel, data) => ipcRenderer.invoke(channel, data),
    removeAllListeners: (channel) => ipcRenderer.removeAllListeners(channel),
  },

  // system store
  store: {
    store: () => ipcRenderer.invoke('store'),
    get: (key) => ipcRenderer.invoke('store-get', key),
    set: (key, value) => ipcRenderer.invoke('store-set', key, value),
    delete: (key) => ipcRenderer.invoke('store-delete', key),
    clear: () => ipcRenderer.invoke('store-clear'),
  },

  // app manipulation
  closeApp: () => ipcRenderer.send('close-app'),
  minimizeApp: () => ipcRenderer.send('minimize-app'),
  setAppHeight: (height) => ipcRenderer.send('set-height', height),

  // icons & statuses
  setTrayIcon: (status) => ipcRenderer.send('tray', status),

  // notifications
  showNotification: (title, description) =>
    ipcRenderer.send('show-notification', title, description),

  // logs
  saveLogs: (data) => ipcRenderer.invoke('save-logs', data),
  openPath: (filePath) => ipcRenderer.send('open-path', filePath),

  // update downloads
  checkUpdates: () => ipcRenderer.invoke('check-for-updates'),
  startDownload: () => ipcRenderer.invoke('start-download'),
  quitAndInstall: () => ipcRenderer.invoke('install-update'),
});
