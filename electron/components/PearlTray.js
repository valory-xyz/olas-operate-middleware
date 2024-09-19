const Electron = require('electron');
const { isMac, isLinux, isWindows, isDev } = require('../constants');
const { logger } = require('../logger');

// Used to resize the tray icon on macOS
const macTrayIconSize = { width: 16, height: 16 };

/** Status supported by tray icons.
 * @readonly
 * @enum {string}
 */
const TrayIconStatus = {
  LoggedOut: 'logged-out',
  LowGas: 'low-gas',
  Paused: 'paused',
  Running: 'running',
};

/** Paths to tray icons for different statuses.
 * @readonly
 * @type {Record<TrayIconStatus, string>}
 */
const trayIconPaths = {
  [TrayIconStatus.LoggedOut]: `${__dirname}/../assets/icons/tray-logged-out.png`,
  [TrayIconStatus.LowGas]: `${__dirname}/../assets/icons/tray-low-gas.png`,
  [TrayIconStatus.Paused]: `${__dirname}/../assets/icons/tray-paused.png`,
  [TrayIconStatus.Running]: `${__dirname}/../assets/icons/tray-running.png`,
};

/** Tray icons as native images
 * @note macOS icons are resized
 * @readonly
 * @type {Record<TrayIconStatus, Electron.NativeImage | string>} */
const trayIcons = Object.entries(trayIconPaths).reduce(
  (acc, [status, path]) => ({
    ...acc,
    [status]: (() => {
      // Linux does not support nativeImage
      if (isLinux) return path;

      // Windows and macOS support nativeImage
      const trayIcon = Electron.nativeImage.createFromPath(path);

      // Resize icon for macOS
      if (isMac) trayIcon.resize(macTrayIconSize);

      return trayIcon;
    })(),
  }),
  {},
);

/** Cross-platform Electron Tray for Pearl, with context menu, icon, events. */
class PearlTray extends Electron.Tray {
  /** @param {() => Electron.BrowserWindow | null} activeWindowCallback */
  constructor(activeWindowCallback) {
    // Set the tray icon to the logged-out state by default
    super(trayIcons[TrayIconStatus.LoggedOut]);

    // Store the callback to retrieve the active window
    this.activeWindowCallback = activeWindowCallback;

    this.setContextMenu(new PearlTrayContextMenu(activeWindowCallback));
    this.setToolTip('Pearl');

    this.#bindClickEvents();
    this.#bindIpcListener();
  }

  #bindClickEvents = () => {
    if (isMac) {
      isDev && logger.electron('binding mac click events to tray');
      // macOS: Only handle the click to show window or context menu with right-click
      this.on('click', () => this.activeWindowCallback()?.show());
      this.on('right-click', () => this.popUpContextMenu());
    } else if (isLinux) {
      isDev && logger.electron('binding linux click events to tray');
      // Linux: events are not working as expected, only context menu shows
      // this.on('click', () => this.activeWindowCallback()?.show());
      // this.on('double-click', () => this.activeWindowCallback()?.show());
      // this.on('right-click', () => this.popUpContextMenu());
    } else if (isWindows) {
      isDev && logger.electron('binding windows click events to tray');
      // Windows: Handle single and double-clicks to show the window
      this.on('click', () => this.activeWindowCallback()?.show());
      this.on('double-click', () => this.activeWindowCallback()?.show());
      this.on('right-click', () => this.popUpContextMenu());
    }
  };

  #bindIpcListener = () => {
    isDev && logger.electron('binding ipc listener for tray icon status');
    Electron.ipcMain.on('tray', (_event, status) => {
      isDev && logger.electron('received tray icon status:', status);
      switch (status) {
        case TrayIconStatus.LoggedOut: {
          this.setImage(trayIcons.LOGGED_OUT);
          break;
        }
        case TrayIconStatus.Running: {
          this.setImage(trayIcons.RUNNING);
          break;
        }
        case TrayIconStatus.Paused: {
          this.setImage(trayIcons.PAUSED);
          break;
        }
        case TrayIconStatus.LowGas: {
          this.setImage(trayIcons.LOW_GAS);
          break;
        }
        default: {
          console.error('Unknown tray icon status:', status);
        }
      }
    });
  };
}

/**
 * Builds the context menu for the tray.
 * @param {() => Electron.BrowserWindow | null} activeWindowCallback - A callback to retrieve the active window.
 * @returns {Electron.Menu} The context menu for the tray.
 */
class PearlTrayContextMenu {
  constructor(activeWindowCallback) {
    return Electron.Menu.buildFromTemplate([
      {
        label: 'Show app',
        click: () => activeWindowCallback()?.show(),
      },
      {
        label: 'Hide app',
        click: () => activeWindowCallback()?.hide(),
      },
      {
        label: 'Quit',
        click: async () => {
          Electron.app.quit();
        },
      },
    ]);
  }
}

module.exports = { PearlTray };
