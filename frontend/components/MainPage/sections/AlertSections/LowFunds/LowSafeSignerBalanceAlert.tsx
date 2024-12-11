import { Flex, Typography } from 'antd';

import { CustomAlert } from '@/components/Alert';
import { LOW_AGENT_SAFE_BALANCE } from '@/constants/thresholds';

import { InlineBanner } from './InlineBanner';
import { useLowFundsDetails } from './useLowFunds';

const { Text, Title } = Typography;

export const LowSafeSignerBalanceAlert = () => {
  const { chainName, tokenSymbol, masterEoaAddress } = useLowFundsDetails();

  return (
    <CustomAlert
      fullWidth
      type="error"
      showIcon
      message={
        <Flex vertical gap={8} align="flex-start">
          <Title level={5} style={{ margin: 0 }}>
            Safe signer balance is too low
          </Title>
          <Text>
            To keep your agent operational, add
            <Text strong>{` ${LOW_AGENT_SAFE_BALANCE} ${tokenSymbol} `}</Text>
            on {chainName} chain to the safe signer.
          </Text>
          <Text>
            Your agent is at risk of missing its targets, which would result in
            several days&apos; suspension.
          </Text>

          {masterEoaAddress && (
            <InlineBanner
              text="Safe signer address"
              address={masterEoaAddress}
            />
          )}
        </Flex>
      }
    />
  );
};
