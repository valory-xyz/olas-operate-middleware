const Store = require('electron-store');

const defaultAgentSettings = {
  isInitialFunded: { type: 'boolean', default: false },
  firstStakingRewardAchieved: { type: 'boolean', default: false },
  firstRewardNotificationShown: { type: 'boolean', default: false },
  agentEvictionAlertShown: { type: 'boolean', default: false },
  currentStakingProgram: { type: 'string', default: '' },
};

// set schema to validate store data
const schema = {
  environmentName: { type: 'string', default: '' },
  lastSelectedAgentType: { type: 'string', default: 'trader' },
  isInitialFunded_trader: { type: 'boolean', default: false },
  isInitialFunded_memeooorr: { type: 'boolean', default: false },

  // each agent has its own settings
  trader: { ...defaultAgentSettings },
  memeooorr: { ...defaultAgentSettings },
};

/**
 * Sets up the IPC communication and initializes the Electron store with default values and schema.
 * @param {Electron.IpcMain} ipcMain - The IPC channel for communication.
 * @param {Electron.BrowserWindow} mainWindow - The main Electron browser window.
 * @returns {Promise<void>} - A promise that resolves once the store is set up.
 */
const setupStoreIpc = (ipcMain, mainWindow) => {
  const store = new Store({ schema });

  /**
   * agent: trader Migration
   *
   * Initially the store was setup with only trader agent settings.
   * The following code migrates the old store to the new store schema.
   */
  const traderAgent = {
    ...store(store.get('trader') || {}),
    isInitialFunded:
      store.get('isInitialFunded_trader') || store.get('isInitialFunded'),
    firstRewardNotificationShown: store.get('firstRewardNotificationShown'),
    agentEvictionAlertShown: store.get('agentEvictionAlertShown'),
    currentStakingProgram: store.get('currentStakingProgram'),
  };

  // set the agent & delete old keys
  store.set('trader', traderAgent);
  store.delete('isInitialFunded');
  store.delete('isInitialFunded_trader');
  store.delete('firstStakingRewardAchieved');
  store.delete('firstRewardNotificationShown');
  store.delete('agentEvictionAlertShown');
  store.delete('currentStakingProgram');

  /**
   * agent: memeooorr Migration
   */
  if (store.has('isInitialFunded_memeooorr')) {
    const memeooorrAgent = store.get('memeooorr');
    store.set('memeooorr', {
      ...memeooorrAgent,
      isInitialFunded: store.get('isInitialFunded_memeooorr') || false,
    });
    store.delete('isInitialFunded_memeooorr');
  }

  store.onDidAnyChange((data) => {
    if (mainWindow?.webContents)
      mainWindow.webContents.send('store-changed', data);
  });

  // exposed to electron browser window
  ipcMain.handle('store', () => store.store);
  ipcMain.handle('store-get', (_, key) => store.get(key));
  ipcMain.handle('store-set', (_, key, value) => store.set(key, value));
  ipcMain.handle('store-delete', (_, key) => store.delete(key));
  ipcMain.handle('store-clear', (_) => store.clear());
};

module.exports = { setupStoreIpc };
