import { Button, Flex, Popover, theme, Typography } from 'antd';
import { isNil } from 'lodash';
import { ReactNode, useMemo, useState } from 'react';
import { useInterval } from 'usehooks-ts';

import { Chain, DeploymentStatus } from '@/client';
import { OpenAddFundsSection } from '@/components/MainPage/sections/AddFundsSection';
import { CardSection } from '@/components/styled/CardSection';
import { SERVICE_STAKING_TOKEN_MECH_USAGE_CONTRACT_ADDRESSES } from '@/constants/contractAddresses';
import { STAKING_PROGRAM_META } from '@/constants/stakingProgramMeta';
import { UNICODE_SYMBOLS } from '@/constants/symbols';
import { Pages } from '@/enums/PageState';
import { StakingProgram } from '@/enums/StakingProgram';
import { StakingProgramStatus } from '@/enums/StakingProgramStatus';
import { useBalance } from '@/hooks/useBalance';
import { useModals } from '@/hooks/useModals';
import { usePageState } from '@/hooks/usePageState';
import { useServices } from '@/hooks/useServices';
import { useServiceTemplates } from '@/hooks/useServiceTemplates';
import { useStakingContractInfo } from '@/hooks/useStakingContractInfo';
import { useStakingProgram } from '@/hooks/useStakingProgram';
import { ServicesService } from '@/service/Services';
import { StakingContractInfo } from '@/types/Autonolas';
import { getMinimumStakedAmountRequired } from '@/utils/service';

import { AlertInsufficientMigrationFunds, AlertNoSlots } from './alerts';
import { StakingContractDetails } from './StakingContractDetails';
import { StakingContractTag } from './StakingContractTag';

const { Title, Text } = Typography;
const { useToken } = theme;

type StakingContractSectionProps = { stakingProgram: StakingProgram };
export const StakingContractSection = ({
  stakingProgram,
}: StakingContractSectionProps) => {
  const { goto } = usePageState();

  const {
    setServiceStatus,
    serviceStatus,
    setIsServicePollingPaused,
    updateServiceStatus,
  } = useServices();

  const { serviceTemplate } = useServiceTemplates();
  const { setMigrationModalOpen } = useModals();

  const {
    activeStakingProgram,
    activeStakingProgramMeta,
    defaultStakingProgram,
    updateStakingProgram,
  } = useStakingProgram();

  const { token } = useToken();

  const {
    safeBalance,
    totalOlasStakedBalance,
    isBalanceLoaded,
    setIsPaused: setIsBalancePollingPaused,
  } = useBalance();

  const {
    isServiceStaked,
    isServiceStakedForMinimumDuration,
    isStakingContractInfoLoaded,
    stakingContractInfoRecord,
  } = useStakingContractInfo();

  const [isFundingSectionOpen, setIsFundingSectionOpen] = useState(false);

  const stakingContractAddress =
    SERVICE_STAKING_TOKEN_MECH_USAGE_CONTRACT_ADDRESSES[Chain.GNOSIS][
      stakingProgram
    ];

  const stakingProgramMeta = STAKING_PROGRAM_META[stakingProgram];

  const stakingContractInfoForStakingProgram =
    stakingContractInfoRecord?.[stakingProgram];

  const activeStakingContractInfo = useMemo<
    Partial<StakingContractInfo> | null | undefined
  >(() => {
    if (!isStakingContractInfoLoaded) return undefined;
    if (activeStakingProgram === undefined) return undefined;
    if (activeStakingProgram === null) return null;
    return stakingContractInfoRecord?.[activeStakingProgram];
  }, [
    activeStakingProgram,
    isStakingContractInfoLoaded,
    stakingContractInfoRecord,
  ]);

  /**
   * Returns `true` if this stakingProgram is active,
   * or user is unstaked and this is the default
   */
  const isSelectedOrUnstakedDefault = useMemo(() => {
    if (activeStakingProgram === null)
      return defaultStakingProgram === stakingProgram;
    return activeStakingProgram === stakingProgram;
  }, [activeStakingProgram, defaultStakingProgram, stakingProgram]);

  const hasEnoughRewards = true;
  //(stakingContractInfoForStakingProgram?.availableRewards ?? 0) > 0;

  const minimumOlasRequiredToMigrate = useMemo(
    () => getMinimumStakedAmountRequired(serviceTemplate, stakingProgram),
    [serviceTemplate, stakingProgram],
  );

  // Check if there are enough OLAS to migrate
  const hasEnoughOlasToMigrate = useMemo(() => {
    if (safeBalance?.OLAS === undefined || totalOlasStakedBalance === undefined)
      return false;

    const balanceForMigration = safeBalance.OLAS + totalOlasStakedBalance;
    if (minimumOlasRequiredToMigrate === undefined) return false;

    return balanceForMigration >= minimumOlasRequiredToMigrate;
  }, [minimumOlasRequiredToMigrate, safeBalance?.OLAS, totalOlasStakedBalance]);

  // Check if there are enough SLOTS available
  const hasEnoughSlots = useMemo(() => {
    if (!stakingContractInfoForStakingProgram) return false;

    const { maxNumServices, serviceIds } = stakingContractInfoForStakingProgram;
    return maxNumServices && serviceIds && maxNumServices > serviceIds.length;
  }, [stakingContractInfoForStakingProgram]);

  const migrateValidation = useMemo<{
    canMigrate: boolean;
    reason?: string | ReactNode;
  }>(() => {
    // loading requirements
    if (!isBalanceLoaded) {
      return { canMigrate: false, reason: <Text>Loading balance...</Text> };
    }
    if (!isStakingContractInfoLoaded) {
      return {
        canMigrate: false,
        reason: <Text>Loading staking contract information...</Text>,
      };
    }

    // general requirements
    if (isSelectedOrUnstakedDefault) {
      return {
        canMigrate: false,
        reason: <Text>Contract is already selected</Text>,
      };
    }

    if (!hasEnoughRewards) {
      return { canMigrate: false, reason: <Text>No available rewards</Text> };
    }
    if (!hasEnoughSlots) {
      return {
        canMigrate: false,
        reason: <Text>No available staking slots</Text>,
      };
    }
    if (!hasEnoughOlasToMigrate) {
      return {
        canMigrate: false,
        reason: <Text>Insufficient OLAS to migrate</Text>,
      };
    }
    // stopped service requirements
    if (
      [
        DeploymentStatus.DEPLOYED,
        DeploymentStatus.DEPLOYING,
        DeploymentStatus.STOPPING,
      ].some((status) => status === serviceStatus) // allow nil serviceStatus to pass, so first-timers can migrate
    ) {
      return {
        canMigrate: false,
        reason: <Text>Pearl is currently running</Text>,
      };
    }

    // active staking program requirements
    if (!isStakingContractInfoLoaded) {
      return {
        canMigrate: false,
        reason: <Text>Loading staking contract information...</Text>,
      };
    }

    // user is not actively staked, allow migration
    if (activeStakingProgram === null) {
      return { canMigrate: true };
    }

    if (!isServiceStaked) {
      return {
        canMigrate: false,
        reason: <Text>Service is not staked</Text>,
      };
    }
    // USER IS STAKED
    if (!activeStakingProgramMeta?.canMigrateTo.includes(stakingProgram)) {
      return {
        canMigrate: false,
        reason: 'Migration not supported for this contract',
      };
    }

    if (activeStakingContractInfo && !isServiceStakedForMinimumDuration) {
      return {
        canMigrate: false,
        reason: (
          <CountdownUntilMigration
            activeStakingContractInfo={activeStakingContractInfo}
          />
        ),
      };
    }

    return { canMigrate: true };
  }, [
    activeStakingContractInfo,
    activeStakingProgram,
    activeStakingProgramMeta?.canMigrateTo,
    hasEnoughOlasToMigrate,
    hasEnoughRewards,
    hasEnoughSlots,
    isBalanceLoaded,
    isSelectedOrUnstakedDefault,
    isServiceStaked,
    isServiceStakedForMinimumDuration,
    isStakingContractInfoLoaded,
    serviceStatus,
    stakingProgram,
  ]);

  const cantMigrateAlert = useMemo(() => {
    if (!isBalanceLoaded || !isStakingContractInfoLoaded) {
      return null;
    }

    if (isSelectedOrUnstakedDefault) {
      return null;
    }

    if (!hasEnoughSlots) {
      return <AlertNoSlots />;
    }

    if (
      !hasEnoughOlasToMigrate &&
      safeBalance?.OLAS !== undefined &&
      totalOlasStakedBalance !== undefined
    ) {
      return (
        <AlertInsufficientMigrationFunds
          masterSafeOlasBalance={safeBalance.OLAS}
          stakedOlasBalance={totalOlasStakedBalance}
          totalOlasRequiredForStaking={minimumOlasRequiredToMigrate!}
        />
      );
    }
  }, [
    isBalanceLoaded,
    isStakingContractInfoLoaded,
    isSelectedOrUnstakedDefault,
    hasEnoughSlots,
    hasEnoughOlasToMigrate,
    safeBalance?.OLAS,
    totalOlasStakedBalance,
    minimumOlasRequiredToMigrate,
  ]);

  const contractTagStatus = useMemo(() => {
    if (activeStakingProgram === stakingProgram)
      return StakingProgramStatus.Selected;

    // Pearl is not staked, set as Selected if default
    if (
      activeStakingProgram === null &&
      stakingProgram === defaultStakingProgram
    )
      return StakingProgramStatus.Selected;

    // Otherwise, no tag
    return;
  }, [activeStakingProgram, defaultStakingProgram, stakingProgram]);

  /** Displays the dropdown function section & button */
  const isFundingSectionShown = useMemo(() => {
    if (!isBalanceLoaded || !isStakingContractInfoLoaded) {
      return false;
    }

    if (!isSelectedOrUnstakedDefault) {
      return false;
    }

    if (!hasEnoughOlasToMigrate) {
      return false;
    }

    // check if migration is possible according to meta
    // ignore `null` as unstaked
    if (
      activeStakingProgram !== null &&
      !stakingProgramMeta.canMigrateTo.includes(stakingProgram)
    ) {
      return false;
    }

    return true;
  }, [
    activeStakingProgram,
    hasEnoughOlasToMigrate,
    isBalanceLoaded,
    isSelectedOrUnstakedDefault,
    isStakingContractInfoLoaded,
    stakingProgram,
    stakingProgramMeta.canMigrateTo,
  ]);

  /** Styling for active or other contracts  */
  const cardSectionStyle = useMemo(() => {
    if (isSelectedOrUnstakedDefault) {
      return { background: token.colorPrimaryBg };
    }
    return {};
  }, [isSelectedOrUnstakedDefault, token.colorPrimaryBg]);

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

        <StakingContractDetails name={stakingProgram} />
        <a
          href={`https://gnosisscan.io/address/${stakingContractAddress}`}
          target="_blank"
        >
          View contract details {UNICODE_SYMBOLS.EXTERNAL_LINK}
        </a>

        {!migrateValidation.canMigrate && cantMigrateAlert}
        {/* Switch to program button */}
        {!isSelectedOrUnstakedDefault && (
          <Popover content={migrateValidation.reason}>
            <Button
              type="primary"
              size="large"
              disabled={!migrateValidation.canMigrate}
              onClick={async () => {
                setIsServicePollingPaused(true);
                setIsBalancePollingPaused(true);

                try {
                  setServiceStatus(DeploymentStatus.DEPLOYING);
                  goto(Pages.Main);

                  await ServicesService.createService({
                    stakingProgram,
                    serviceTemplate,
                    deploy: true,
                  });

                  await updateStakingProgram();

                  setMigrationModalOpen(true);
                } catch (error) {
                  console.error(error);
                } finally {
                  setIsServicePollingPaused(false);
                  setIsBalancePollingPaused(false);
                  updateServiceStatus();
                }
              }}
            >
              Switch and run agent
            </Button>
          </Popover>
        )}

        {/* show funding address */}
        {isFundingSectionShown && (
          <>
            <Button
              type="default"
              size="large"
              onClick={() => setIsFundingSectionOpen((prev) => !prev)}
            >
              {isFundingSectionOpen ? 'Hide' : 'Show'} address to fund
            </Button>
            {isFundingSectionOpen && <OpenAddFundsSection />}
          </>
        )}
      </CardSection>
    </>
  );
};

const CountdownUntilMigration = ({
  activeStakingContractInfo,
}: {
  activeStakingContractInfo: Partial<StakingContractInfo>;
}) => {
  const [secondsUntilReady, setSecondsUntilMigration] = useState<number>();

  useInterval(() => {
    if (!activeStakingContractInfo) return;

    const { serviceStakingStartTime, minimumStakingDuration } =
      activeStakingContractInfo;

    if (isNil(minimumStakingDuration)) return;
    if (isNil(serviceStakingStartTime)) return;

    const now = Math.round(Date.now() / 1000);
    const timeSinceLastStaked = now - serviceStakingStartTime;

    const timeUntilMigration = minimumStakingDuration - timeSinceLastStaked;

    if (timeUntilMigration < 0) {
      setSecondsUntilMigration(0);
      return;
    }

    setSecondsUntilMigration(timeUntilMigration);
  }, 1000);

  if (!secondsUntilReady) return "You're ready to switch contracts!"; // Shouldn't happen, but just in case

  return (
    <Flex vertical gap={1}>
      <strong>Can&apos;t switch because you unstaked too recently.</strong>
      <span>This may be because your agent was suspended.</span>
      <span>Keep running your agent and you&apos;ll be able to switch in</span>
      <span>{countdownDisplayFormat(secondsUntilReady)}</span>
    </Flex>
  );
};

const countdownDisplayFormat = (totalSeconds: number) => {
  const days = Math.floor(totalSeconds / (24 * 3600));
  totalSeconds %= 24 * 3600;

  const hours = Math.floor(totalSeconds / 3600);
  totalSeconds %= 3600;

  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;

  // Ensure double digits for hours, minutes, and seconds
  const formattedHours = String(hours).padStart(2, '0');
  const formattedMinutes = String(minutes).padStart(2, '0');
  const formattedSeconds = String(seconds).padStart(2, '0');

  return `${days} days ${formattedHours} hours ${formattedMinutes} minutes ${formattedSeconds} seconds`;
};
