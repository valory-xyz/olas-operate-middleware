import { CloseOutlined } from '@ant-design/icons';
import { Button, Card } from 'antd';

import { STAKING_PROGRAM_META } from '@/constants/stakingProgramMeta';
import { Pages } from '@/enums/PageState';
import { StakingProgramId } from '@/enums/StakingProgram';
import { usePageState } from '@/hooks/usePageState';
import { useStakingProgram } from '@/hooks/useStakingProgram';

import { CardTitle } from '../Card/CardTitle';
import { CardSection } from '../styled/CardSection';
import { StakingContractSection } from './StakingContractSection';
import { WhatAreStakingContractsSection } from './WhatAreStakingContracts';

export const ManageStakingPage = () => {
  const { goto } = usePageState();
  const { activeStakingProgramId, defaultStakingProgramId } =
    useStakingProgram();

  const orderedStakingProgramIds: StakingProgramId[] = Object.values(
    StakingProgramId,
  ).reduce((acc: StakingProgramId[], stakingProgramId: StakingProgramId) => {
    // put the active staking program at the top
    if (stakingProgramId === activeStakingProgramId) {
      return [stakingProgramId, ...acc];
    }

    // otherwise put the default at the top
    if (
      activeStakingProgramId === null &&
      stakingProgramId === defaultStakingProgramId
    )
      return [stakingProgramId];

    // otherwise, append to the end
    return [...acc, stakingProgramId];
  }, []);

  const otherStakingProgramIds = orderedStakingProgramIds.filter(
    (stakingProgramId) => {
      const info = STAKING_PROGRAM_META[stakingProgramId];
      if (!info) return false;
      if (activeStakingProgramId === stakingProgramId) return false;
      if (info.deprecated) return false;
      return true;
    },
  );

  return (
    <Card
      title={<CardTitle title="Manage staking contract" />}
      bordered={false}
      extra={
        <Button
          size="large"
          icon={<CloseOutlined />}
          onClick={() => goto(Pages.Main)}
        />
      }
    >
      <WhatAreStakingContractsSection />
      <StakingContractSection stakingProgramId={orderedStakingProgramIds[0]} />

      <CardSection borderbottom="true" vertical gap={16}>
        {`Browse ${otherStakingProgramIds.length} staking contract${otherStakingProgramIds.length > 1 ? 's' : ''}.`}
      </CardSection>

      {otherStakingProgramIds.map((stakingProgramId) => (
        <StakingContractSection
          key={stakingProgramId}
          stakingProgramId={stakingProgramId}
        />
      ))}
    </Card>
  );
};
