const net = require('net');
const { ERROR_ADDRESS_IN_USE } = require('./constants');
const { logger } = require('./logger');

/**
 * Finds an available port within the specified range, excluding specified ports.
 * @param {number} startPort - The start of the port range.
 * @param {number} endPort - The end of the port range.
 * @param {Array<number>} excludePorts - An array of ports to be skipped.
 * @returns {Promise<number>} The first available port found within the range that's not excluded.
 */
function findAvailablePort({ startPort, endPort, excludePorts = [] }) {
  return new Promise((resolve, reject) => {
    let currentPort = startPort;

    const tryPort = (port) => {
      if (excludePorts.includes(port)) {
        if (currentPort < endPort) {
          tryPort(++currentPort);
        } else {
          reject(
            new Error(
              `Unable to find an available port between ${startPort} and ${endPort} excluding specified ports.`,
            ),
          );
        }
        return;
      }
      isPortAvailable(port)
        .then((available) => {
          if (available) {
            resolve(port);
          } else if (currentPort < endPort) {
            tryPort(++currentPort);
          } else {
            reject(
              new Error(
                `Unable to find an available port between ${startPort} and ${endPort} excluding specified ports.`,
              ),
            );
          }
        })
        .catch((err) => {
          reject(
            new Error(`Error checking port: ${port} | ${JSON.stringify(err)}`),
          );
        });
    };

    tryPort(currentPort);
  });
}

/**
 * Checks if a port is available.
 * @param {number} port - The port to check.
 * @returns {Promise<boolean>} Whether the port is available.
 */
function isPortAvailable(port) {
  logger.electron(`Checking if port is available: ${port}`);
  return new Promise((resolve) => {
    const server = net.createServer();

    // If the port is available
    server.once('listening', () => {
      server.close();
      logger.electron(`Port is available: ${port}`);
      resolve(true);
    });

    // If the port is already in use
    server.once('error', (err) => {
      if (err.code === ERROR_ADDRESS_IN_USE) {
        logger.electron(`Port is NOT available: ${port}`);
        resolve(false);
      } else {
        logger.electron(
          `Error checking port: ${port} | ${JSON.stringify(err)}`,
        );
        resolve(false);
      }
    });

    // Try to listen on the specified port and host
    server.listen(port, 'localhost');
  });
}

module.exports = {
  findAvailablePort,
  isPortAvailable,
};
