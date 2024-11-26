import { Button } from 'antd';
import { ErrorBoundary } from 'next/dist/client/components/error-boundary';
import { useMemo } from 'react';

import { MiddlewareDeploymentStatus } from '@/client';
import { ErrorComponent } from '@/components/errors/ErrorComponent';
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

    if (
      selectedService?.deploymentStatus === MiddlewareDeploymentStatus.STOPPING
    ) {
      return <AgentStoppingButton />;
    }

    if (
      selectedService?.deploymentStatus === MiddlewareDeploymentStatus.DEPLOYING
    ) {
      return <AgentStartingButton />;
    }

    if (
      selectedService?.deploymentStatus === MiddlewareDeploymentStatus.DEPLOYED
    ) {
      return <AgentRunningButton />;
    }

    if (!isEligibleForStaking && isAgentEvicted)
      return <CannotStartAgentPopover />;

    if (
      !selectedService ||
      selectedService?.deploymentStatus ===
        MiddlewareDeploymentStatus.STOPPED ||
      selectedService?.deploymentStatus ===
        MiddlewareDeploymentStatus.CREATED ||
      selectedService?.deploymentStatus === MiddlewareDeploymentStatus.BUILT ||
      selectedService?.deploymentStatus === MiddlewareDeploymentStatus.DELETED
    ) {
      return <AgentNotRunningButton />;
    }

    return <CannotStartAgentDueToUnexpectedError />;
  }, [
    isServicesLoaded,
    isSelectedStakingContractDetailsLoaded,
    selectedService,
    isEligibleForStaking,
    isAgentEvicted,
  ]);

  return (
    <ErrorBoundary errorComponent={ErrorComponent}>{button}</ErrorBoundary>
  );
};
