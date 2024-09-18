import { Card, Flex, Typography } from 'antd';
import { useMemo, useState } from 'react';
import styled from 'styled-components';

import { MODAL_WIDTH } from '@/constants/width';

import { InfoBreakdownList } from './InfoBreakdown';
import { CustomModal } from './styled/CustomModal';

const { Title } = Typography;

const Container = styled.div`
  .ant-card-body {
    /* display: flex; */
    /* flex-direction: column; */
    /* gap: 8px; */
    padding: 16px;
  }
`;

export const AccountBalanceDetails = () => {
  const [isModalVisible, setIsModalVisible] = useState(true);

  const olasBalances = useMemo(() => {
    return [
      {
        title: 'Available',
        value: '100',
      },
      {
        title: 'Staked',
        value: '200',
      },
    ];
  }, []);

  return (
    <CustomModal
      title="Account balance details"
      open={isModalVisible}
      width={MODAL_WIDTH}
      bodyPadding
      onCancel={() => setIsModalVisible(false)}
      footer={null}
    >
      <Container>
        <Card>
          <Flex vertical gap={8}>
            <Title level={5} className="m-0">
              OLAS
            </Title>
            <InfoBreakdownList
              list={olasBalances.map((item) => ({
                left: item.title,
                right: `${item.value} OLAS`,
              }))}
              parentStyle={{ padding: 4, gap: 8 }}
            />
          </Flex>
        </Card>
      </Container>
    </CustomModal>
  );
};
