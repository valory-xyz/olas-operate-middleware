import { InfoCircleOutlined, WalletOutlined } from '@ant-design/icons';
import { Card, Flex, Tooltip, Typography } from 'antd';
import { useMemo, useState } from 'react';
import styled from 'styled-components';

import { COLOR } from '@/constants/colors';
import { MODAL_WIDTH } from '@/constants/width';

import { InfoBreakdownList } from './InfoBreakdown';
import { CustomModal } from './styled/CustomModal';

const { Title, Paragraph } = Typography;

const Container = styled.div`
  > div:not(:last-child) {
    margin-bottom: 16px;
  }
  .ant-card-body {
    padding: 16px;
  }
`;

const infoBreakdownParentStyle = { gap: 8 };

const InfoTooltip = ({ children }: { children: React.ReactNode }) => (
  <Tooltip arrow={false} title={children} placement="topLeft">
    <InfoCircleOutlined />
  </Tooltip>
);

const YourWalletDetails = () => {
  return (
    <>
      <Flex vertical gap={12}>
        <WalletOutlined style={{ fontSize: 24, color: COLOR.TEXT_LIGHT }} />
        <Flex justify="space-between" className="w-full">
          <Title level={5} className="m-0">
            Your wallet
          </Title>

          <Title level={5} className="m-0">
            Your wallet
          </Title>
        </Flex>
      </Flex>
    </>
  );
};

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
  const xdaiBalances = useMemo(() => {
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
          list={xdaiBalances.map((item) => ({
            left: item.title,
            right: `${item.value} XDAI`,
          }))}
          parentStyle={infoBreakdownParentStyle}
        />
      </Flex>
    </Card>
  );
};

const Signer = () => {
  const signerInfo = useMemo(() => {
    return [
      {
        title: (
          <>
            Signer&nbsp;
            <InfoTooltip>
              <Paragraph className="text-sm">
                Your wallet and agent’s wallet use Safe, a multi-signature
                wallet. The app is designed to trigger transactions on these
                Safe wallets via Signers.
              </Paragraph>
              <Paragraph className="text-sm">
                This setup enables features like the backup wallet.
              </Paragraph>
              <Paragraph className="text-sm m-0">
                Note: Signer’s XDAI balance is included in wallet XDAI balances.
              </Paragraph>
            </InfoTooltip>
          </>
        ),
        value: '100',
      },
    ];
  }, []);

  return (
    <Card>
      <Flex vertical gap={8}>
        <InfoBreakdownList
          list={signerInfo.map((item) => ({
            left: item.title,
            right: `${item.value} XDAI`,
          }))}
          parentStyle={infoBreakdownParentStyle}
        />
      </Flex>
    </Card>
  );
};

const YourAgentWallet = () => {
  const olasBalances = useMemo(() => {
    return [
      {
        title: 'Available rewards',
        value: '100',
      },
      {
        title: 'Unclaimed rewards',
        value: '200',
      },
    ];
  }, []);

  const xdaiBalances = useMemo(() => {
    return [
      {
        title: 'Available',
        value: '100',
      },
    ];
  }, []);

  const signerInfo = useMemo(() => {
    return [
      {
        title: (
          <>
            Signer&nbsp;
            <InfoTooltip>
              <Paragraph className="text-sm">
                Your wallet and agent’s wallet use Safe, a multi-signature
                wallet. The app is designed to trigger transactions on these
                Safe wallets via Signers.
              </Paragraph>
              <Paragraph className="text-sm">
                This setup enables features like the backup wallet.
              </Paragraph>
              <Paragraph className="text-sm m-0">
                Note: Signer’s XDAI balance is included in wallet XDAI balances.
              </Paragraph>
            </InfoTooltip>
          </>
        ),
        value: '100',
      },
    ];
  }, []);

  return (
    <Card>
      <Container>
        <Flex vertical gap={12}>
          <WalletOutlined style={{ fontSize: 24, color: COLOR.TEXT_LIGHT }} />
          <Flex justify="space-between" className="w-full">
            <Title level={5} className="m-0">
              Your agent&apos;s wallet
            </Title>

            <Title level={5} className="m-0">
              Your wallet
            </Title>
          </Flex>
        </Flex>

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

        <Flex vertical gap={8}>
          <Title level={5} className="m-0">
            XDAI
          </Title>
          <InfoBreakdownList
            list={xdaiBalances.map((item) => ({
              left: item.title,
              right: `${item.value} XDAI`,
            }))}
            parentStyle={infoBreakdownParentStyle}
          />
        </Flex>

        <Flex vertical gap={8}>
          <InfoBreakdownList
            list={signerInfo.map((item) => ({
              left: item.title,
              right: `${item.value} XDAI`,
            }))}
            parentStyle={infoBreakdownParentStyle}
          />
        </Flex>
      </Container>
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
        <YourWalletDetails />
        <OlasBalance />
        <XdaiBalance />
        <Signer />
        <YourAgentWallet />
      </Container>
    </CustomModal>
  );
};
