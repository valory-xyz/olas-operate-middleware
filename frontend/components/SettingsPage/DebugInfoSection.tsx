import { Button, Flex, Typography } from 'antd';
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
  // serviceStakingState
  const { selectedAgentConfig } = useServices();
  const { selectedStakingContractDetails } = useStakingContractContext();

  const agentName = selectedAgentConfig?.displayName;
  const agentStatus = selectedStakingContractDetails?.serviceStakingState;

  const agentStakingState = useMemo(() => {
    if (agentStatus === StakingState.Evicted) return 'Evicted';
    if (agentStatus === StakingState.Staked) return 'Staked';
    if (agentStatus === StakingState.NotStaked) return 'Not Staked';
    return null;
  }, [agentStatus]);

  const info = useMemo(() => {
    return [
      { key: 'Name', value: agentName ?? NA },
      {
        key: 'Status',
        value: agentStakingState ?? NA,
      },
      {
        key: 'Staking state',
        value: NA,
      },
      {
        key: 'The time remaining until it can be unstaked',
        value: NA + ' ' + NA,
        column: true,
      },
    ];
  }, [agentName, agentStakingState]);

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
