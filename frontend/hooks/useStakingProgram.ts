import { useContext, useMemo } from 'react';

import { STAKING_PROGRAM_META } from '@/constants/stakingProgramMeta';
import { StakingProgramContext } from '@/context/StakingProgramContext';

/**
 * Hook to get the active staking program and its metadata, and the default staking program.
 * @returns {Object} The active staking program and its metadata.
 */
export const useStakingProgram = () => {
  const {
    activeStakingProgram,
    defaultStakingProgram,
    updateActiveStakingProgram: updateStakingProgram,
  } = useContext(StakingProgramContext);

  const isLoadedActiveStakingProgram = activeStakingProgram !== undefined;

  const activeStakingProgramMeta = useMemo(() => {
    if (activeStakingProgram === undefined) return undefined;
    if (activeStakingProgram === null) return null;
    return STAKING_PROGRAM_META[activeStakingProgram];
  }, [activeStakingProgram]);

  const defaultStakingProgramMeta = STAKING_PROGRAM_META[defaultStakingProgram];

  return {
    activeStakingProgram,
    activeStakingProgramMeta,
    defaultStakingProgram,
    defaultStakingProgramMeta,
    isLoadedActiveStakingProgram,
    updateStakingProgram,
  };
};
