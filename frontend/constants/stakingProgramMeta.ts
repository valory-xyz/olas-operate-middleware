import { StakingProgram } from '@/enums/StakingProgram';

export const STAKING_PROGRAM_META: Record<
  StakingProgram,
  {
    name: string;
    canMigrateTo: StakingProgram[];
    deprecated: boolean;
  }
> = {
  [StakingProgram.Alpha]: {
    name: 'Pearl Alpha',
    canMigrateTo: [StakingProgram.Beta, StakingProgram.Beta2],
    deprecated: true,
  },
  [StakingProgram.Beta]: {
    name: 'Pearl Beta',
    canMigrateTo: [StakingProgram.Beta2],
    deprecated: false,
  },
  [StakingProgram.Beta2]: {
    name: 'Pearl Beta 2',
    canMigrateTo: [StakingProgram.Beta],
    deprecated: false,
  },
};
