import { Flex, Typography } from 'antd';

import { CustomAlert } from '@/components/Alert';
import { WalletOwnerType, WalletType } from '@/enums/Wallet';
import { useServices } from '@/hooks/useServices';

import { InlineBanner } from './InlineBanner';
import { useLowFundsDetails } from './useLowFunds';

const { Text, Title } = Typography;

/**
 * Alert for low safe signer (EOA) balance
 */
export const LowSafeSignerBalanceAlert = () => {
  const { chainName, tokenSymbol, masterEoaAddress } = useLowFundsDetails();
  const { selectedAgentConfig } = useServices();
  const token =
    selectedAgentConfig.operatingThresholds[WalletOwnerType.Master][
      WalletType.EOA
    ][tokenSymbol];

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
            <Text strong>{` ${token} ${tokenSymbol} `}</Text>
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
