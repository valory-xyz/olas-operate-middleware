const { MacUpdater } = require('electron-updater');
const electronLogger = require('electron-log');
const { githubOptions } = require('./constants/config');

const macUpdater = new MacUpdater(githubOptions);

electronLogger.transports.file.level = 'info';
macUpdater.logger = electronLogger;
macUpdater.autoDownload = false;
macUpdater.autoInstallOnAppQuit = false;
macUpdater.channel = 'latest';

module.exports = { macUpdater };
