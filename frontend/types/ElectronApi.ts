export type ElectronStore = {
  isInitialFunded?: boolean;
  firstStakingRewardAchieved?: boolean;
  firstRewardNotificationShown?: boolean;
  isUpdateAvailable?: boolean;
};

export type ElectronTrayIconStatus = 'low-gas' | 'running' | 'paused';
