import { Flex } from 'antd';
import { isNil } from 'lodash';
import { useState } from 'react';
import { useInterval } from 'usehooks-ts';

import { StakingContractInfo } from '@/types/Autonolas';

export const CountdownUntilMigration = ({
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
