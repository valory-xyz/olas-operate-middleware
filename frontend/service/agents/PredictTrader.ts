import { noop } from 'lodash';

import { AgentServiceApi } from './Agent';

export abstract class PredictTraderServiceApi extends AgentServiceApi {
  public static getStakingRewardsInfo = () => noop;

  public static getAvailableRewardsForEpoch = () => noop;

  public static getStakingContractInfo = () => noop;
  private getStakingContractInfoByServiceIdStakingProgramId = () => noop;
  private getStakingContractInfoByStakingProgramId = () => noop;

  public static getServiceRegistryInfo = () => noop;
  public static getCurrentStakingProgramByServiceId = () => noop;
}
