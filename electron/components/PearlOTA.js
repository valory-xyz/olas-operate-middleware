const { MacUpdater, NsisUpdater } = require('electron-updater');
const { logger } = require('../logger');
const { publishOptions, isWindows, isMac } = require('../constants');

/** Over-the-air update manager
 * @property {NsisUpdater | MacUpdater} updater - The updater instance
 * @example
 * const { PearlOTA } = require('./PearlOTA');
 * const ota = new PearlOTA();
 * ota.updater.checkForUpdates();
 * ota.updater.downloadUpdate();
 * ota.updater.quitAndInstall();
 * @see https://www.electron.build/auto-update
 * @note updater only supports Windows and Mac
 */
class PearlOTA {
  updater = null;
  constructor() {
    if (isWindows) this.updater = new NsisUpdater(publishOptions);
    if (isMac) this.updater = new MacUpdater(publishOptions);

    if (!this.updater) {
      logger.electron.error('Unsupported platform for auto-updates');
      return null;
    }

    this.updater.autoDownload = false;
    this.updater.autoInstallOnAppQuit = false;
    this.updater.logger = logger.electron;

    this.#bindUpdaterEvents();
  }

  /** Binds events to the updater
   */
  #bindUpdaterEvents = () => {
    this.updater.on('error', (error) => {
      logger.electron.error('Update error:', error);
    });
    this.updater.on('update-available', () => {
      logger.electron.info('Update available');
    });
    this.updater.on('update-not-available', () => {
      logger.electron.info('No update available');
    });
    this.updater.on('checking-for-update', () => {
      logger.electron.info('Checking for update');
    });
    this.updater.on('download-progress', (progress) => {
      logger.electron.info('Download progress:', progress);
    });
    this.updater.on('update-not-available', () => {
      logger.electron.info('No update available');
    });
  };
}

module.exports = {
  PearlOTA,
};
