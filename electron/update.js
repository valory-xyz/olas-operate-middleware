const electronUpdater = require('electron-updater');
const electronLogger = require('electron-log');

const { githubOptions } = require('./constants/options');

const macUpdater = new electronUpdater.MacUpdater(githubOptions);

macUpdater.logger = electronLogger;

module.exports = { macUpdater };
