const electronLogger = require('electron-log');
const { githubOptions } = require('./constants/config');
const { MacUpdater } = require('electron-updater');

const macUpdater = new MacUpdater(githubOptions);

electronLogger.transports.file.level = 'debug';
macUpdater.logger = electronLogger;
macUpdater.autoDownload = false;
macUpdater.autoInstallOnAppQuit = false;

module.exports = { macUpdater };
