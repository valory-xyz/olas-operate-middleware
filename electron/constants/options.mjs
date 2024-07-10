// Publish options
export const publishOptions = {
  provider: 'github',
  owner: 'valory-xyz',
  repo: 'olas-operate-app',
  releaseType: 'draft',
  token: process.env.GH_TOKEN,
  private: false,
  publishAutoUpdate: true,
};
