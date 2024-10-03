const { isDev } = require('../constants');

require('dotenv').config();

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
 *  releaseType: 'draft' | 'prerelease' | 'release',
 *  token?: string,
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

module.exports = {
  githubPublishOptions,
};
