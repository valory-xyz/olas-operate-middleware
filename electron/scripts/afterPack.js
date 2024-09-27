const fs = require('fs');
const path = require('path');
const os = require('os');
const builderUtil = require('builder-util');

/**
 * @param {string} outDir - Output directory of the build
 * @param {keyof typeof builderUtil.Arch} arch - CPU architecture
 */
const renameLatestMacToArchSpecific = (outDir, arch) => {
  console.log(`afterPack: renaming latest-mac.yml to latest-mac-${arch}.yml`);
  fs.renameSync(
    path.resolve(outDir, 'latest-mac.yml'),
    path.resolve(outDir, `latest-mac-${arch}.yml`),
  );
};

/**
 * @note This function is called after the packaging of the app is done.
 * @param {import('electron-builder').AfterPackContext} context - The context object from electron-builder
 */
const afterPack = async (context) => {
  if (os.platform() === 'darwin') {
    console.log('afterPack: macOS detected');

    if (context.arch === builderUtil.Arch.x64) {
      renameLatestMacToArchSpecific(context.outDir, 'x64');
    }
    if (context.arch === builderUtil.Arch.arm64) {
      renameLatestMacToArchSpecific(context.outDir, 'arm64');
    }
  }
};

exports.default = afterPack;
