import { Col, Flex, Row, Skeleton, Tag, Typography } from 'antd';
import styled from 'styled-components';

import { balanceFormat } from '@/common-util';
import { COLOR } from '@/constants';
import { useBalance } from '@/hooks';
import { useReward } from '@/hooks/useReward';

const { Text } = Typography;

const RewardsRow = styled(Row)`
  margin: 0 -24px;
  > .ant-col {
    padding: 24px;
    &:not(:last-child) {
      border-right: 1px solid ${COLOR.BORDER_GRAY};
    }
  }
`;

const Loader = () => (
  <Flex vertical gap={8}>
    <Skeleton.Button active size="small" style={{ width: 92 }} />
    <Skeleton.Button active size="small" style={{ width: 92 }} />
  </Flex>
);

export const MainRewards = () => {
  const {
    availableRewardsForEpochEth,
    isEligibleForRewards,
    minimumStakedAmountRequired,
  } = useReward();
  const { isBalanceLoaded, totalOlasStakedBalance } = useBalance();

  // check if the staked amount is greater than the minimum required
  const isStaked =
    minimumStakedAmountRequired &&
    totalOlasStakedBalance &&
    totalOlasStakedBalance >= minimumStakedAmountRequired;

  return (
    <RewardsRow>
      <Col span={12}>
        <Flex vertical gap={4} align="flex-start">
          <Text type="secondary">Staking rewards today</Text>
          {isBalanceLoaded ? (
            <>
              <Text strong style={{ fontSize: 20 }}>
                {balanceFormat(availableRewardsForEpochEth, 2)} OLAS
              </Text>
              {isEligibleForRewards ? (
                <Tag color="success">Earned</Tag>
              ) : (
                <Tag color="processing">Not yet earned</Tag>
              )}
            </>
          ) : (
            <Loader />
          )}
        </Flex>
      </Col>

      <Col span={12}>
        <Flex vertical gap={4} align="flex-start">
          <Text type="secondary">Staked amount</Text>
          {isBalanceLoaded ? (
            <>
              <Text strong style={{ fontSize: 20 }}>
                {balanceFormat(totalOlasStakedBalance, 2)} OLAS
              </Text>
              {minimumStakedAmountRequired && !isStaked ? (
                <Tag color="processing">Not yet staked</Tag>
              ) : null}
            </>
          ) : (
            <Loader />
          )}
        </Flex>
      </Col>
    </RewardsRow>
  );
};
