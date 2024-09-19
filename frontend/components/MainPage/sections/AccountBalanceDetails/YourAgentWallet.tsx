import { WalletOutlined } from '@ant-design/icons';
import { Card, Flex, Typography } from 'antd';
import { useMemo } from 'react';

import { InfoTooltip } from '@/components/InfoTooltip';
import { COLOR } from '@/constants/colors';

import { InfoBreakdownList } from '../../../InfoBreakdown';
import { Container, infoBreakdownParentStyle } from './styles';

const { Title, Paragraph } = Typography;

export const YourAgentWallet = () => {
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
