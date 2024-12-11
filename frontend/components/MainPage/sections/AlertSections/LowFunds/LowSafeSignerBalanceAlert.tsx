import { Flex, Typography } from 'antd';
import { useMemo } from 'react';

import { CustomAlert } from '@/components/Alert';
import { LOW_AGENT_SAFE_BALANCE } from '@/constants/thresholds';
import { useMasterBalances } from '@/hooks/useBalanceContext';
import { useChainDetails } from '@/hooks/useChainDetails';
import { useServices } from '@/hooks/useServices';
import { useStore } from '@/hooks/useStore';
import { useMasterWalletContext } from '@/hooks/useWallet';

import { InlineBanner } from './InlineBanner';

const { Text, Title } = Typography;

export const LowSafeSignerBalanceAlert = () => {
  const { storeState } = useStore();
  const { selectedAgentConfig } = useServices();
  const { masterEoa } = useMasterWalletContext();
  const { isLoaded: isBalanceLoaded, masterEoaNativeGasBalance } =
    useMasterBalances();

  const isLowBalance = useMemo(() => {
    if (!masterEoaNativeGasBalance) return false;
    return masterEoaNativeGasBalance < LOW_AGENT_SAFE_BALANCE;
  }, [masterEoaNativeGasBalance]);

  const homeChainId = selectedAgentConfig.evmHomeChainId;
  const { name, symbol } = useChainDetails(homeChainId);

  if (!isBalanceLoaded) return null;
  if (!storeState?.isInitialFunded) return;
  if (!isLowBalance) return null;

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
            <Text strong>{` ${LOW_AGENT_SAFE_BALANCE} ${symbol} `}</Text>
            on {name} chain to the safe signer.
          </Text>
          <Text>
            Your agent is at risk of missing its targets, which would result in
            several days&apos; suspension.
          </Text>

          {masterEoa?.address && (
            <InlineBanner
              text="Safe signer address"
              address={masterEoa.address}
            />
          )}
        </Flex>
      }
    />
  );
};
