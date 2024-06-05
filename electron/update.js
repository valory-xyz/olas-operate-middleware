const { MacUpdater } = require('electron-updater');
const electronLogger = require('electron-log');

const macUpdater = new MacUpdater({
  provider: 'github',
  host: 'github.com',
  protocol: 'https',
  owner: 'valory-xyz',
  channel: ['latest', 'beta', 'alpha'],
  private: false,
});

electronLogger.transports.file.level = 'info';
macUpdater.logger = electronLogger;

module.exports = { macUpdater };
