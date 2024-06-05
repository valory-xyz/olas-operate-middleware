const electronUpdater = require('electron-updater');
const electronLogger = require('electron-log');

const { publishOptions } = require('./constants/publishOptions');

const macUpdater = new electronUpdater.MacUpdater({ publishOptions });

module.exports = { macUpdater };
