import { Contract as MulticallContract } from 'ethers-multicall';
import { noop } from 'lodash';

import { AgentServiceApi } from './Agent';

export class OptimusServiceApi extends AgentServiceApi {
  static activityCheckerContract: MulticallContract;
  static stakingContracts: MulticallContract;
  static serviceRegistryTokenUtilityContract: MulticallContract;

  public static getStakingRewardsInfo = () => noop;

  public static getAvailableRewardsForEpoch = () => noop;

  public static getStakingContractInfo = () => noop;
  private getStakingContractInfoByServiceIdStakingProgramId = () => noop;
  private getStakingContractInfoByStakingProgramId = () => noop;

  public static getServiceRegistryInfo = () => noop;
  public static getCurrentStakingProgramByServiceId = () => noop;
}
