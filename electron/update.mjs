import { MacUpdater } from 'electron-updater';

import { isDev } from './constants/env.mjs';
import { logger } from './utils/logger.mjs';

export const updateOptions = {
  provider: 'github',
  owner: 'valory-xyz',
  repo: 'olas-operate-app',
  releaseType: 'draft',
  private: false,
};

const macUpdater = new MacUpdater(updateOptions);

macUpdater.setFeedURL({ ...updateOptions });

macUpdater.autoDownload = false;
macUpdater.autoInstallOnAppQuit = false;
macUpdater.logger = logger;
macUpdater.forceDevUpdateConfig = isDev;

export { macUpdater };
