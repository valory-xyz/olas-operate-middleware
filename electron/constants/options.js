/** @implements import { GithubOptions } from 'electron-updater' */

const githubOptions = {
  provider: 'github',
  owner: 'valory-xyz',
  repo: 'olas-operate-app',
  private: false,
};

const githubPublishOptions = {
  releaseType: 'draft',
  publishAutoUpdate: true,
  token: process.env.GH_TOKEN,
  ...githubOptions,
};

module.exports = { githubPublishOptions, githubOptions };
