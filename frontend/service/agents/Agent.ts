/**
 * Abstract class representing an Agent API.
 *
 * This class is intended to be extended by other classes and should not be used directly.
 * It provides static methods and properties specific agents.
 *
 * @note The methods in this class are placeholders (no-op) and should be implemented in the derived classes.
 * @warning DO NOT STORE STATE IN THESE CLASSES. THEY ARE SINGLETONS AND WILL BE SHARED ACROSS THE APPLICATION.
 */
import { Contract as MulticallContract } from 'ethers-multicall';
import { noop } from 'lodash';

/**
 *
 */
export abstract class AgentServiceApi {
  static activityCheckerContract: MulticallContract;
  static olasStakingTokenProxyContract: MulticallContract;
  static serviceRegistryTokenUtilityContract: MulticallContract;

  public static getStakingRewardsInfo = () => noop;

  public static getAvailableRewardsForEpoch = () => noop;

  public static getStakingContractInfo = () => noop;
  private getStakingContractInfoByServiceIdStakingProgramId = () => noop;
  private getStakingContractInfoByStakingProgramId = () => noop;

  public static getServiceRegistryInfo = () => noop;
  public static getCurrentStakingProgramByServiceId = () => noop;
}
