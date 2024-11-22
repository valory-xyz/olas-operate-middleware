import { Card, Flex, Skeleton, Tooltip, Typography } from 'antd';
import { isEmpty, isNil } from 'lodash';
import Image from 'next/image';
import { useMemo } from 'react';
import styled from 'styled-components';

import { OLAS_CONTRACTS } from '@/config/olasContracts';
import { UNICODE_SYMBOLS } from '@/constants/symbols';
import { ChainId } from '@/enums/Chain';
import { ContractType } from '@/enums/Contract';
import { TokenSymbol } from '@/enums/Token';
import { AgentSafe, Safe } from '@/enums/Wallet';
import {
  useBalanceContext,
  useServiceBalances,
} from '@/hooks/useBalanceContext';
import { useReward } from '@/hooks/useReward';
import { useService } from '@/hooks/useService';
import { Address } from '@/types/Address';
import { generateName } from '@/utils/agentName';
import { balanceFormat } from '@/utils/numberFormatters';
import { truncateAddress } from '@/utils/truncate';

import { AddressLink } from '../AddressLink';
import { InfoBreakdownList } from '../InfoBreakdown';
import { Container, infoBreakdownParentStyle } from './styles';
import { OlasTitle, OwnershipNftTitle, ServiceIdTitle } from './Titles';

const { Text, Paragraph } = Typography;

const NftCard = styled(Card)`
  .ant-card-body {
    padding: 0;
    img {
      border-radius: 8px;
    }
  }
`;

const SafeAddress = ({ serviceSafe }: { serviceSafe: Safe }) => {
  const multisigAddress = serviceSafe.address;

  return (
    <Flex vertical gap={8}>
      <InfoBreakdownList
        list={[
          {
            left: 'Wallet Address',
            leftClassName: 'text-light text-sm',
            right: <AddressLink address={multisigAddress} />,
            rightClassName: 'font-normal text-sm',
          },
        ]}
        parentStyle={infoBreakdownParentStyle}
      />
    </Flex>
  );
};

const AgentTitle = ({ serviceSafe }: { serviceSafe: AgentSafe }) => {
  const agentName = useMemo(
    () => (serviceSafe ? generateName(serviceSafe.address) : '--'),
    [serviceSafe],
  );

  return (
    <Flex vertical gap={12}>
      <Flex gap={12}>
        <Image
          width={36}
          height={36}
          alt="Agent wallet"
          src="/agent-wallet.png"
        />

        <Flex vertical className="w-full">
          <Text className="m-0 text-sm" type="secondary">
            Your agent
          </Text>
          <Flex justify="space-between">
            <Tooltip
              arrow={false}
              title={
                <Paragraph className="text-sm m-0">
                  This is your agent&apos;s unique name
                </Paragraph>
              }
              placement="top"
            >
              <Text strong>{agentName}</Text>
            </Tooltip>
            {/* TODO: address multi-agent at later point */}
            <a
              href={`https://predict.olas.network/agents/${serviceSafe.address}`}
              target="_blank"
              className="text-sm"
            >
              Agent profile {UNICODE_SYMBOLS.EXTERNAL_LINK}
            </a>
          </Flex>
        </Flex>
      </Flex>
    </Flex>
  );
};

const ServiceAndNftDetails = ({
  serviceConfigId,
}: {
  serviceConfigId: string;
}) => {
  const serviceRegistryL2ContractAddress =
    OLAS_CONTRACTS[ChainId.Gnosis][ContractType.ServiceRegistryL2].address;

  return (
    <NftCard>
      <Flex>
        <Flex>
          <Image width={78} height={78} alt="NFT" src="/NFT.png" />
        </Flex>
        <Flex
          style={{ padding: '16px 12px' }}
          align="center"
          justify="space-between"
          flex={1}
        >
          <Flex vertical>
            <OwnershipNftTitle />
            <a
              href={`https://gnosis.blockscout.com/token/${serviceRegistryL2ContractAddress}/instance/${serviceConfigId}`}
              target="_blank"
            >
              {truncateAddress(serviceRegistryL2ContractAddress as Address)}{' '}
              {UNICODE_SYMBOLS.EXTERNAL_LINK}
            </a>
          </Flex>

          <Flex vertical>
            <ServiceIdTitle />
            <a
              href={`https://registry.olas.network/gnosis/services/${serviceConfigId}`}
              target="_blank"
            >
              {serviceConfigId} {UNICODE_SYMBOLS.EXTERNAL_LINK}
            </a>
          </Flex>
        </Flex>
      </Flex>
    </NftCard>
  );
};

export const YourAgentWallet = ({
  serviceConfigId,
}: {
  serviceConfigId: string;
}) => {
  const { isLoaded } = useBalanceContext();
  const { serviceEoa, serviceSafes } = useService({ serviceConfigId });
  const { serviceSafeBalances, serviceEoaBalances, serviceStakedBalances } =
    useServiceBalances(serviceConfigId);

  const {
    availableRewardsForEpochEth,
    isEligibleForRewards,
    accruedServiceStakingRewards,
  } = useReward();

  const reward = useMemo(() => {
    if (!isLoaded) return <Skeleton.Input size="small" active />;
    if (!isEligibleForRewards) return 'Not yet earned';
    return `~${balanceFormat(availableRewardsForEpochEth, 2)} OLAS`;
  }, [isLoaded, isEligibleForRewards, availableRewardsForEpochEth]);

  const serviceSafeOlasBalances = useMemo(
    () =>
      serviceSafeBalances?.filter(
        (balance) => balance.symbol === TokenSymbol.OLAS,
      ),
    [serviceSafeBalances],
  );

  // TODO: refactor for multichain/agent
  const serviceSafeRewards = useMemo(
    () => [
      {
        title: 'Claimed rewards',
        value: `${balanceFormat(serviceSafeOlasBalances?.[0].balance ?? 0, 2)} OLAS`,
      },
      {
        title: 'Unclaimed rewards',
        value: `${balanceFormat(accruedServiceStakingRewards, 2)} OLAS`,
      },
      {
        title: 'Current epoch rewards',
        value: reward,
      },
    ],
    [accruedServiceStakingRewards, reward, serviceSafeOlasBalances],
  );

  const serviceSafeNativeBalances = useMemo(
    () => serviceSafeBalances?.filter((balance) => balance.isNative),
    [serviceSafeBalances],
  );

  const serviceEoaNativeBalances = useMemo(
    () => serviceEoaBalances?.filter((balance) => balance.isNative),
    [serviceEoaBalances],
  );

  const serviceSafe = useMemo(() => {
    if (isNil(serviceSafes) || isEmpty(serviceSafes)) return null;
    return serviceSafes[0];
  }, [serviceSafes]);

  if (isNil(serviceSafe)) return null;

  return (
    <Card title={<AgentTitle serviceSafe={serviceSafe} />}>
      <Container>
        <SafeAddress serviceSafe={serviceSafe} />

        {!isEmpty(serviceSafeRewards) && (
          <Flex vertical gap={8}>
            <OlasTitle />
            <InfoBreakdownList
              list={serviceSafeRewards.map((item) => ({
                left: item.title,
                leftClassName: 'text-light text-sm',
                right: item.value,
              }))}
              parentStyle={infoBreakdownParentStyle}
            />
          </Flex>
        )}

        {!isEmpty(serviceStakedBalances) && (
          <Flex vertical gap={8}>
            <InfoBreakdownList
              list={serviceSafeNativeBalances.map((balance) => ({
                left: balance.symbol,
                leftClassName: 'text-light text-sm',
                right: `${balanceFormat(balance.balance, 2)} ${balance.symbol}`,
              }))}
              parentStyle={infoBreakdownParentStyle}
            />
          </Flex>
        )}

        {serviceEoa?.address && !isEmpty(serviceEoaNativeBalances) && (
          <Flex vertical gap={8}>
            <InfoBreakdownList
              list={
                serviceEoaNativeBalances.map((balance) => ({
                  left: balance.symbol,
                  leftClassName: 'text-light text-sm',
                  right: `${balanceFormat(balance.balance, 2)} ${balance.symbol}`,
                })) ?? []
              }
              parentStyle={infoBreakdownParentStyle}
            />
          </Flex>
        )}

        <ServiceAndNftDetails serviceConfigId={serviceConfigId} />
      </Container>
    </Card>
  );
};
