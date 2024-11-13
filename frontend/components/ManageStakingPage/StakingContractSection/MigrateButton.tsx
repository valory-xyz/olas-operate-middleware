import { Button, Popover } from 'antd';
import { isNil } from 'lodash';
import { useMemo } from 'react';

import { MiddlewareDeploymentStatus } from '@/client';
import { ChainId } from '@/enums/Chain';
import { Pages } from '@/enums/Pages';
import { StakingProgramId } from '@/enums/StakingProgram';
import { useBalance } from '@/hooks/useBalance';
import { useModals } from '@/hooks/useModals';
import { usePageState } from '@/hooks/usePageState';
import { useServices } from '@/hooks/useServices';
import { useServiceTemplates } from '@/hooks/useServiceTemplates';
import {
  useActiveStakingContractInfo,
  useStakingContractInfo,
} from '@/hooks/useStakingContractInfo';
import { useStakingProgram } from '@/hooks/useStakingProgram';
import { ServicesService } from '@/service/Services';

import { CountdownUntilMigration } from './CountdownUntilMigration';
import { CantMigrateReason, useMigrate } from './useMigrate';

type MigrateButtonProps = {
  stakingProgramId: StakingProgramId;
};
export const MigrateButton = ({ stakingProgramId }: MigrateButtonProps) => {
  const { goto } = usePageState();
  const { serviceTemplate } = useServiceTemplates();
  const {
    setIsServicePollingPaused,
    setServiceStatus,
    updateServiceStatus,
    hasInitialLoaded: isServicesLoaded,
    service,
  } = useServices();

  const { defaultStakingProgramId, setDefaultStakingProgramId } =
    useStakingProgram();

  const { setIsPaused: setIsBalancePollingPaused } = useBalance();
  const { updateActiveStakingProgramId } = useStakingProgram();

  const { activeStakingContractInfo, isActiveStakingContractInfoLoaded } =
    useActiveStakingContractInfo();
  const { stakingContractInfo: defaultStakingContractInfo } =
    useStakingContractInfo(defaultStakingProgramId);

  const currentStakingContractInfo = useMemo(() => {
    if (!isActiveStakingContractInfoLoaded) return;
    if (activeStakingContractInfo) return activeStakingContractInfo;
    return defaultStakingContractInfo;
  }, [
    activeStakingContractInfo,
    defaultStakingContractInfo,
    isActiveStakingContractInfoLoaded,
  ]);

  const { setMigrationModalOpen } = useModals();

  const { migrateValidation, firstDeployValidation } =
    useMigrate(stakingProgramId);

  // if false, user is migrating, not running for first time
  const isFirstDeploy = useMemo(() => {
    if (!isServicesLoaded) return false;
    if (service) return false;
    return true;
  }, [isServicesLoaded, service]);

  const validation = isFirstDeploy ? firstDeployValidation : migrateValidation;

  const popoverContent = useMemo(() => {
    if (validation.canMigrate) return null;

    if (
      validation.reason === CantMigrateReason.NotStakedForMinimumDuration &&
      !isNil(currentStakingContractInfo)
    ) {
      return (
        <CountdownUntilMigration
          currentStakingContractInfo={currentStakingContractInfo}
        />
      );
    }

    return validation.reason;
  }, [currentStakingContractInfo, validation]);

  return (
    <Popover content={popoverContent}>
      <Button
        type="primary"
        size="large"
        disabled={!validation.canMigrate}
        onClick={async () => {
          setIsServicePollingPaused(true);
          setIsBalancePollingPaused(true);
          setDefaultStakingProgramId(stakingProgramId);

          try {
            setServiceStatus(MiddlewareDeploymentStatus.DEPLOYING);
            goto(Pages.Main);

            // update service
            await ServicesService.updateService({
              stakingProgramId,
              serviceTemplate,
              serviceUuid: serviceTemplate.service_config_id,
              deploy: true,
              useMechMarketplace:
                stakingProgramId === StakingProgramId.BetaMechMarketplace,
            });

            // start service after updating
            await ServicesService.startService(
              serviceTemplate.service_config_id,
            );

            await updateActiveStakingProgramId();

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
  );
};
