import { Button, Flex, Skeleton, Typography } from 'antd';
import { isNumber } from 'lodash';
import { useCallback, useEffect, useMemo, useState } from 'react';
import styled from 'styled-components';

import { AnimateNumber } from '@/components/ui/animations/AnimateNumber';
import { UNICODE_SYMBOLS } from '@/constants/symbols';
import { Pages } from '@/enums/Pages';
import { useFeatureFlag } from '@/hooks/useFeatureFlag';
import { usePageState } from '@/hooks/usePageState';
import { usePrevious } from '@/hooks/usePrevious';
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
    // mainOlasBalance: wholeMainOlasBalance,
    hasMainOlasBalanceAnimatedOnLoad,
    setMainOlasBalanceAnimated,
  } = useSharedContext();
  const [isAnimating, setIsAnimating] = useState(false);

  // const mainOlasBalance = wholeMainOlasBalance
  //   ? round(wholeMainOlasBalance, 4)
  //   : 0;
  const previousMainOlasBalance = usePrevious(mainOlasBalance);

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

    // if balance has NOT changed
    // if (mainOlasBalance === previousMainOlasBalance) return false;

    return true;
  }, [
    isMainOlasBalanceLoading,
    mainOlasBalance,
    previousMainOlasBalance,
    hasMainOlasBalanceAnimatedOnLoad,
  ]);

  const onAnimationComplete = useCallback(() => {
    setIsAnimating(false);
  }, []);

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
                triggerAnimation={isAnimating || !!triggerAnimation}
                onAnimationComplete={onAnimationComplete}
              />
            </Balance>
            <span className="balance-currency">OLAS</span>
          </Flex>
        </Flex>
      )}
    </CardSection>
  );
};
