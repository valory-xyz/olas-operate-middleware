import { ServiceTemplate } from '@/client';
import { StakingProgram } from '@/enums/StakingProgram';

/** TODO: update from hardcoded, workaround for quick release */
export const getMinimumStakedAmountRequired = (
  serviceTemplate: ServiceTemplate,
  stakingProgram: StakingProgram = StakingProgram.Beta,
) => {
  if (stakingProgram === StakingProgram.Alpha) {
    return 20;
  }

  if (stakingProgram === StakingProgram.Beta) {
    return 40;
  }

  if (stakingProgram === StakingProgram.Beta2) {
    return 100;
  }
};
