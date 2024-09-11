import { Flex, theme, Typography } from 'antd';
import { useMemo } from 'react';

import { Chain } from '@/client';
import { CardSection } from '@/components/styled/CardSection';
import { SERVICE_STAKING_TOKEN_MECH_USAGE_CONTRACT_ADDRESSES } from '@/constants/contractAddresses';
import { STAKING_PROGRAM_META } from '@/constants/stakingProgramMeta';
import { UNICODE_SYMBOLS } from '@/constants/symbols';
import { StakingProgramId } from '@/enums/StakingProgram';
import { StakingProgramStatus } from '@/enums/StakingProgramStatus';
import { useStakingProgram } from '@/hooks/useStakingProgram';

import { CantMigrateAlert } from './CantMigrateAlert';
import { MigrateButton } from './MigrateButton';
import { StakingContractDetails } from './StakingContractDetails';
import { StakingContractFundingButton } from './StakingContractFundingButton';
import { StakingContractTag } from './StakingContractTag';
import { useMigrate } from './useMigrate';

const { Title } = Typography;
const { useToken } = theme;

type StakingContractSectionProps = { stakingProgramId: StakingProgramId };
export const StakingContractSection = ({
  stakingProgramId: stakingProgramId,
}: StakingContractSectionProps) => {
  const { activeStakingProgramId, defaultStakingProgramId } =
    useStakingProgram();

  const { token } = useToken();

  const { migrateValidation } = useMigrate(stakingProgramId);

  // const {
  //   // isServiceStaked,
  //   // isServiceStakedForMinimumDuration,
  //   // isStakingContractInfoLoaded,
  //   // stakingContractInfoRecord,
  // } = useStakingContractInfo();

  const stakingContractAddress =
    SERVICE_STAKING_TOKEN_MECH_USAGE_CONTRACT_ADDRESSES[Chain.GNOSIS][
      stakingProgramId
    ];

  const stakingProgramMeta = STAKING_PROGRAM_META[stakingProgramId];

  // const activeStakingContractInfo = useMemo<
  //   Partial<StakingContractInfo> | null | undefined
  // >(() => {
  //   if (!isStakingContractInfoLoaded) return undefined;
  //   if (activeStakingProgram === undefined) return undefined;
  //   if (activeStakingProgram === null) return null;
  //   return stakingContractInfoRecord?.[activeStakingProgram];
  // }, [
  //   activeStakingProgram,
  //   isStakingContractInfoLoaded,
  //   stakingContractInfoRecord,
  // ]);

  /**
   * Returns `true` if this stakingProgram is active,
   * or user is unstaked and this is the default
   */
  const isActiveStakingProgram = useMemo(() => {
    if (activeStakingProgramId === null)
      return defaultStakingProgramId === stakingProgramId;
    return activeStakingProgramId === stakingProgramId;
  }, [activeStakingProgramId, defaultStakingProgramId, stakingProgramId]);

  // const isActiveStakingProgram = activeStakingProgramId === stakingProgramId;
  // const isDefaultStakingProgram = defaultStakingProgramId === stakingProgramId;

  const contractTagStatus = useMemo(() => {
    if (activeStakingProgramId === stakingProgramId)
      return StakingProgramStatus.Selected;

    // Pearl is not staked, set as Selected if default
    if (
      activeStakingProgramId === null &&
      stakingProgramId === defaultStakingProgramId
    )
      return StakingProgramStatus.Selected;

    // Otherwise, no tag
    return;
  }, [activeStakingProgramId, defaultStakingProgramId, stakingProgramId]);

  /** Styling for active or other contracts  */
  const cardSectionStyle = useMemo(() => {
    if (isActiveStakingProgram) {
      return { background: token.colorPrimaryBg };
    }
    return {};
  }, [isActiveStakingProgram, token.colorPrimaryBg]);

  return (
    <>
      <CardSection
        style={cardSectionStyle}
        borderbottom="true"
        vertical
        gap={16}
      >
        <Flex gap={12}>
          <Title level={5} className="m-0">
            {`${stakingProgramMeta?.name} contract`}
          </Title>
          <StakingContractTag status={contractTagStatus} />
        </Flex>

        <StakingContractDetails stakingProgramId={stakingProgramId} />
        <a
          href={`https://gnosisscan.io/address/${stakingContractAddress}`}
          target="_blank"
        >
          View contract details {UNICODE_SYMBOLS.EXTERNAL_LINK}
        </a>

        {!migrateValidation.canMigrate && migrateValidation.reason && (
          <CantMigrateAlert
            stakingProgramId={stakingProgramId}
            cantMigrateReason={migrateValidation.reason}
          />
        )}

        {/* Switch to program button */}
        <MigrateButton stakingProgramId={stakingProgramId} />
        <StakingContractFundingButton />
      </CardSection>
    </>
  );
};
