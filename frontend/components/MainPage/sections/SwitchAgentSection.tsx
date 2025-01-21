import { ControlOutlined } from '@ant-design/icons';
import { Button, Flex, Popover, Tooltip, Typography } from 'antd';
import Image from 'next/image';
import { useMemo } from 'react';

import { CardSection } from '@/components/styled/CardSection';
import { COLOR } from '@/constants/colors';
import { Pages } from '@/enums/Pages';
import { useFeatureFlag } from '@/hooks/useFeatureFlag';
import { usePageState } from '@/hooks/usePageState';
import { useService } from '@/hooks/useService';
import { useServices } from '@/hooks/useServices';
import { useStakingContractContext } from '@/hooks/useStakingContractDetails';

const { Text } = Typography;

const UpdateTemplate = () => {
  const { goto } = usePageState();

  const isAgentSettingsEnabled = useFeatureFlag('agent-settings');

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    goto(Pages.UpdateAgentTemplate);
  };

  if (isAgentSettingsEnabled) {
    return <ControlOutlined onClick={handleClick} />;
  }

  return (
    <Tooltip
      arrow={false}
      title={
        <Text className="text-sm">
          The agent cannot be configured at the moment
        </Text>
      }
      overlayInnerStyle={{ width: 'max-content' }}
      placement="bottom"
    >
      <ControlOutlined style={{ color: COLOR.NEUTRAL_4, cursor: 'pointer' }} />
    </Tooltip>
  );
};

export const SwitchAgentSection = () => {
  const { goto } = usePageState();
  const {
    isLoading: isServicesLoading,
    selectedAgentConfig,
    selectedAgentType,
    selectedService,
  } = useServices();
  const { isServiceRunning } = useService(selectedService?.service_config_id);
  const { isAllStakingContractDetailsRecordLoaded } =
    useStakingContractContext();

  // enable only if all conditions are met
  const isSwitchAgentEnabled = useMemo(() => {
    if (isServicesLoading) return false;
    if (isServiceRunning) return false;
    if (!isAllStakingContractDetailsRecordLoaded) return false;
    return true;
  }, [
    isServicesLoading,
    isServiceRunning,
    isAllStakingContractDetailsRecordLoaded,
  ]);

  return (
    <CardSection
      gap={8}
      padding="12px 24px"
      justify="space-between"
      align="center"
      borderbottom="true"
    >
      <Flex gap={12} align="center">
        <Image
          src={`/agent-${selectedAgentType}-icon.png`}
          width={24}
          height={24}
          alt={selectedAgentConfig.displayName}
        />
        <Text>{selectedAgentConfig.displayName}</Text>
        <UpdateTemplate />
      </Flex>

      {isSwitchAgentEnabled ? (
        <Button onClick={() => goto(Pages.SwitchAgent)} type="primary" ghost>
          Switch agent
        </Button>
      ) : (
        <Popover
          placement="bottomRight"
          content="To switch, stop the agent you're running"
          showArrow={false}
        >
          <Button disabled>Switch agent</Button>
        </Popover>
      )}
    </CardSection>
  );
};
