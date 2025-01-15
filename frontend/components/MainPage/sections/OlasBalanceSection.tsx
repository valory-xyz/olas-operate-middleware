import { Button, Flex, Skeleton, Typography } from 'antd';
import { useEffect } from 'react';
import styled from 'styled-components';

import { AnimateNumber } from '@/components/ui/animations/AnimateNumber';
import { UNICODE_SYMBOLS } from '@/constants/symbols';
import { Pages } from '@/enums/Pages';
import { useFeatureFlag } from '@/hooks/useFeatureFlag';
import { usePageState } from '@/hooks/usePageState';
import { useSharedContext } from '@/hooks/useSharedContext';

import { CardSection } from '../../styled/CardSection';

const { Text } = Typography;

const Balance = styled.span`
  letter-spacing: -2px;
  margin-right: 4px;
`;

export const MainOlasBalance = () => {
  const isBalanceBreakdownEnabled = useFeatureFlag('manage-wallet');
  const { goto } = usePageState();
  const {
    isMainOlasBalanceLoading,
    mainOlasBalance,
    hasMainOlasBalanceAnimated,
    setMainOlasBalanceAnimated,
  } = useSharedContext();

  useEffect(() => {
    if (!hasMainOlasBalanceAnimated) {
      setMainOlasBalanceAnimated(true);
    }
  }, [hasMainOlasBalanceAnimated, setMainOlasBalanceAnimated]);

  return (
    <CardSection
      vertical
      gap={8}
      bordertop="true"
      borderbottom="true"
      padding="16px 24px"
    >
      {isMainOlasBalanceLoading ? (
        <Skeleton.Input active size="large" style={{ margin: '4px 0' }} />
      ) : (
        <Flex vertical gap={8}>
          <Flex align="center" justify="space-between">
            <Text type="secondary">Current balance</Text>
            {isBalanceBreakdownEnabled && (
              <Button
                size="small"
                onClick={() => goto(Pages.ManageWallet)}
                className="text-sm"
              >
                Manage wallet
              </Button>
            )}
          </Flex>

          <Flex align="end">
            <span className="balance-symbol">{UNICODE_SYMBOLS.OLAS}</span>
            <Balance className="balance">
              <AnimateNumber
                value={mainOlasBalance}
                hasAnimated={hasMainOlasBalanceAnimated}
              />
            </Balance>
            <span className="balance-currency">OLAS</span>
          </Flex>
        </Flex>
      )}
    </CardSection>
  );
};
