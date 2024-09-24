import { CloseOutlined } from '@ant-design/icons';
import { Button, Card, ConfigProvider, ThemeConfig, Typography } from 'antd';

import { CardTitle } from '@/components/Card/CardTitle';
import { CardFlex } from '@/components/styled/CardFlex';
import { Pages } from '@/enums/PageState';
import { usePageState } from '@/hooks/usePageState';

const { Text } = Typography;

const yourWalletTheme: ThemeConfig = {
  components: {
    Card: { paddingLG: 16 },
  },
};

const RewardsHistoryTitle = () => <CardTitle title="Staking rewards history" />;

export const RewardsHistory = () => {
  const { goto } = usePageState();

  return (
    <ConfigProvider theme={yourWalletTheme}>
      <CardFlex
        bordered={false}
        title={<RewardsHistoryTitle />}
        extra={
          <Button
            size="large"
            icon={<CloseOutlined />}
            onClick={() => goto(Pages.Main)}
          />
        }
      >
        <Card>
          <Text>Hey!</Text>
        </Card>
      </CardFlex>
    </ConfigProvider>
  );
};
