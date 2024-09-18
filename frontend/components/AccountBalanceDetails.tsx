import { Card, Flex, Typography } from 'antd';
import { useMemo, useState } from 'react';
import styled from 'styled-components';

import { MODAL_WIDTH } from '@/constants/width';

import { InfoBreakdownList } from './InfoBreakdown';
import { CustomModal } from './styled/CustomModal';

const { Title } = Typography;

const Container = styled.div`
  > div:not(:last-child) {
    margin-bottom: 16px;
  }
  .ant-card-body {
    /* display: flex; */
    /* flex-direction: column; */
    /* gap: 8px; */
    padding: 16px;
  }
`;

const infoBreakdownParentStyle = { gap: 8 };

const OlasBalance = () => {
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
          parentStyle={infoBreakdownParentStyle}
        />
      </Flex>
    </Card>
  );
};

const XdaiBalance = () => {
  const olasBalances = useMemo(() => {
    return [
      {
        title: 'Available',
        value: '100',
      },
    ];
  }, []);

  return (
    <Card>
      <Flex vertical gap={8}>
        <Title level={5} className="m-0">
          XDAI
        </Title>
        <InfoBreakdownList
          list={olasBalances.map((item) => ({
            left: item.title,
            right: `${item.value} XDAI`,
          }))}
          parentStyle={infoBreakdownParentStyle}
        />
      </Flex>
    </Card>
  );
};

export const AccountBalanceDetails = () => {
  const [isModalVisible, setIsModalVisible] = useState(true);

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
        <OlasBalance />
        <XdaiBalance />
      </Container>
    </CustomModal>
  );
};
