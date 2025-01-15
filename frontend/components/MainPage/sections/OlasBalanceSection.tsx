import { Button, Flex, Skeleton, Typography } from 'antd';
import { isNumber } from 'lodash';
import { useEffect, useMemo } from 'react';
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
    previousMainOlasBalance,
    hasMainOlasBalanceAnimatedOnLoad,
    setMainOlasBalanceAnimated,
  } = useSharedContext();

  useEffect(() => {
    if (
      !isMainOlasBalanceLoading &&
      isNumber(mainOlasBalance) &&
      !hasMainOlasBalanceAnimatedOnLoad
    ) {
      setMainOlasBalanceAnimated(true);
    }
  }, [
    isMainOlasBalanceLoading,
    mainOlasBalance,
    hasMainOlasBalanceAnimatedOnLoad,
    setMainOlasBalanceAnimated,
  ]);

  // boolean to trigger animation
  const triggerAnimation = useMemo(() => {
    if (isMainOlasBalanceLoading) return false;

    if (!isNumber(mainOlasBalance)) return false;

    // if balance has not been animated on load
    if (!hasMainOlasBalanceAnimatedOnLoad) return true;

    // if previous balance is not a number but already animated
    // example: navigating to another page and coming back
    if (
      hasMainOlasBalanceAnimatedOnLoad &&
      !isNumber(previousMainOlasBalance)
    ) {
      return false;
    }

    // if balance has changed, animate
    if (mainOlasBalance !== previousMainOlasBalance) return true;

    return false;
  }, [
    isMainOlasBalanceLoading,
    mainOlasBalance,
    previousMainOlasBalance,
    hasMainOlasBalanceAnimatedOnLoad,
  ]);

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
                triggerAnimation={!!triggerAnimation}
              />
            </Balance>
            <span className="balance-currency">OLAS</span>
          </Flex>
        </Flex>
      )}
    </CardSection>
  );
};
