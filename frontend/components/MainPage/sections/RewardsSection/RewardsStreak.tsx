import { RightOutlined } from '@ant-design/icons';
import { Flex, Skeleton, Typography } from 'antd';
import styled from 'styled-components';

import { FireNoStreak } from '@/components/custom-icons/FireNoStreak';
import { FireStreak } from '@/components/custom-icons/FireStreak';
import { NA } from '@/constants/symbols';
import { Pages } from '@/enums/PageState';
import { usePageState } from '@/hooks/usePageState';
import { useReward } from '@/hooks/useReward';
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

const Streak = () => {
  const { isEligibleForRewards } = useReward();
  const {
    latestRewardStreak: streak,
    isLoading,
    isFetching,
    isError,
  } = useRewardsHistory();

  if (isLoading || isFetching) return <Skeleton.Input active size="small" />;

  if (isError) return NA;

  // Graph does not account for the current day so, so we need to add 1 to the streak.
  // Also, if previously streak was not 0.
  const optimisticStreak =
    isEligibleForRewards && streak !== 0 ? streak + 1 : streak;

  return (
    <span style={{ display: 'inline-flex', gap: 8 }}>
      {optimisticStreak > 0 ? (
        <>
          <FireStreak /> {optimisticStreak} day streak
        </>
      ) : (
        <>
          <FireNoStreak /> No streak
        </>
      )}
    </span>
  );
};

export const RewardsStreak = () => {
  const { goto } = usePageState();

  return (
    <RewardsStreakFlex>
      <Streak />

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
