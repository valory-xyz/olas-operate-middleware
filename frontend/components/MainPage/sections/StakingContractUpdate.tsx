import { RightOutlined } from '@ant-design/icons';
import { Button, Flex, Skeleton, Typography } from 'antd';
import { useMemo } from 'react';

import { STAKING_PROGRAM_META } from '@/constants/stakingProgramMeta';
import { Pages } from '@/enums/PageState';
import { usePageState } from '@/hooks/usePageState';
import { useStakingProgram } from '@/hooks/useStakingProgram';

import { CardSection } from '../../styled/CardSection';

const { Text } = Typography;

export const StakingContractUpdate = () => {
  const { goto } = usePageState();
  const {
    activeStakingProgramMeta,
    isActiveStakingProgramLoaded,
    defaultStakingProgramId,
  } = useStakingProgram();

  const stakingContractName = useMemo(() => {
    if (activeStakingProgramMeta) return activeStakingProgramMeta.name;
    return STAKING_PROGRAM_META[defaultStakingProgramId].name;
  }, [activeStakingProgramMeta, defaultStakingProgramId]);

  const stakingButton = useMemo(() => {
    if (!isActiveStakingProgramLoaded) return <Skeleton.Input />;
    return (
      <Button
        type="link"
        className="p-0"
        onClick={() => goto(Pages.ManageStaking)}
      >
        {stakingContractName}
        <RightOutlined />
      </Button>
    );
  }, [goto, isActiveStakingProgramLoaded, stakingContractName]);

  return (
    <CardSection bordertop="true" padding="16px 24px">
      <Flex
        gap={16}
        justify="space-between"
        align="center"
        style={{ width: '100%' }}
      >
        <Text type="secondary">Staking contract</Text>

        {stakingButton}
      </Flex>
    </CardSection>
  );
};
