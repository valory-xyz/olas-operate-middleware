import { Button, Popover } from 'antd';
import { isNil } from 'lodash';
import { useMemo } from 'react';

import { MiddlewareDeploymentStatus } from '@/client';
import { Pages } from '@/enums/Pages';
import { StakingProgramId } from '@/enums/StakingProgram';
import { useBalance } from '@/hooks/useBalance';
import { useModals } from '@/hooks/useModals';
import { usePageState } from '@/hooks/usePageState';
import { useService } from '@/hooks/useService';
import { useServices } from '@/hooks/useServices';
import { useServiceTemplates } from '@/hooks/useServiceTemplates';
import { useStakingContractInfo } from '@/hooks/useStakingContractInfo';
import { useStakingProgram } from '@/hooks/useStakingProgram';
import { ServicesService } from '@/service/Services';

import { CountdownUntilMigration } from './CountdownUntilMigration';
import { CantMigrateReason, useMigrate } from './useMigrate';

type MigrateButtonProps = {
  stakingProgramId: StakingProgramId;
};
export const MigrateButton = ({
  stakingProgramId: stakingProgramIdToMigrateTo,
}: MigrateButtonProps) => {
  const { goto } = usePageState();
  const { serviceTemplate } = useServiceTemplates();
  const {
    setPaused: setIsServicePollingPaused,
    isLoaded: isServicesLoaded,
    selectedService,
  } = useServices();

  const { setDeploymentStatus } = useService({
    serviceConfigId:
      isServicesLoaded && selectedService
        ? selectedService.service_config_id
        : '',
  });

  const { setIsPaused: setIsBalancePollingPaused } = useBalance();
  const { updateActiveStakingProgramId: updateStakingProgram } =
    useStakingProgram();
  const { activeStakingContractInfo } = useStakingContractInfo();
  const { setMigrationModalOpen } = useModals();

  const { migrateValidation, firstDeployValidation } = useMigrate(
    stakingProgramIdToMigrateTo,
  );

  // if false, user is migrating, not running for first time
  const isFirstDeploy = useMemo(() => {
    if (!isServicesLoaded) return false;
    if (selectedService) return false;

    return true;
  }, [isServicesLoaded, selectedService]);

  const validation = isFirstDeploy ? firstDeployValidation : migrateValidation;

  const popoverContent = useMemo(() => {
    if (validation.canMigrate) return null;

    if (
      validation.reason === CantMigrateReason.NotStakedForMinimumDuration &&
      !isNil(activeStakingContractInfo)
    ) {
      return (
        <CountdownUntilMigration
          activeStakingContractInfo={activeStakingContractInfo}
        />
      );
    }

    return validation.reason;
  }, [activeStakingContractInfo, validation]);

  return (
    <Popover content={popoverContent}>
      <Button
        type="primary"
        size="large"
        disabled={!validation.canMigrate}
        onClick={async () => {
          setIsServicePollingPaused(true);
          setIsBalancePollingPaused(true);

          try {
            setDeploymentStatus(MiddlewareDeploymentStatus.DEPLOYING);
            goto(Pages.Main);

            // TODO: create type for this response, we need the service_config_id to update the relevant service
            // eslint-disable-next-line @typescript-eslint/no-unused-vars
            const createServiceResponse = await ServicesService.createService({
              stakingProgramId: stakingProgramIdToMigrateTo,
              serviceTemplate,
              deploy: true,
              useMechMarketplace: false,
            });

            await updateStakingProgram(); // TODO: refactor to support single staking program & multi staking programs, this on longer works

            setMigrationModalOpen(true);
          } catch (error) {
            console.error(error);
          } finally {
            setIsServicePollingPaused(false);
            setIsBalancePollingPaused(false);
            // updateServiceStatus(); // TODO: update service status
          }
        }}
      >
        Switch and run agent
      </Button>
    </Popover>
  );
};
