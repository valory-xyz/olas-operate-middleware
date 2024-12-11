import { Divider, Flex, Typography } from 'antd';
import { useEffect, useMemo } from 'react';

import { CustomAlert } from '@/components/Alert';
import { getNativeTokenSymbol } from '@/config/tokens';
import { COLOR } from '@/constants/colors';
import { UNICODE_SYMBOLS } from '@/constants/symbols';
import { LOW_AGENT_SAFE_BALANCE } from '@/constants/thresholds';
import { TokenSymbol } from '@/enums/Token';
import { useElectronApi } from '@/hooks/useElectronApi';
import { useNeedsFunds } from '@/hooks/useNeedsFunds';
import { useServices } from '@/hooks/useServices';
import { useStakingProgram } from '@/hooks/useStakingProgram';

import { FundsToActivate } from './FundsToActivate';
import { InlineBanner } from './InlineBanner';
import { useLowFundsDetails } from './useLowFunds';

const { Text, Title } = Typography;

export const EmptyFunds = () => {
  const { selectedStakingProgramId } = useStakingProgram();

  const {
    hasEnoughEthForInitialFunding,
    hasEnoughOlasForInitialFunding,
    serviceFundRequirements,
    isInitialFunded,
    needsInitialFunding,
  } = useNeedsFunds(selectedStakingProgramId);

  const { selectedAgentConfig } = useServices();
  const { evmHomeChainId: homeChainId } = selectedAgentConfig;
  const nativeTokenSymbol = getNativeTokenSymbol(homeChainId);
  const { chainName, tokenSymbol, masterEoaAddress } = useLowFundsDetails();

  const electronApi = useElectronApi();

  useEffect(() => {
    if (
      hasEnoughEthForInitialFunding &&
      hasEnoughOlasForInitialFunding &&
      !isInitialFunded
    ) {
      electronApi.store?.set?.('isInitialFunded', true);
    }
  }, [
    electronApi.store,
    hasEnoughEthForInitialFunding,
    hasEnoughOlasForInitialFunding,
    isInitialFunded,
  ]);

  const olasRequired = useMemo(() => {
    if (hasEnoughOlasForInitialFunding) return null;
    const olas = serviceFundRequirements[homeChainId][TokenSymbol.OLAS];
    return `${UNICODE_SYMBOLS.OLAS}${olas} OLAS `;
  }, [homeChainId, hasEnoughOlasForInitialFunding, serviceFundRequirements]);

  const nativeTokenRequired = useMemo(() => {
    if (hasEnoughEthForInitialFunding) return null;
    const native = serviceFundRequirements[homeChainId][nativeTokenSymbol];
    return `${native} ${nativeTokenSymbol}`;
  }, [
    homeChainId,
    hasEnoughEthForInitialFunding,
    serviceFundRequirements,
    nativeTokenSymbol,
  ]);

  // if (!needsInitialFunding) return null;

  return (
    <CustomAlert
      fullWidth
      showIcon
      message={
        <Flex vertical gap={8} align="flex-start">
          <Title level={5} style={{ margin: 0 }}>
            Fund your agent
          </Title>

          <Text>
            To keep your agent operational, add
            <Text strong>{` ${LOW_AGENT_SAFE_BALANCE} ${tokenSymbol} `}</Text>
            on {chainName} chain to the safe signer.
          </Text>

          {masterEoaAddress && (
            <InlineBanner text="Your safe address" address={masterEoaAddress} />
          )}

          <Divider
            style={{ margin: '12px 0 8px 0', background: COLOR.PURPLE_LIGHT }}
          />

          <FundsToActivate />
        </Flex>
      }
      type="primary"
    />
  );
};
