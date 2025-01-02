import { Flex, Typography } from 'antd';
import { useMemo } from 'react';

import { CustomAlert } from '@/components/Alert';
import { WalletType } from '@/enums/Wallet';
import {
  useMasterBalances,
  useServiceBalances,
} from '@/hooks/useBalanceContext';
import { useServices } from '@/hooks/useServices';
import { useStore } from '@/hooks/useStore';

import { InlineBanner } from './InlineBanner';
import { useLowFundsDetails } from './useLowFunds';

const { Text, Title } = Typography;

/**
 * Alert for low operating (safe) balance
 */
export const LowOperatingBalanceAlert = () => {
  const { storeState } = useStore();
  const { selectedAgentType, selectedService, selectedAgentConfig } =
    useServices();
  const { isLoaded: isBalanceLoaded, isMasterSafeLowOnNativeGas } =
    useMasterBalances();
  const { serviceSafeBalances, serviceSafeNative } = useServiceBalances(
    selectedService?.service_config_id,
  );

  const {
    chainName,
    tokenSymbol,
    masterSafeAddress,
    masterThresholds,
    agentThresholds,
  } = useLowFundsDetails();

  const isLowBalance = useMemo(() => {
    if (!agentThresholds) return false;
    if (!serviceSafeNative) return false;

    // Check both master and agent safes
    return (
      isMasterSafeLowOnNativeGas ||
      serviceSafeNative.balance < agentThresholds[WalletType.Safe][tokenSymbol]
    );
  }, [
    isMasterSafeLowOnNativeGas,
    agentThresholds,
    tokenSymbol,
    serviceSafeNative,
  ]);

  if (!isBalanceLoaded) return null;
  if (!agentThresholds) return null;
  if (!storeState?.[selectedAgentType]?.isInitialFunded) return;
  if (!isLowBalance) return null;

  return (
    <CustomAlert
      fullWidth
      type="error"
      showIcon
      message={
        <Flex vertical gap={8} align="flex-start">
          <Title level={5} style={{ margin: 0 }}>
            Operating balance is too low
          </Title>
          <Text>
            To run your agent, add at least
            <Text strong>{` ${
              masterThresholds[WalletType.Safe][tokenSymbol]
            } ${tokenSymbol} `}</Text>
            on {chainName} chain to your safe.
          </Text>
          <Text>
            Your agent is at risk of missing its targets, which would result in
            several days&apos; suspension.
          </Text>

          {masterSafeAddress && (
            <InlineBanner
              text="Your safe address"
              address={masterSafeAddress}
            />
          )}
        </Flex>
      }
    />
  );
};
