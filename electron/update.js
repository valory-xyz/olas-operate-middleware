const electronUpdater = require('electron-updater');
const electronLogger = require('electron-log');

const { publishOptions } = require('./constants/publishOptions');

const setupMacUpdater = (app) => {
  /** @type import type { MacUpdater } from "electron-updater" */
  const macUpdater = new electronUpdater.MacUpdater(
    { publishOptions, token: undefined },
    app,
  );

  macUpdater.logger = electronLogger;

  return {
    macUpdater,
  };
};

module.exports = { setupMacUpdater };
