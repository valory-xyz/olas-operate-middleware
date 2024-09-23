const os = require('os');
const path = require('path');
require('dotenv').config();

const PORT_RANGE = { startPort: 39152, endPort: 65535 };
const ERROR_ADDRESS_IN_USE = 'EADDRINUSE';

// OS specific constants
const isWindows = process.platform === 'win32';
const isMac = process.platform === 'darwin';
const isLinux = process.platform === 'linux';

// Environment specific constants
const isDev = process.env.NODE_ENV === 'development';
const isProd = !isDev;

// Paths
const dotOperateDirectory = isProd
  ? path.join(os.homedir(), '.operate')
  : path.join(process.cwd(), '.operate');

const paths = {
  dotOperateDirectory,
  servicesDir: path.join(dotOperateDirectory, 'services'),
  venvDir: path.join(dotOperateDirectory, 'venv'),
  tempDir: path.join(dotOperateDirectory, 'temp'),
  versionFile: path.join(dotOperateDirectory, 'version.txt'),
  cliLogFile: path.join(dotOperateDirectory, 'cli.log'),
  electronLogFile: path.join(dotOperateDirectory, 'electron.log'),
  nextLogFile: path.join(dotOperateDirectory, 'next.log'),
  osPearlTempDir: path.join(os.tmpdir(), 'pearl'),
};

/**
 * Options for the auto-updater
 * @note electron-updater does not export the required type, so it is defined here
 * @type {{
 *  provider: 'github',
 * owner: string,
 * repo: string,
 * private: boolean,
 * publishAutoUpdate: boolean,
 * channel: string,
 * vPrefixedTagName: boolean,
 * protocol: 'https' | 'http'
 * }}
 */
const publishOptions = {
  provider: 'github',
  owner: 'valory-xyz',
  repo: 'olas-operate-app',
  private: false,
  publishAutoUpdate: true,
  channel: 'latest',
  vPrefixedTagName: true,
  protocol: 'https',
};

module.exports = {
  PORT_RANGE,
  ERROR_ADDRESS_IN_USE,
  isWindows,
  isMac,
  isLinux,
  isProd,
  isDev,
  paths,
  publishOptions,
};
