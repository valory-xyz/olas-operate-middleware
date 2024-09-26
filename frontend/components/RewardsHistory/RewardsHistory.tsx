import { ApiOutlined, CloseOutlined, HistoryOutlined } from '@ant-design/icons';
import {
  Button,
  Col,
  ConfigProvider,
  Flex,
  Row,
  Spin,
  Tag,
  ThemeConfig,
  Typography,
} from 'antd';
import { CSSProperties, ReactNode, useMemo } from 'react';
import styled from 'styled-components';

import { CardTitle } from '@/components/Card/CardTitle';
import { CardFlex } from '@/components/styled/CardFlex';
import { COLOR } from '@/constants/colors';
import { Pages } from '@/enums/PageState';
import { usePageState } from '@/hooks/usePageState';

import dummyData from './mock.json';
// import { useRewardsHistory } from './useRewardsHistory';

const { Text } = Typography;
const MIN_HEIGHT = 400;
const iconStyle: CSSProperties = { fontSize: 48, color: COLOR.TEXT_LIGHT };

const yourWalletTheme: ThemeConfig = {
  components: {
    Card: { paddingLG: 16 },
  },
};

const ContractName = styled.div`
  padding: 24px 24px 16px 24px;
  border-bottom: 1px solid ${COLOR.BORDER_GRAY};
`;

const EpochRow = styled(Row)`
  padding: 16px 24px;
  border-bottom: 1px solid ${COLOR.BORDER_GRAY};
`;

const getFormattedReward = (date: number | undefined) => {
  if (!date) return '--';
  return new Date(date).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
  });
};

const RewardsHistoryTitle = () => <CardTitle title="Staking rewards history" />;
const EarnedTag = () => (
  <Tag color="success" className="m-0">
    Earned
  </Tag>
);
const NotEarnedTag = () => (
  <Tag color="red" className="m-0">
    Not earned
  </Tag>
);

interface HistoryItem {
  epochStartTimeStamp: number;
  epochEndTimeStamp: number;
  reward: number;
  earned: boolean;
}

interface StakingContract {
  id: number;
  stakingContractName: string;
  history: HistoryItem[];
}

const Container = ({ children }: { children: ReactNode }) => (
  <Flex
    vertical
    gap={24}
    align="center"
    justify="center"
    style={{ height: MIN_HEIGHT }}
  >
    {children}
  </Flex>
);

const Loading = () => (
  <Container>
    <Spin />
  </Container>
);

const NoRewardsHistory = () => (
  <Container>
    <HistoryOutlined style={iconStyle} />
    <Text type="secondary">There’s no history of rewards yet</Text>
  </Container>
);

const ErrorLoadingHistory = () => (
  <Container>
    <ApiOutlined style={iconStyle} />
    <Text type="secondary">Error loading data</Text>
    {/* TODO: add "refetch" function */}
    <Button onClick={() => window.console.log('refetch')}>Try again</Button>
  </Container>
);

const RewardsHistoryList = () =>
  (dummyData as StakingContract[]).map((item) => {
    return (
      <Flex vertical key={item.id}>
        <ContractName>
          <Text strong>{item.stakingContractName}</Text>
        </ContractName>

        {item.history.map((epoch, index) => {
          const reward = epoch.reward ? epoch.reward.toFixed(2) : '--';

          return (
            <EpochRow
              key={epoch.epochStartTimeStamp}
              className={index === item.history.length - 1 ? 'mb-16' : ''}
            >
              <Col span={6}>
                <Text type="secondary">
                  {getFormattedReward(epoch.epochStartTimeStamp)}
                </Text>
              </Col>
              <Col span={11} className="text-right pr-16">
                <Text type="secondary">{`~${reward} OLAS`}</Text>
              </Col>
              <Col span={7} className="text-center pl-16">
                {epoch.earned ? <EarnedTag /> : <NotEarnedTag />}
              </Col>
            </EpochRow>
          );
        })}
      </Flex>
    );
  });

export const RewardsHistory = () => {
  // const {
  //   data, isError, isLoading
  // } = useRewardsHistory();
  const { goto } = usePageState();
  const isLoading = false;
  const isError = false;

  const history = useMemo(() => {
    if (isLoading) return <Loading />;
    if (isError) return <ErrorLoadingHistory />;
    if (dummyData.length === 0) return <NoRewardsHistory />;
    return <RewardsHistoryList />;
  }, [isLoading, isError]);

  return (
    <ConfigProvider theme={yourWalletTheme}>
      <CardFlex
        bordered={false}
        title={<RewardsHistoryTitle />}
        noBodyPadding="true"
        extra={
          <Button
            size="large"
            icon={<CloseOutlined />}
            onClick={() => goto(Pages.Main)}
          />
        }
      >
        {history}
      </CardFlex>
    </ConfigProvider>
  );
};

/**
 * - do we need to do the "Factory" stuff? - https://thegraph.com/docs/en/developing/creating-a-subgraph/#data-source-templates
 *
 * - fetch the staking contracts (already hardcoded)
 * - for each staking contract, fetch the list of epochs current agent safe have interacted with
 *    - for each epoch, fetch the rewards
 *    - for each epoch, did the user earn rewards
 *    - for each epoch, get the timestamp
 */
