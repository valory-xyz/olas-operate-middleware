/** @implements import { GithubOptions } from 'electron-updater' */
const publishOptions = {
  provider: 'github',
  owner: 'valory-xyz',
  repo: 'olas-operate-app',
  releaseType: 'draft',
  private: false,
  publishAutoUpdate: true,
  token: process.env.GH_TOKEN,
};

module.exports = { publishOptions };
