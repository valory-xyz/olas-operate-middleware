const { publishOptions } = require('./constants');
const { MacUpdater } = require('electron-updater');
const logger = require('./logger');

const macUpdater = new MacUpdater(githubOptions);

macUpdater.setFeedURL({ ...publishOptions });

macUpdater.autoDownload = true;
macUpdater.autoInstallOnAppQuit = true;
macUpdater.logger = logger;

module.exports = { macUpdater };
