import { RightOutlined } from '@ant-design/icons';
import { Flex, Typography } from 'antd';
import styled from 'styled-components';

import { FireNoStreak } from '@/components/custom-icons/FireNoStreak';
import { FireStreak } from '@/components/custom-icons/FireStreak';
import { Pages } from '@/enums/PageState';
import { usePageState } from '@/hooks/usePageState';
import { useRewardsHistory } from '@/hooks/useRewardsHistory';

const { Text } = Typography;

const RewardsStreakFlex = styled(Flex)`
  padding: 8px 16px;
  background: #f2f4f9;
  border-radius: 6px;
  justify-content: space-between;
  height: 40px;
  align-items: center;
`;

const StreakIcon = ({ isOnStreak }: { isOnStreak: boolean }) => {
  if (isOnStreak) return <FireStreak />;
  return <FireNoStreak />;
};
const StreakText = ({
  streak,
  isLoading,
}: {
  streak: number;
  isLoading: boolean;
}) => {
  if (isLoading) return <div>Loading...</div>;
  if (streak > 0) return <div>{streak} day streak</div>;
  return <div>No streak</div>;
};

export const RewardsStreak = () => {
  const { goto } = usePageState();
  const { latestRewardStreak, isLoading } = useRewardsHistory();

  return (
    <RewardsStreakFlex>
      <span style={{ display: 'inline-flex', gap: 8 }}>
        <StreakIcon isOnStreak={!!latestRewardStreak} />
        <StreakText streak={latestRewardStreak} isLoading={isLoading} />
      </span>

      <Text
        type="secondary"
        className="text-sm pointer hover-underline"
        onClick={() => goto(Pages.RewardsHistory)}
      >
        See rewards history
        <RightOutlined style={{ fontSize: 12, paddingLeft: 6 }} />
      </Text>
    </RewardsStreakFlex>
  );
};
