import { Button, Flex, Typography } from 'antd';
import { isNil } from 'lodash';
import { useCallback, useMemo, useState } from 'react';

import { NA } from '@/constants/symbols';
import { MODAL_WIDTH } from '@/constants/width';
import { useServices } from '@/hooks/useServices';
import { useStakingContractContext } from '@/hooks/useStakingContractDetails';
import { StakingState } from '@/types/Autonolas';

import { CardSection } from '../styled/CardSection';
import { CustomModal } from '../styled/CustomModal';

const { Text } = Typography;

const AgentStakingInfo = () => {
  const { selectedAgentConfig } = useServices();
  const { selectedStakingContractDetails } = useStakingContractContext();

  const agentName = selectedAgentConfig?.displayName;

  // agent status
  const agentStatus = selectedStakingContractDetails?.serviceStakingState;
  const agentStakingState = useMemo(() => {
    if (agentStatus === StakingState.Evicted) return 'Evicted';
    if (agentStatus === StakingState.Staked) return 'Staked';
    if (agentStatus === StakingState.NotStaked) return 'Not Staked';
    return null;
  }, [agentStatus]);

  // last staked time
  const lastStakedTime =
    selectedStakingContractDetails?.serviceStakingStartTime;
  const lastStaked = lastStakedTime
    ? new Date(lastStakedTime).toLocaleString()
    : null;

  // time remaining until it can be unstaked
  const timeRemainingToUnstake = useMemo(() => {
    if (lastStakedTime === 0) return null; // If never staked, return null

    if (!selectedStakingContractDetails) return null;
    const { serviceStakingStartTime, minimumStakingDuration } =
      selectedStakingContractDetails;
    const timeRemaining =
      (serviceStakingStartTime ?? 0) + (minimumStakingDuration ?? 0) * 1000;

    return Intl.DateTimeFormat('en-US', {
      dateStyle: 'medium',
      timeStyle: 'long',
    }).format(new Date(timeRemaining + Date.now()));
  }, [lastStakedTime, selectedStakingContractDetails]);

  const info = useMemo(() => {
    return [
      { key: 'Name', value: agentName ?? NA },
      { key: 'Status', value: agentStakingState ?? NA },
      { key: 'Last staked', value: lastStaked ?? NA },
      {
        key: 'The time remaining until it can be unstaked',
        value: isNil(timeRemainingToUnstake) ? NA : timeRemainingToUnstake,
        column: true,
      },
    ];
  }, [agentName, agentStakingState, lastStaked, timeRemainingToUnstake]);

  return (
    <Flex vertical style={{ padding: '16px 24px' }} gap={8}>
      <Text strong>Agent staking details:</Text>
      {selectedAgentConfig ? (
        info.map(({ key, value, column }) => (
          <Flex key={key} gap={column ? 0 : 8} vertical={!!column}>
            <Text type="secondary">{key}: </Text>
            <Text strong>{value}</Text>
          </Flex>
        ))
      ) : (
        <Text type="secondary">No agent staking info available.</Text>
      )}
    </Flex>
  );
};

export const DebugInfoSection = () => {
  const [isModalOpen, setIsModalOpen] = useState(true);
  const showModal = useCallback(() => setIsModalOpen(true), []);
  const handleCancel = useCallback(() => setIsModalOpen(false), []);

  return (
    <CardSection vertical gap={8} align="start" padding="24px">
      <Text strong>Debug data (for devs)</Text>
      <Button type="primary" ghost size="large" onClick={showModal}>
        Show debug data
      </Button>
      <CustomModal
        title="Debug data"
        open={isModalOpen}
        footer={null}
        width={MODAL_WIDTH}
        onCancel={handleCancel}
      >
        <AgentStakingInfo />
      </CustomModal>
    </CardSection>
  );
};
