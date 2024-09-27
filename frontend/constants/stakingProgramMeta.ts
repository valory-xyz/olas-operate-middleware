import { StakingProgramId } from '@/enums/StakingProgram';

export type StakingProgramMeta = {
  name: string;
  canMigrateTo: StakingProgramId[];
  deprecated: boolean;
  liveness?: number; // in seconds
};

export const STAKING_PROGRAM_META: Record<
  StakingProgramId,
  StakingProgramMeta
> = {
  [StakingProgramId.Alpha]: {
    name: 'Pearl Alpha',
    canMigrateTo: [StakingProgramId.Beta, StakingProgramId.Beta2],
    deprecated: true,
  },
  [StakingProgramId.Beta]: {
    name: 'Pearl Beta',
    canMigrateTo: [StakingProgramId.Beta2],
    deprecated: false,
    liveness: 86400,
  },
  [StakingProgramId.Beta2]: {
    name: 'Pearl Beta 2',
    canMigrateTo: [StakingProgramId.Beta],
    deprecated: false,
    liveness: 86400,
  },
};
