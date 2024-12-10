import { Flex, Typography } from 'antd';
import { useMemo } from 'react';

import { CustomAlert } from '@/components/Alert';
import { LOW_MASTER_SAFE_BALANCE } from '@/constants/thresholds';
import { useBalanceContext } from '@/hooks/useBalanceContext';
import { useChainDetails } from '@/hooks/useChainDetails';
import { useServices } from '@/hooks/useServices';
import { useStore } from '@/hooks/useStore';
import { useMasterWalletContext } from '@/hooks/useWallet';

import { InlineBanner } from './InlineBanner';

const { Text, Title } = Typography;

export const LowOperatingBalanceAlert = () => {
  const { selectedAgentConfig } = useServices();
  const { evmHomeChainId: homeChainId } = selectedAgentConfig;

  const { masterSafes } = useMasterWalletContext();
  const { isLoaded: isBalanceLoaded, isLowBalance } = useBalanceContext();
  const { storeState } = useStore();

  const { name, symbol } = useChainDetails(homeChainId);

  const selectedMasterSafe = useMemo(() => {
    if (!masterSafes) return;
    if (!homeChainId) return;

    return masterSafes.find(
      (masterSafe) => masterSafe.evmChainId === homeChainId,
    );
  }, [masterSafes, homeChainId]);

  // if (!isBalanceLoaded) return null;
  // if (!storeState?.isInitialFunded) return;
  // if (!isLowBalance) return null;

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
            <Text strong>{` ${LOW_MASTER_SAFE_BALANCE} ${symbol} `}</Text>
            on {name} chain to your safe.
          </Text>
          <Text>
            Your agent is at risk of missing its targets, which would result in
            several days&apos; suspension.
          </Text>

          {selectedMasterSafe?.address && (
            <InlineBanner
              text="Your safe address"
              address={selectedMasterSafe.address}
            />
          )}
        </Flex>
      }
    />
  );
};
