import { MacUpdater } from 'electron-updater';

import { publishOptions } from './constants/options.mjs';
import { logger } from './utils/logger.mjs';

const macUpdater = new MacUpdater(publishOptions);

macUpdater.setFeedURL({ ...publishOptions });

macUpdater.autoDownload = false;
macUpdater.autoInstallOnAppQuit = false;
macUpdater.logger = logger;

export { macUpdater };
