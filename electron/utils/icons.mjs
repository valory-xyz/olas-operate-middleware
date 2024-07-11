import { nativeImage } from 'electron';

import { isLinux, isMac } from '../constants/os.mjs';
import { logger } from './logger.mjs';

const TRAY_ICONS_PATHS = {
  LOGGED_OUT: `${import.meta.dirname}/assets/icons/tray-logged-out.png`,
  LOW_GAS: `${import.meta.dirname}/assets/icons/tray-low-gas.png`,
  PAUSED: `${import.meta.dirname}/assets/icons/tray-paused.png`,
  RUNNING: `${import.meta.dirname}/assets/icons/tray-running.png`,
};

const TRAY_ICONS = {
  LOGGED_OUT: nativeImage.createFromPath(TRAY_ICONS_PATHS.LOGGED_OUT),
  LOW_GAS: nativeImage.createFromPath(TRAY_ICONS_PATHS.LOW_GAS),
  PAUSED: nativeImage.createFromPath(TRAY_ICONS_PATHS.PAUSED),
  RUNNING: nativeImage.createFromPath(TRAY_ICONS_PATHS.RUNNING),
};

try {
  if (isMac || isLinux) {
    // resize icons for macOS
    const size = { width: 16, height: 16 };
    TRAY_ICONS.LOGGED_OUT = TRAY_ICONS.LOGGED_OUT.resize(size);
    TRAY_ICONS.LOW_GAS = TRAY_ICONS.LOW_GAS.resize({ width: 16, height: 16 });
    TRAY_ICONS.PAUSED = TRAY_ICONS.PAUSED.resize({ width: 16, height: 16 });
    TRAY_ICONS.RUNNING = TRAY_ICONS.RUNNING.resize({ width: 16, height: 16 });
  }
} catch (e) {
  logger.electron('Error resizing tray icons', e);
}

export { TRAY_ICONS, TRAY_ICONS_PATHS };
