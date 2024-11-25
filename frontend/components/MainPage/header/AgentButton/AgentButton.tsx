import { Button } from 'antd';
import { ErrorBoundary } from 'next/dist/client/components/error-boundary';
import { useMemo } from 'react';

import { MiddlewareDeploymentStatus } from '@/client';
import { ErrorComponent } from '@/components/errors/ErrorComponent';
import { useService } from '@/hooks/useService';
import { useServices } from '@/hooks/useServices';
import { useActiveStakingContractInfo } from '@/hooks/useStakingContractDetails';

import {
  CannotStartAgentDueToUnexpectedError,
  CannotStartAgentPopover,
} from '../CannotStartAgentPopover';
import { AgentNotRunningButton } from './AgentNotRunningButton';
import { AgentRunningButton } from './AgentRunningButton';
import { AgentStartingButton } from './AgentStartingButton';
import { AgentStoppingButton } from './AgentStoppingButton';

export const AgentButton = () => {
  const { selectedService, isFetched: isServicesLoaded } = useServices();

  const { service, deploymentStatus: serviceStatus } = useService(
    selectedService?.service_config_id,
  );

  const {
    isEligibleForStaking,
    isAgentEvicted,
    isSelectedStakingContractDetailsLoaded,
  } = useActiveStakingContractInfo();

  const button = useMemo(() => {
    if (!isServicesLoaded || !isSelectedStakingContractDetailsLoaded) {
      return (
        <Button type="primary" size="large" disabled loading>
          Loading...
        </Button>
      );
    }

    if (serviceStatus === MiddlewareDeploymentStatus.STOPPING) {
      return <AgentStoppingButton />;
    }

    if (serviceStatus === MiddlewareDeploymentStatus.DEPLOYING) {
      return <AgentStartingButton />;
    }

    if (serviceStatus === MiddlewareDeploymentStatus.DEPLOYED) {
      return <AgentRunningButton />;
    }

    if (!isEligibleForStaking && isAgentEvicted)
      return <CannotStartAgentPopover />;

    if (
      !service ||
      serviceStatus === MiddlewareDeploymentStatus.STOPPED ||
      serviceStatus === MiddlewareDeploymentStatus.CREATED ||
      serviceStatus === MiddlewareDeploymentStatus.BUILT ||
      serviceStatus === MiddlewareDeploymentStatus.DELETED
    ) {
      return <AgentNotRunningButton />;
    }

    return <CannotStartAgentDueToUnexpectedError />;
  }, [
    isServicesLoaded,
    isSelectedStakingContractDetailsLoaded,
    serviceStatus,
    isEligibleForStaking,
    isAgentEvicted,
    service,
  ]);

  return (
    <ErrorBoundary errorComponent={ErrorComponent}>{button}</ErrorBoundary>
  );
};
