// const { publishOptions } = require('./constants/publishOptions');
// const electronUpdater = require('electron-updater');
// const electronLogger = require('electron-log');

// const macUpdater = new electronUpdater.MacUpdater({
//   ...publishOptions,
// });

// macUpdater.logger = electronLogger;

// macUpdater.setFeedURL({
//   ...publishOptions,
// });

// macUpdater.autoDownload = true;
// macUpdater.autoInstallOnAppQuit = true;
// macUpdater.logger = electronLogger;

const { publishOptions } = require("../constants/publishOptions");
const electronUpdater = require("electron-updater");
const electronLogger = require("electron-log");

macUpdater.logger = electronLogger;

export const setupMacUpdater = (app) => {
  /** @type import type { MacUpdater } from "electron-updater" */
  const macUpdater = new electronUpdater.MacUpdater(
    {
      ...publishOptions,
    },
    app
  );

  macUpdater.logger = electronLogger;

  return {
    macUpdater,
  };
};

module.exports = { macUpdater };
