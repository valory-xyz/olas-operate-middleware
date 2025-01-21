import { Divider, Flex, Typography } from 'antd';

import { CustomAlert } from '@/components/Alert';
import { COLOR } from '@/constants/colors';
import { Optional } from '@/types/Util';

import { FundsToActivate } from './FundsToActivate';
import { InlineBanner } from './InlineBanner';
import { useLowFundsDetails } from './useLowFunds';

const { Text, Title } = Typography;

const PurpleDivider = () => (
  <Divider style={{ margin: '12px 0 8px 0', background: COLOR.PURPLE_LIGHT }} />
);

type EmptyFundsProps = { requiredSignerFunds: Optional<number> };

export const EmptyFunds = ({ requiredSignerFunds }: EmptyFundsProps) => {
  const { chainName, tokenSymbol, masterEoaAddress } = useLowFundsDetails();

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
            <Text strong>{` ${requiredSignerFunds} ${tokenSymbol} `}</Text>
            on {chainName} chain to the safe signer.
          </Text>

          {masterEoaAddress && (
            <InlineBanner text="Your safe address" address={masterEoaAddress} />
          )}
          <PurpleDivider />
          <FundsToActivate stakingFundsRequired nativeFundsRequired />
        </Flex>
      }
      type="primary"
    />
  );
};
