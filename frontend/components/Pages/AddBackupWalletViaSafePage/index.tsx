import { Card, Flex, Typography } from 'antd';
import { isNil } from 'lodash';

import { CardTitle } from '@/components/Card/CardTitle';
import { UNICODE_SYMBOLS } from '@/constants/symbols';
import { DISCORD_TICKET_URL } from '@/constants/urls';
import { EvmChainId } from '@/enums/Chain';
import { useServices } from '@/hooks/useServices';
import { useMasterWalletContext } from '@/hooks/useWallet';

import { GoToMainPageButton } from '../GoToMainPageButton';

const { Text } = Typography;

/**
 * update as needed; check https://app.safe.global/new-safe/create for prefixes
 */
const safeChainPrefix = {
  [EvmChainId.Ethereum]: 'eth',
  [EvmChainId.Base]: 'base',
  [EvmChainId.Optimism]: 'oeth',
  [EvmChainId.Gnosis]: 'gno',
};

export const AddBackupWalletViaSafePage = () => {
  const {
    selectedAgentConfig: { evmHomeChainId: homeChainId },
  } = useServices();
  const { masterSafes, isFetched } = useMasterWalletContext();

  const masterSafe = masterSafes?.find(
    ({ evmChainId: chainId }) => homeChainId === chainId,
  );

  const safePrefix =
    masterSafe?.evmChainId && safeChainPrefix[masterSafe?.evmChainId];

  if (!isFetched) return null;
  if (isNil(masterSafe)) return null;

  return (
    <Card
      title={<CardTitle title="Add backup wallet via Safe" />}
      bordered={false}
      extra={<GoToMainPageButton />}
    >
      <Flex vertical gap={16}>
        <Flex vertical gap={4}>
          <Text>Manually add backup wallet via Safe interface:</Text>
          <a
            target="_blank"
            href={`https://app.safe.global/settings/setup?safe=${safePrefix}:${masterSafe.address}`}
          >
            Add backup wallet {UNICODE_SYMBOLS.EXTERNAL_LINK}
          </a>
        </Flex>

        <Flex vertical gap={4}>
          <Text>Not sure how?</Text>
          <a target="_blank" href={DISCORD_TICKET_URL}>
            Get community assistance via Discord ticket{' '}
            {UNICODE_SYMBOLS.EXTERNAL_LINK}
          </a>
        </Flex>
      </Flex>
    </Card>
  );
};
