const fs = require('fs');
const path = require('path');
const os = require('os');

/**
 * @param {string} outDir - Output directory of the build
 * @param {keyof typeof import('builder-util').Arch} arch - CPU architecture
 */
const renameLatestMacToArchSpecific = (outDir, arch) => {
  console.log(`afterPack: renaming latest.yml to latest-mac-${arch}.yml`);

  const latestYmlPath = path.join(outDir, 'latest-mac.yml');
  const renamedYmlPath = path.join(outDir, `latest-mac-${arch}.yml`);

  console.log(`Renaming ${latestYmlPath} to ${renamedYmlPath}`);

  if (fs.existsSync(latestYmlPath)) {
    fs.renameSync(latestYmlPath, renamedYmlPath);
    console.log(`Renamed ${latestYmlPath} to ${renamedYmlPath}`);
  } else {
    console.error(`Error: ${latestYmlPath} not found in ${outDir}.`);
    // Print the contents of outDir for debugging
    console.log(`Contents of ${outDir}:`);
    fs.readdir(outDir, (err, files) => {
      if (err) {
        console.error(`Error reading directory ${outDir}:`, err);
      } else {
        files.forEach((file) => {
          console.log(file);
        });
      }
    });
    process.exit(1);
  }
};

/**
 * @note This function is called after the packaging of the app is done.
 * @param {import('electron-builder').BuildResult} context - The context object from electron-builder
 */
const afterAllArtifactBuild = async (context) => {
  if (os.platform() === 'darwin') {
    console.log('afterPack: macOS detected');

    if (process.env.ARCH === 'x64') {
      renameLatestMacToArchSpecific(context.outDir, 'x64');
    }
    if (process.env.ARCH === 'arm64') {
      renameLatestMacToArchSpecific(context.outDir, 'arm64');
    }
  }
};

exports.default = afterAllArtifactBuild;
