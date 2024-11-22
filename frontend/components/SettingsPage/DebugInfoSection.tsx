import { CopyOutlined } from '@ant-design/icons';
import {
  Button,
  Col,
  Flex,
  message,
  Row,
  Spin,
  Tooltip,
  Typography,
} from 'antd';
import { isEmpty, isNil } from 'lodash';
import { useCallback, useMemo, useState } from 'react';
import styled from 'styled-components';

import { COLOR } from '@/constants/colors';
import { UNICODE_SYMBOLS } from '@/constants/symbols';
import { EXPLORER_URL } from '@/constants/urls';
import { MODAL_WIDTH } from '@/constants/width';
import { WalletBalanceResult } from '@/context/BalanceProvider';
import { ChainId, ChainName } from '@/enums/Chain';
import { TokenSymbol } from '@/enums/Token';
import { WalletType } from '@/enums/Wallet';
import {
  useBalanceContext,
  useMasterBalances,
} from '@/hooks/useBalanceContext';
import { useServices } from '@/hooks/useServices';
import { useMasterWalletContext } from '@/hooks/useWallet';
import { Address } from '@/types/Address';
import { copyToClipboard } from '@/utils/copyToClipboard';
import { truncateAddress } from '@/utils/truncate';

import { CardSection } from '../styled/CardSection';
import { CustomModal } from '../styled/CustomModal';

const { Text, Title } = Typography;

const Card = styled.div`
  padding: 16px 24px;
  border-bottom: 1px solid ${COLOR.BORDER_GRAY};
`;

const ICON_STYLE = { color: '#606F85' };

const getBalanceData = (walletBalances: WalletBalanceResult[]) => {
  const result: { [chainId: number]: { [tokenSymbol: string]: number } } = {};

  for (const walletBalanceResult of walletBalances) {
    const { chainId, symbol } = walletBalanceResult;
    if (!result[chainId]) result[chainId] = {};
    if (!result[chainId][symbol]) result[chainId][symbol] = 0;
    result[chainId][symbol] += walletBalanceResult.balance;
  }

  return { balance: result };
};

const DebugItem = ({
  item,
}: {
  item: {
    title: string;
    balance: Record<number | ChainId, Record<string | TokenSymbol, number>>;
    address: `0x${string}`;
    link?: { title: string; href: string };
  };
}) => {
  const truncatedAddress = truncateAddress(item.address);

  const onCopyToClipboard = useCallback(
    () =>
      copyToClipboard(item.address).then(() =>
        message.success('Address copied!'),
      ),
    [item.address],
  );

  const chainIds = Object.keys(item.balance);

  return (
    <Card>
      <Title level={5} className="m-0 mb-8 text-base">
        {item.title}
      </Title>
      <Row>
        <Col span={12}>
          <Flex vertical gap={4} align="flex-start">
            <Text type="secondary" className="text-sm">
              Balance
            </Text>
            {Object.entries(item.balance).map(([chainId, balance]) => {
              return (
                <Flex key={chainId} vertical gap={4}>
                  <Text type="secondary" className="text-sm">
                    {ChainName[+chainId as keyof typeof ChainName]}
                  </Text>
                  {Object.entries(balance).map(([tokenSymbol, balance]) => {
                    return (
                      <Flex key={tokenSymbol} gap={12}>
                        <Text>{balance}</Text>
                        <Text type="secondary">{tokenSymbol}</Text>
                      </Flex>
                    );
                  })}
                </Flex>
              );
            })}
          </Flex>
        </Col>

        <Col span={12}>
          {chainIds.map((chainId) => (
            <Flex vertical gap={4} align="flex-start" key={chainId}>
              <Text type="secondary" className="text-sm">
                Address{' '}
                {chainIds.length > 1 &&
                  `on ${ChainName[+chainId as keyof typeof ChainName]}`}
              </Text>
              <Flex gap={12}>
                <a
                  target="_blank"
                  href={`${EXPLORER_URL[+chainId as keyof typeof EXPLORER_URL]}/address/${item.address}`}
                >
                  {truncatedAddress}
                </a>
                <Tooltip title="Copy to clipboard">
                  <CopyOutlined
                    style={ICON_STYLE}
                    onClick={onCopyToClipboard}
                  />
                </Tooltip>
              </Flex>
            </Flex>
          ))}
        </Col>
      </Row>
      {item.link ? (
        <Row className="mt-8">
          <a target="_blank" href={item.link.href}>
            {item.link.title} {UNICODE_SYMBOLS.EXTERNAL_LINK}
          </a>
        </Row>
      ) : null}
    </Card>
  );
};

export const DebugInfoSection = () => {
  const { masterEoa, masterSafes } = useMasterWalletContext();
  const { serviceAddresses } = useServices();
  const { walletBalances } = useBalanceContext();
  const { masterEoaBalances, masterSafeBalances } = useMasterBalances();

  const [isModalOpen, setIsModalOpen] = useState(false);
  const showModal = useCallback(() => setIsModalOpen(true), []);
  const handleCancel = useCallback(() => setIsModalOpen(false), []);

  const data = useMemo(() => {
    if (isNil(masterEoa)) return null;
    if (isNil(masterSafes) || isEmpty(masterSafes)) return null;
    if (isNil(walletBalances) || isEmpty(walletBalances)) return null;

    const result: {
      title: string;
      balance: Record<number | ChainId, Record<string | TokenSymbol, number>>;
      address: Address;
      link?: { title: string; href: string };
    }[] = [];

    result.push({
      title: 'Master EOA',
      ...getBalanceData(masterEoaBalances),
      address: masterEoa.address,
    });

    masterSafes.forEach((wallet) => {
      result.push({
        title: 'Master Safe',
        ...getBalanceData(masterSafeBalances),
        address: wallet.address,
      });
    });

    serviceAddresses?.forEach((wallet) => {
      if (wallet.type === WalletType.EOA) {
        result.push({
          title: 'Agent Instance EOA',
          ...getBalanceData(
            walletBalances.filter(
              (balance) => balance.walletAddress === wallet.address,
            ),
          ),
          address: wallet.address,
        });
      }

      if (wallet.type === WalletType.Safe) {
        result.push({
          title: 'Agent Safe',
          ...getBalanceData(walletBalances),
          address: wallet.address,
        });
      }
    });

    return result;
  }, [
    masterEoa,
    masterEoaBalances,
    masterSafeBalances,
    masterSafes,
    serviceAddresses,
    walletBalances,
  ]);

  return (
    <CardSection vertical gap={8} align="start" padding="24px">
      <Text strong>Debug data (for devs)</Text>
      <Button type="primary" ghost size="large" onClick={showModal}>
        Show debug data
      </Button>
      <CustomModal
        title="Debug data"
        open={isModalOpen}
        footer={null}
        width={MODAL_WIDTH}
        onCancel={handleCancel}
      >
        {data ? (
          data.map((item) => <DebugItem key={item.address} item={item} />)
        ) : (
          <Flex justify="center" align="center" flex="auto">
            <Spin size="large" />
          </Flex>
        )}
      </CustomModal>
    </CardSection>
  );
};
