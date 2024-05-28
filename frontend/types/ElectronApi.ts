export type ElectronStore = {
  isInitialFunded?: boolean;
  firstStakingRewardAchieved?: boolean;
  firstRewardNotificationShown?: boolean;
  isUpdateAvailable?: boolean;
  downloadPercentage?: number;
};

export type ElectronTrayIconStatus = 'low-gas' | 'running' | 'paused';
