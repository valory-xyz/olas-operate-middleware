import { WalletOutlined } from '@ant-design/icons';
import { Card, Flex, Typography } from 'antd';
import Image from 'next/image';
import { useMemo } from 'react';
import styled from 'styled-components';

import { Chain } from '@/client';
import { AddressLink } from '@/components/AddressLink';
import { InfoTooltip } from '@/components/InfoTooltip';
import { COLOR } from '@/constants/colors';
import { SERVICE_REGISTRY_L2_CONTRACT_ADDRESS } from '@/constants/contractAddresses';
import { UNICODE_SYMBOLS } from '@/constants/symbols';
import { useAddress } from '@/hooks/useAddress';
import { useBalance } from '@/hooks/useBalance';
import { useReward } from '@/hooks/useReward';
import { useServices } from '@/hooks/useServices';
import { balanceFormat } from '@/utils/numberFormatters';
import { truncateAddress } from '@/utils/truncate';

import { InfoBreakdownList } from '../../../InfoBreakdown';
import { SignerTitle } from './SignerTitle';
import { Container, infoBreakdownParentStyle } from './styles';

const { Title, Paragraph, Text } = Typography;

const OlasTitle = () => (
  <Flex align="center">
    <Title level={5} className="m-0 text-sm">
      OLAS
    </Title>
    &nbsp;
    <InfoTooltip>
      <Paragraph className="text-sm m-0">
        Agent rewards accumulate in the staking contract. The agent is designed
        to claim rewards periodically. Withdrawal of claimed rewards isn’t
        available yet.
      </Paragraph>
    </InfoTooltip>
  </Flex>
);

const XdaiTitle = () => (
  <Flex align="center">
    <Title level={5} className="m-0 text-sm">
      XDAI
    </Title>
    &nbsp;
    <InfoTooltip>
      <Paragraph className="text-sm m-0">
        XDAI is used by the agent to engage in prediction markets. This amount
        will fluctuate based on your agent’s performance.
      </Paragraph>
    </InfoTooltip>
  </Flex>
);

const OwnershipNftTitle = () => (
  <Text className="text-sm text-light">
    Ownership NFT&nbsp;
    <InfoTooltip>
      <Flex gap={4} vertical>
        <Text strong className="text-sm">
          You own your agent
        </Text>
        <Paragraph className="text-sm m-0">
          Agents are minted through the Olas Registry. Each agent has an NFT
          that gives its owner control over the agent’s settings.
        </Paragraph>
      </Flex>
    </InfoTooltip>
  </Text>
);

const ServiceIdTitle = () => (
  <Text className="text-sm text-light">
    ID&nbsp;
    <InfoTooltip placement="topRight">
      <Paragraph className="text-sm m-0">
        Each minted agent gets a unique ID. Technically, agents are referred to
        as ‘services’.
      </Paragraph>
    </InfoTooltip>
  </Text>
);

const NftCard = styled(Card)`
  .ant-card-body {
    padding: 0;
    img {
      border-radius: 8px;
    }
  }
`;

const ServiceAndNftDetails = () => {
  const { serviceId } = useServices();
  const serviceAddress =
    SERVICE_REGISTRY_L2_CONTRACT_ADDRESS[`${Chain.GNOSIS}`];

  return (
    <NftCard>
      <Flex>
        <Flex>
          <Image
            width={64}
            height={64}
            alt="NFT"
            src="https://zos.alipayobjects.com/rmsportal/jkjgkEfvpUPVyRjUImniVslZfWPnJuuZ.png"
          />
        </Flex>
        <Flex
          style={{ padding: '8px 16px' }}
          align="center"
          justify="space-between"
          flex={1}
        >
          <Flex vertical>
            <OwnershipNftTitle />
            <a
              href={`https://gnosis.blockscout.com/token/${serviceAddress}/instance/${serviceId}`}
              target="_blank"
            >
              {truncateAddress(serviceAddress)} {UNICODE_SYMBOLS.EXTERNAL_LINK}
            </a>
          </Flex>

          <Flex vertical>
            <ServiceIdTitle />
            <a
              href={`https://registry.olas.network/gnosis/services/${serviceId}`}
              target="_blank"
            >
              {serviceId} {UNICODE_SYMBOLS.EXTERNAL_LINK}
            </a>
          </Flex>
        </Flex>
      </Flex>
    </NftCard>
  );
};

export const YourAgentWallet = () => {
  const { agentSafeBalance } = useBalance();
  const { accruedServiceStakingRewards } = useReward();
  const {
    instanceAddress: agentInstanceAddress,
    multisigAddress: agentSafeAddress,
  } = useAddress();

  const olasBalances = useMemo(() => {
    return [
      {
        title: 'Claimed rewards',
        value: balanceFormat(agentSafeBalance?.OLAS ?? 0, 2),
      },
      {
        title: 'Unclaimed rewards',
        value: balanceFormat(accruedServiceStakingRewards ?? 0, 2),
      },
    ];
  }, [agentSafeBalance?.OLAS, accruedServiceStakingRewards]);

  const xdaiBalances = useMemo(() => {
    return [
      {
        title: <XdaiTitle />,
        value: balanceFormat(agentSafeBalance?.ETH ?? 0, 2),
      },
    ];
  }, [agentSafeBalance?.ETH]);

  const signerInfo = useMemo(() => {
    return [
      {
        title: <SignerTitle />,
        value: <AddressLink address={agentInstanceAddress} />,
      },
    ];
  }, [agentInstanceAddress]);

  return (
    <Card>
      <Container>
        <Flex vertical gap={12}>
          <WalletOutlined style={{ fontSize: 24, color: COLOR.TEXT_LIGHT }} />
          <Flex justify="space-between" className="w-full">
            <Title level={5} className="m-0 text-base">
              Your agent
            </Title>
            <AddressLink address={agentSafeAddress} />
          </Flex>
        </Flex>

        <Flex vertical gap={8}>
          <OlasTitle />
          <InfoBreakdownList
            list={olasBalances.map((item) => ({
              left: item.title,
              leftClassName: 'text-light text-sm',
              right: `${item.value} OLAS`,
            }))}
            parentStyle={infoBreakdownParentStyle}
          />
        </Flex>

        <Flex vertical gap={8}>
          <InfoBreakdownList
            list={xdaiBalances.map((item) => ({
              left: item.title,
              leftClassName: 'text-light text-sm',
              right: `${item.value} XDAI`,
            }))}
            parentStyle={infoBreakdownParentStyle}
          />
        </Flex>

        <Flex vertical gap={8}>
          <InfoBreakdownList
            list={signerInfo.map((item) => ({
              left: item.title,
              leftClassName: 'text-light text-sm',
              right: item.value,
              rightClassName: 'font-normal',
            }))}
            parentStyle={infoBreakdownParentStyle}
          />
        </Flex>

        <ServiceAndNftDetails />
      </Container>
    </Card>
  );
};
