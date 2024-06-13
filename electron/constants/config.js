const githubOptions = {
  releaseType: 'draft',
  publishAutoUpdate: true,
  provider: 'github',
  owner: 'valory-xyz',
  repo: 'olas-operate-app',
  private: false,
  protocol: 'https',
  channel: 'latest',
  vPrefixedTagName: true,
};

module.exports = { githubOptions };
