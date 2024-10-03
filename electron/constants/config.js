const { isDev } = require('../constants');

require('dotenv').config();
/**
 * GitHub publish options
 * @see https://www.electron.build/auto-update#githuboptions
 * @type {{
 * releaseType: 'draft' | 'prerelease' | 'release',
 * token?: string
 * } & PearlGithubUpdateOptions}
 */

/**
 * Pearl GitHub publish options type definition
 * @see https://www.electron.build/auto-update#githuboptions
 * @typedef {{
 *  provider: 'github',
 *  owner: string,
 *  repo: string,
 *  publishAutoUpdate: boolean,
 *  channel: string,
 *  vPrefixedTagName: boolean,
 *  protocol: "https" | "http",
 *  token?: string,
 *  releaseType: 'draft' | 'prerelease' | 'release',
 * }} PearlGithubPublishOptions
 */

/**
 * GitHub update options
 * @type {PearlGithubPublishOptions} */
const githubPublishOptions = {
  provider: 'github',
  owner: 'valory-xyz',
  repo: 'olas-operate-app',
  releaseType: 'draft',
  publishAutoUpdate: true, // Publishes the update to GitHub
  vPrefixedTagName: true,
  protocol: 'https',
  channel: isDev ? 'dev' : 'latest', // Github only supports latest, dev stops overwrite
};

/**
 * Pearl GitHub update options type definition
 * @see https://www.electron.build/auto-update#githuboptions
 * @typedef {{
 * private: boolean,
 * token?: string,
 * allowPrerelease: boolean,
 * } & PearlGithubPublishOptions} PearlGithubUpdateOptions
 */

/**
 * GitHub update options
 * @see https://www.electron.build/auto-update#githuboptions
 * @type {PearlGithubUpdateOptions}
 */
const githubUpdateOptions = {
  ...githubPublishOptions,
  private: false, // Only set to true if the repo is private
  allowPrerelease: true, // Allow pre-release versions to be installed
};

module.exports = {
  githubUpdateOptions,
  githubPublishOptions,
};
