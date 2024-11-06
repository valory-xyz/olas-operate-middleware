import { Contract as MulticallContract } from 'ethers-multicall';
import { noop } from 'lodash';

import { AgentApi } from './Agent';

export class PredictTraderService extends AgentApi {
  readonly stakingContracts = Object.reduce(() => {}, []);
  readonly serviceRegistryTokenUtilityContract: MulticallContract;

  public static getStakingRewardsInfo = () => noop;

  public static getAvailableRewardsForEpoch = () => noop;

  public static getStakingContractInfo = () => noop;
  private getStakingContractInfoByServiceIdStakingProgramId = () => noop;
  private getStakingContractInfoByStakingProgramId = () => noop;

  public static getServiceRegistryInfo = () => noop;
  public static getCurrentStakingProgramByServiceId = () => noop;
}
