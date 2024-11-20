import { Card, Flex, Typography } from 'antd';

import { CardTitle } from '@/components/Card/CardTitle';
import { UNICODE_SYMBOLS } from '@/constants/symbols';
import { DISCORD_TICKET_URL } from '@/constants/urls';
import { ChainId } from '@/enums/Chain';
import { MasterSafe } from '@/enums/Wallet';

import { GoToMainPageButton } from '../GoToMainPageButton';

const { Text } = Typography;

/**
 * update as needed; check https://app.safe.global/new-safe/create for prefixes
 */
const safeChainPrefix = {
  [ChainId.Ethereum]: 'eth',
  [ChainId.Base]: 'base',
  [ChainId.Optimism]: 'oeth',
  [ChainId.Gnosis]: 'gno',
};

export const AddBackupWalletViaSafePage = (masterSafe: MasterSafe) => {
  const { chainId, address } = masterSafe;

  const safePrefix = safeChainPrefix[chainId];

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
            href={`https://app.safe.global/settings/setup?safe=${safePrefix}:${address}`}
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
