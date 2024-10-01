import { InfoCircleOutlined } from '@ant-design/icons';
import { Flex, Popover, PopoverProps, Typography } from 'antd';

import { COLOR } from '@/constants/colors';
import { UNICODE_SYMBOLS } from '@/constants/symbols';
import { SUPPORT_URL } from '@/constants/urls';
import { useStakingContractInfo } from '@/hooks/useStakingContractInfo';

const { Paragraph, Text } = Typography;

const cannotStartAgentText = (
  <Text style={{ color: COLOR.RED }}>
    Cannot start agent&nbsp;
    <InfoCircleOutlined />
  </Text>
);

const otherPopoverProps: PopoverProps = {
  arrow: false,
  placement: 'bottomRight',
};

export const CannotStartAgentDueToUnexpectedError = () => (
  <Popover
    {...otherPopoverProps}
    title="Unexpected error"
    content={
      <div style={{ maxWidth: 340 }}>
        <Paragraph>
          Try to restart the app. If the issue persists, join the Olas community
          Discord server to report or stay up to date on the issue.
        </Paragraph>

        <a href={SUPPORT_URL} target="_blank" rel="noreferrer">
          Olas community Discord server {UNICODE_SYMBOLS.EXTERNAL_LINK}
        </a>
      </div>
    }
  >
    {cannotStartAgentText}
  </Popover>
);

const evictedDescription =
  "You didn't run your agent enough and it missed its targets multiple times. Please wait a few days and try to run your agent again.";
const AgentEvictedPopover = () => (
  <Popover
    {...otherPopoverProps}
    open
    title="Your agent is suspended from work"
    content={
      <Flex vertical gap={8} className="text-sm-all" style={{ maxWidth: 340 }}>
        <Paragraph className="text-sm m-0">{evictedDescription}</Paragraph>
        <Paragraph className="m-0">
          <Text className="text-sm">Eviction ends at</Text>{' '}
          <Text strong className="text-sm">
            Sep 29, 11:15 pm
          </Text>
        </Paragraph>
      </Flex>
    }
  >
    {cannotStartAgentText}
  </Popover>
);

const JoinOlasCommunity = () => (
  <div style={{ maxWidth: 340 }}>
    <Paragraph>
      Join the Olas community Discord server to report or stay up to date on the
      issue.
    </Paragraph>

    <a href={SUPPORT_URL} target="_blank" rel="noreferrer">
      Olas community Discord server {UNICODE_SYMBOLS.EXTERNAL_LINK}
    </a>
  </div>
);

const NoRewardsAvailablePopover = () => (
  <Popover
    {...otherPopoverProps}
    title="No rewards available"
    content={<JoinOlasCommunity />}
  >
    {cannotStartAgentText}
  </Popover>
);

const NoJobsAvailablePopover = () => (
  <Popover
    {...otherPopoverProps}
    title="No jobs available"
    content={<JoinOlasCommunity />}
  >
    {cannotStartAgentText}
  </Popover>
);

export const CannotStartAgentPopover = () => {
  const {
    isEligibleForStaking,
    hasEnoughServiceSlots,
    isRewardsAvailable,
    isAgentEvicted,
  } = useStakingContractInfo();

  return <AgentEvictedPopover />;

  if (isEligibleForStaking) return null;
  if (!hasEnoughServiceSlots) return <NoJobsAvailablePopover />;
  if (!isRewardsAvailable) return <NoRewardsAvailablePopover />;
  if (isAgentEvicted) return <AgentEvictedPopover />;
  throw new Error('Cannot start agent, please contact support');
};
