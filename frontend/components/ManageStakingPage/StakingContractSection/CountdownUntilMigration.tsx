import { Flex, Typography } from 'antd';
import { isNil } from 'lodash';
import { useState } from 'react';
import { useInterval } from 'usehooks-ts';

import { POPOVER_WIDTH_LARGE } from '@/constants/width';
import {
  ServiceStakingDetails,
  StakingContractDetails,
} from '@/types/Autonolas';
import { formatCountdownDisplay } from '@/utils/time';

const { Text } = Typography;

export const CountdownUntilMigration = ({
  currentStakingContractInfo,
}: {
  currentStakingContractInfo:
    | Partial<StakingContractDetails>
    | Partial<StakingContractDetails & ServiceStakingDetails>;
}) => {
  const [secondsUntilReady, setSecondsUntilMigration] = useState<number>();

  useInterval(() => {
    if (!currentStakingContractInfo) return;

    if (
      !('serviceStakingStartTime' in currentStakingContractInfo) ||
      !('minimumStakingDuration' in currentStakingContractInfo)
    ) {
      return;
    }

    const { serviceStakingStartTime, minimumStakingDuration } =
      currentStakingContractInfo;

    if (isNil(minimumStakingDuration) || isNil(serviceStakingStartTime)) return;

    const now = Math.round(Date.now() / 1000);
    const timeSinceLastStaked = now - serviceStakingStartTime;

    const timeUntilMigration = minimumStakingDuration - timeSinceLastStaked;

    if (timeUntilMigration < 0) {
      setSecondsUntilMigration(0);
      return;
    }

    setSecondsUntilMigration(timeUntilMigration);
  }, 1000);

  const countdownDisplay = isNil(secondsUntilReady)
    ? 'Loading...'
    : formatCountdownDisplay(secondsUntilReady);

  return (
    <Flex vertical gap={1} style={{ maxWidth: POPOVER_WIDTH_LARGE }}>
      <Text strong>Can&apos;t switch because you unstaked too recently.</Text>
      <Text>This may be because your agent was suspended.</Text>
      <Text>Keep running your agent and you&apos;ll be able to switch in</Text>
      <Text>{countdownDisplay}</Text>
    </Flex>
  );
};
