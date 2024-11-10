import { Contract as MulticallContract } from 'ethers-multicall';
import { noop } from 'lodash';

import { StakedAgentService } from './StakedAgentService';

export class OptimusService extends StakedAgentService {
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
