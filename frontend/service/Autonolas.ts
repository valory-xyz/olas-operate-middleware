const ONE_YEAR = 1 * 24 * 60 * 60 * 365;
const REQUIRED_MECH_REQUESTS_SAFETY_MARGIN = 1;

/**
 * @param serviceId
 * @returns StakingProgram | null (null when not staked)
 */

export const AutonolasService = {
  getAgentStakingRewardsInfo,
  getAvailableRewardsForEpoch,
  getCurrentStakingProgramByServiceId,
  getServiceRegistryInfo,
  getStakingContractInfoByServiceIdStakingProgram,
  getStakingContractInfoByStakingProgram,
};
