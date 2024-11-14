const {
  app,
  BrowserWindow,
  Notification,
  ipcMain,
  dialog,
  shell,
} = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const os = require('os');
const next = require('next/dist/server/next');
const http = require('http');
const AdmZip = require('adm-zip');

const { setupDarwin, setupUbuntu, setupWindows, Env } = require('./install');

const { paths } = require('./constants');
const { killProcesses } = require('./processes');
const { isPortAvailable, findAvailablePort } = require('./ports');
const { PORT_RANGE } = require('./constants');
const { setupStoreIpc } = require('./store');
const { logger } = require('./logger');
const { isDev, isProd } = require('./constants');
const { PearlTray } = require('./components/PearlTray');

// Attempt to acquire the single instance lock
const singleInstanceLock = app.requestSingleInstanceLock();

if (!singleInstanceLock) {
  try {
    logger.electron('Could not obtain single instance lock. Quitting...');
  } catch (e) {
    console.error(e);
  } finally {
    app.exit();
  }
}

const platform = os.platform();

const binaryPaths = {
  darwin: {
    arm64: 'bins/pearl_arm64',
    x64: 'bins/pearl_x64',
  },
  win32: {
    x64: 'bins/pearl_win.exe',
  },
};

/**
 * @note - Ports are overwritten if they are already in use.
 */
let portConfig = {
  ports: {
    dev: {
      operate: 8000,
      next: 3000,
    },
    prod: {
      operate: 8765,
      next: 3000,
    },
  },
};

/** @type {Electron.BrowserWindow | null} */
let mainWindow = null;
/** @type {Electron.BrowserWindow | null} */
let splashWindow = null;

/** @type {Electron.Tray | null} */
let tray = null;

// Used in production and development
let operateDaemon;
let operateDaemonPid;

// Child processes for running next app are only used in development
// required for hot reloads and other dev features
let devNextApp;
let devNextAppPid;

// Next.js app instance for production
// requires http server wrap to work; assign port, receive requests, deliver responses
/**
 * @note - The Next.js app instance used to serve the frontend application in production.
 * @note - Envs configured in `/frontend/next.config.mjs`, don't pass them here.
 * @type {import('next/dist/server/next').NextServer | null}
 */
let prodNextApp = isProd
  ? next({
      dev: false,
      dir: path.join(__dirname),
    })
  : null;

const getActiveWindow = () => splashWindow ?? mainWindow;

function showNotification(title, body) {
  new Notification({ title, body }).show();
}

async function beforeQuit() {
  // destroy all ui components for immediate feedback
  tray?.destroy();
  splashWindow?.destroy();
  mainWindow?.destroy();

  if (operateDaemon || operateDaemonPid) {
    // gracefully stop running services
    try {
      const operatePort = isDev
        ? portConfig.ports.dev.operate
        : portConfig.ports.prod.operate;
      await fetch(`http://localhost:${operatePort}/stop_all_services`);
    } catch (e) {
      logger.electron("Couldn't stop_all_services gracefully:");
      logger.electron(JSON.stringify(e));
    }

    // clean-up via pid first*
    // may have dangling subprocesses
    try {
      operateDaemonPid && (await killProcesses(operateDaemonPid));
    } catch (e) {
      logger.electron("Couldn't kill daemon processes via pid:");
      logger.electron(JSON.stringify(e));
    }

    // attempt to kill the daemon process via kill
    // if the pid-based cleanup fails
    try {
      const dead = operateDaemon?.kill();
      if (!dead) {
        logger.electron('Daemon process still alive after kill');
      }
    } catch (e) {
      logger.electron("Couldn't kill operate daemon process via kill:");
      logger.electron(JSON.stringify(e));
    }
  }

  if (devNextApp || devNextAppPid) {
    // attempt graceful kill first with next app
    try {
      const dead = devNextApp?.kill();
      if (!dead) {
        logger.electron('Dev NextApp process still alive after kill');
      }
    } catch (e) {
      logger.electron("Couldn't kill devNextApp process via kill:");
      logger.electron(JSON.stringify(e));
    }

    // attempt to kill the dev next app process via pid
    try {
      devNextAppPid && (await killProcesses(devNextAppPid));
    } catch (e) {
      logger.electron("Couldn't kill devNextApp processes via pid:");
      logger.electron(JSON.stringify(e));
    }
  }

  if (prodNextApp) {
    // attempt graceful close of prod next app
    await prodNextApp.close().catch((e) => {
      logger.electron("Couldn't close NextApp gracefully:");
      logger.electron(JSON.stringify(e));
    });
    // electron will kill next service on exit
  }
}

const APP_WIDTH = 460;

/**
 * Creates the splash window
 */
const createSplashWindow = () => {
  /** @type {Electron.BrowserWindow} */
  splashWindow = new BrowserWindow({
    width: APP_WIDTH,
    height: APP_WIDTH,
    resizable: false,
    show: true,
    title: 'Pearl',
    frame: false,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false,
    },
  });
  splashWindow.loadURL('file://' + __dirname + '/loading/index.html');

  if (isDev) {
    splashWindow.webContents.openDevTools({
      mode: 'detach',
    });
  }
};

const HEIGHT = 700;
/**
 * Creates the main window
 */
const createMainWindow = async () => {
  const width = isDev ? 840 : APP_WIDTH;
  mainWindow = new BrowserWindow({
    title: 'Pearl',
    resizable: false,
    draggable: true,
    frame: false,
    transparent: true,
    fullscreenable: false,
    maximizable: false,
    width,
    maxHeight: HEIGHT,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
    },
  });

  mainWindow.setMenuBarVisibility(true);

  ipcMain.on('close-app', () => {
    mainWindow?.close();
  });

  ipcMain.on('minimize-app', () => {
    mainWindow?.minimize();
  });

  app.on('activate', () => {
    if (mainWindow?.isMinimized()) {
      mainWindow?.restore();
    } else {
      mainWindow?.show();
    }
  });

  ipcMain.on('set-height', (_event, height) => {
    mainWindow?.setSize(width, height);
  });

  ipcMain.on('show-notification', (_event, title, description) => {
    showNotification(title, description || undefined);
  });

  // if app (ie. mainWindow) is loaded, destroy splash window.
  ipcMain.on('is-app-loaded', (_event, isLoaded) => {
    if (isLoaded && splashWindow) {
      splashWindow.destroy();
      splashWindow = null;
    }
  });

  ipcMain.handle('app-version', () => app.getVersion());

  mainWindow.webContents.on('did-fail-load', () => {
    mainWindow.webContents.reloadIgnoringCache();
  });

  mainWindow.webContents.on('ready-to-show', () => {
    mainWindow.show();
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    // open url in a browser and prevent default
    require('electron').shell.openExternal(url);
    return { action: 'deny' };
  });

  mainWindow.on('close', function (event) {
    event.preventDefault();
    mainWindow.hide();
  });

  try {
    logger.electron('Setting up store IPC');
    await setupStoreIpc(ipcMain, mainWindow);
  } catch (e) {
    logger.electron('Store IPC failed:', JSON.stringify(e));
  }

  if (isDev) {
    mainWindow.webContents.openDevTools();
  }

  if (isDev) {
    mainWindow.loadURL(`http://localhost:${portConfig.ports.dev.next}`);
  } else {
    mainWindow.loadURL(`http://localhost:${portConfig.ports.prod.next}`);
  }
};

async function launchDaemon() {
  // Free up backend port if already occupied
  try {
    await fetch(`http://localhost:${portConfig.ports.prod.operate}/api`);
  } catch (err) {
    logger.electron('Backend `api` endpoint did not respond');
    logger.electron(JSON.stringify(err));
  }

  try {
    logger.electron('Attempting to kill hanging backend server instances');

    let endpoint = fs
      .readFileSync(`${paths.dotOperateDirectory}/operate.kill`)
      .toString()
      .trim();

    await fetch(
      `http://localhost:${portConfig.ports.prod.operate}/${endpoint}`,
    );
  } catch (err) {
    logger.electron(
      `Error killing backend server: ${JSON.stringify(err)} (Backend server may not exist)`,
    );
  }

  // TODO: rename, check is not a useful name
  const check = new Promise(function (resolve, _reject) {
    operateDaemon = spawn(
      path.join(
        process.resourcesPath,
        binaryPaths[platform][process.arch.toString()],
      ),
      [
        'daemon',
        `--port=${portConfig.ports.prod.operate}`,
        `--home=${paths.dotOperateDirectory}`,
      ],
      { env: Env },
    );
    operateDaemonPid = operateDaemon.pid;
    // fs.appendFileSync(
    //   `${paths.OperateDirectory}/operate.pip`,
    //   `${operateDaemon.pid}`,
    //   {
    //     encoding: 'utf-8',
    //   },
    // );

    operateDaemon.stderr.on('data', (data) => {
      if (data.toString().includes('Uvicorn running on')) {
        resolve({ running: true, error: null });
      }
      if (
        data.toString().includes('error while attempting to bind on address')
      ) {
        resolve({ running: false, error: 'Port already in use' });
      }
      logger.cli(data.toString().trim());
    });
    operateDaemon.stdout.on('data', (data) => {
      logger.cli(data.toString().trim());
    });
  });

  return await check;
}

async function launchDaemonDev() {
  const check = new Promise(function (resolve, _reject) {
    operateDaemon = spawn('poetry', [
      'run',
      'operate',
      'daemon',
      `--port=${portConfig.ports.dev.operate}`,
      '--home=.operate',
    ]);
    operateDaemonPid = operateDaemon.pid;
    operateDaemon.stderr.on('data', (data) => {
      if (data.toString().includes('Uvicorn running on')) {
        resolve({ running: true, error: null });
      }
      if (
        data.toString().includes('error while attempting to bind on address')
      ) {
        resolve({ running: false, error: 'Port already in use' });
      }
      logger.cli(data.toString().trim());
    });
    operateDaemon.stdout.on('data', (data) => {
      logger.cli(data.toString().trim());
    });
  });
  return await check;
}

async function launchNextApp() {
  logger.electron('Launching Next App');

  logger.electron('Preparing Next App');
  await prodNextApp.prepare();

  logger.electron('Getting Next App Handler');
  const handle = prodNextApp.getRequestHandler();

  logger.electron('Creating Next App Server');
  const server = http.createServer((req, res) => {
    handle(req, res); // Handle requests using the Next.js request handler
  });

  logger.electron('Listening on Next App Server');
  server.listen(portConfig.ports.prod.next, () => {
    logger.next(
      `> Next server running on http://localhost:${portConfig.ports.prod.next}`,
    );
  });
}

async function launchNextAppDev() {
  await new Promise(function (resolve, _reject) {
    devNextApp = spawn(
      'yarn',
      ['dev:frontend', '--port', portConfig.ports.dev.next],
      {
        shell: true,
        env: {
          ...process.env,
          MIDDLEWARE_PORT: portConfig.ports.dev.operate,
          NEXT_PUBLIC_PEARL_VERSION: app.getVersion(),
        },
      },
    );
    devNextAppPid = devNextApp.pid;
    devNextApp.stdout.on('data', (data) => {
      logger.next(data.toString().trim());
      resolve();
    });
  });
}

ipcMain.on('check', async function (event, _argument) {
  // Update
  try {
    // macUpdater.checkForUpdates().then((res) => {
    //   if (!res) return;
    //   if (!res.downloadPromise) return;
    //   new Notification({
    //     title: 'Update Available',
    //     body: 'Downloading update...',
    //   }).show();
    //   res.downloadPromise.then(() => {
    //     new Notification({
    //       title: 'Update Downloaded',
    //       body: 'Restarting application...',
    //     }).show();
    //     macUpdater.quitAndInstall();
    //   });
    // });
  } catch (e) {
    logger.electron(e);
  }

  // Setup
  try {
    event.sender.send('response', 'Checking installation');

    if (platform === 'darwin') {
      await setupDarwin(event.sender);
    } else if (platform === 'win32') {
      await setupWindows(event.sender);
    } else {
      await setupUbuntu(event.sender);
    }

    if (isDev) {
      event.sender.send(
        'response',
        'Starting Pearl Daemon In Development Mode',
      );

      const daemonDevPortAvailable = await isPortAvailable(
        portConfig.ports.dev.operate,
      );

      if (!daemonDevPortAvailable) {
        portConfig.ports.dev.operate = await findAvailablePort({
          ...PORT_RANGE,
        });
      }
      await launchDaemonDev();
      event.sender.send(
        'response',
        'Starting Frontend Server In Development Mode',
      );

      const frontendDevPortAvailable = await isPortAvailable(
        portConfig.ports.dev.next,
      );

      if (!frontendDevPortAvailable) {
        portConfig.ports.dev.next = await findAvailablePort({
          ...PORT_RANGE,
          excludePorts: [portConfig.ports.dev.operate],
        });
      }
      await launchNextAppDev();
    } else {
      event.sender.send('response', 'Starting Pearl Daemon');
      await launchDaemon();

      event.sender.send('response', 'Starting Frontend Server');
      const frontendPortAvailable = await isPortAvailable(
        portConfig.ports.prod.next,
      );
      if (!frontendPortAvailable) {
        portConfig.ports.prod.next = await findAvailablePort({
          ...PORT_RANGE,
          excludePorts: [portConfig.ports.prod.operate],
        });
      }
      await launchNextApp();
    }

    event.sender.send('response', 'Launching App');
    await createMainWindow();
    tray = new PearlTray(getActiveWindow);
  } catch (e) {
    logger.electron(e);
    new Notification({
      title: 'Error',
      body: e,
    }).show();
    event.sender.send('response', e);
    // app.quit();
  }
});

// APP-SPECIFIC EVENTS
app.on('second-instance', () => {
  logger.electron('User attempted to open a second instance.');

  if (mainWindow) {
    logger.electron('Restoring primary main window.');
    mainWindow.show();
    return;
  }

  if (splashWindow) {
    logger.electron(
      'Restoring primary splash window as there is no main window.',
    );
    splashWindow.show();
    return;
  }
});

app.once('ready', async () => {
  app.on('window-all-closed', () => {
    app.quit();
  });

  app.on('before-quit', async () => {
    await beforeQuit();
  });

  if (platform === 'darwin') {
    app.dock?.setIcon(
      path.join(__dirname, 'assets/icons/splash-robot-head-dock.png'),
    );
  }

  // check ports are available
  if (process.env.NODE_ENV === 'production') {
    const isMiddlewarePortAvailable = await isPortAvailable(
      portConfig.ports.prod.operate,
    );
    if (!isMiddlewarePortAvailable) {
      portConfig.ports.prod.operate = await findAvailablePort({
        ...PORT_RANGE,
      });
    }

    const isNextPortAvailable = await isPortAvailable(
      portConfig.ports.prod.next,
    );
    if (!isNextPortAvailable) {
      portConfig.ports.prod.next = await findAvailablePort({
        ...PORT_RANGE,
        excludePorts: [portConfig.ports.prod.operate],
      });
    }
  } else {
    // development checks
    const isMiddlewarePortAvailable = await isPortAvailable(
      portConfig.ports.dev.operate,
    );

    if (!isMiddlewarePortAvailable) {
      portConfig.ports.dev.operate = await findAvailablePort({
        ...PORT_RANGE,
      });
    }

    const devNextPortAvailable = await isPortAvailable(
      portConfig.ports.dev.next,
    );

    if (!devNextPortAvailable) {
      portConfig.ports.dev.next = await findAvailablePort({
        ...PORT_RANGE,
        excludePorts: [portConfig.ports.dev.operate],
      });
    }
  }

  createSplashWindow();
});

// PROCESS SPECIFIC EVENTS (HANDLES NON-GRACEFUL TERMINATION)
process.on('uncaughtException', (error) => {
  logger.electron('Uncaught Exception:', error);
  // Clean up your child processes here
  beforeQuit().then(() => {
    process.exit(1); // Exit with a failure code
  });
});

['SIGINT', 'SIGTERM'].forEach((signal) => {
  process.on(signal, () => {
    logger.electron(`Received ${signal}. Cleaning up...`);
    beforeQuit().then(() => {
      process.exit(0);
    });
  });
});

// OPEN PATH
ipcMain.on('open-path', (_, filePath) => {
  shell.openPath(filePath);
});

/**
 * Sanitizes logs by replacing usernames in the log data with asterisks.
 * If a file path is provided, it reads the log data from the file and sanitizes it.
 * If the file path does not exist, it returns null.
 * If no file path is provided, it sanitizes the provided data directly.
 * The sanitized log data is then written to the destination path.
 * @param {Object} options - The options for sanitizing logs.
 * @param {string} options.name - The name of the log file.
 * @param {string} options.filePath - The file path to read the log data from.
 * @param {string} options.data - The log data to sanitize if no file path is provided.
 * @param {string} options.destPath - The destination path where the logs should be stored after sanitization.
 * @returns {string|null} - The file path of the sanitized log data, or null if the file path does not exist.
 */
function sanitizeLogs({
  name,
  filePath,
  data = '',
  destPath = paths.osPearlTempDir,
}) {
  if (filePath && !fs.existsSync(filePath)) return null;

  const logs = filePath ? fs.readFileSync(filePath, 'utf-8') : data;

  const usernameRegex = /\/(Users|home)\/([^/]+)/g;
  const sanitizedData = logs.replace(usernameRegex, '/$1/*****');
  const sanitizedLogsFilePath = path.join(destPath, name);

  if (!fs.existsSync(destPath)) fs.mkdirSync(destPath);

  fs.writeFileSync(sanitizedLogsFilePath, sanitizedData);

  return sanitizedLogsFilePath;
}

// EXPORT LOGS
ipcMain.handle('save-logs', async (_, data) => {
  sanitizeLogs({
    name: 'cli.log',
    filePath: paths.cliLogFile,
  });

  sanitizeLogs({
    name: 'next.log',
    filePath: paths.nextLogFile,
  });

  sanitizeLogs({
    name: 'electron.log',
    filePath: paths.electronLogFile,
  });

  // OS info
  const osInfo = `
    OS Type: ${os.type()}
    OS Platform: ${os.platform()}
    OS Arch: ${os.arch()}
    OS Release: ${os.release()}
    Total Memory: ${os.totalmem()}
    Free Memory: ${os.freemem()}
  `;
  const osInfoFilePath = path.join(paths.osPearlTempDir, 'os_info.txt');
  fs.writeFileSync(osInfoFilePath, osInfo);

  // Persistent store
  if (data.store)
    sanitizeLogs({
      name: 'store.txt',
      data: JSON.stringify(data.store, null, 2),
    });

  // Other debug data: balances, addresses, etc.
  if (data.debugData)
    sanitizeLogs({
      name: 'debug_data.txt',
      data: JSON.stringify(data.debugData, null, 2),
    });

  // Agent logs
  try {
    fs.readdirSync(paths.servicesDir).map((serviceDirName) => {
      const servicePath = path.join(paths.servicesDir, serviceDirName);
      if (!fs.existsSync(servicePath)) return;
      if (!fs.statSync(servicePath).isDirectory()) return;

      const agentLogFilePath = path.join(
        servicePath,
        'deployment',
        'agent',
        'log.txt',
      );
      if (!fs.existsSync(agentLogFilePath)) return;

      return sanitizeLogs({
        name: `${serviceDirName}_agent.log`,
        filePath: agentLogFilePath,
      });
    });
  } catch (e) {
    logger.electron(e);
  }

  // Create a zip archive
  const zip = new AdmZip();
  fs.readdirSync(paths.osPearlTempDir).forEach((file) => {
    const filePath = path.join(paths.osPearlTempDir, file);
    if (!fs.existsSync(filePath)) return;
    if (fs.statSync(filePath).isDirectory()) return;

    zip.addLocalFile(filePath);
  });

  // Show save dialog
  const { filePath } = await dialog.showSaveDialog({
    title: 'Save Logs',
    defaultPath: path.join(
      os.homedir(),
      `pearl_logs_${new Date(Date.now())
        .toISOString()
        .replaceAll(':', '-')}-${app.getVersion()}.zip`,
    ),
    filters: [{ name: 'Zip Files', extensions: ['zip'] }],
  });

  let result;
  if (filePath) {
    // Write the zip file to the selected path
    zip.writeZip(filePath);
    result = { success: true, dirPath: path.dirname(filePath) };
  } else {
    result = { success: false };
  }

  // Remove temporary files
  fs.existsSync(paths.osPearlTempDir) &&
    fs.rmSync(paths.osPearlTempDir, {
      recursive: true,
      force: true,
    });

  return result;
});
