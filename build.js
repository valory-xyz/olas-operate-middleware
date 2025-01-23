/**
 * This script is used to build the electron app **with notarization**. It is used for the final build and release process.
 */
require('dotenv').config();
const build = require('electron-builder').build;

const { publishOptions } = require('./electron/constants');

/**
 * Get the artifact name for the build based on the environment.
 * @returns {string}
 */
function artifactName() {
  const env = process.env.NODE_ENV;
  const prefix = env === 'production' ? '' : 'dev-';
  return prefix + '${productName}-${version}-${platform}-${arch}.${ext}';
}

const main = async () => {
  console.log('Building...');
 
  const macTarget = process.env.ARCH === 'universal' ? {
    target: 'dmg',
    arch: ['arm64', 'x64'],
    artifactName: '${productName}-${version}-${platform}-universal.${ext}'
  } : {
    target: 'dmg',
    arch: [process.env.ARCH],
    artifactName: '${productName}-${version}-${platform}-${arch}.${ext}'
  };
 
  await build({
    publish: 'onTag',
    config: {
      appId: 'xyz.valory.olas-operate-app',
      artifactName: artifactName(),
      productName: 'Pearl',
      files: ['electron/**/*', 'package.json'],
      directories: {
        output: 'dist',
      },
      extraResources: [
        {
          from: process.env.ARCH === 'universal' ? 'electron/bins' : 'electron/bins',
          to: 'bins',
          filter: ['**/*'],
        },
        {
          from: '.env',
          to: '.env'
        },
      ],
      cscKeyPassword: process.env.CSC_KEY_PASSWORD, 
      cscLink: process.env.CSC_LINK,
      mac: {
        target: [macTarget],
        publish: publishOptions,
        category: 'public.app-category.utilities',
        icon: 'electron/assets/icons/splash-robot-head-dock.png',
        hardenedRuntime: true,
        gatekeeperAssess: false,
        entitlements: 'electron/entitlements.mac.plist',
        entitlementsInherit: 'electron/entitlements.mac.plist',
      },
    },
  });
 };

main().then(() => {
  console.log('Build & Notarize complete');
});
