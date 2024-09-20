const { publishOptions } = require('./constants');
const electronUpdater = require('electron-updater');
const logger = require('./logger');

const updateOptions = {
  ...publishOptions,
  // token is not required for macUpdater as repo is public, should overwrite it to undefined
  token: undefined,
  channels: ['latest', 'beta', 'alpha'],
};

const macUpdater = new electronUpdater.MacUpdater({
  ...updateOptions,
});

macUpdater.setFeedURL({ ...updateOptions });

macUpdater.autoDownload = false;
macUpdater.autoInstallOnAppQuit = false;
macUpdater.logger = logger;

module.exports = { macUpdater };
