import { CloseOutlined } from '@ant-design/icons';
import { Button, Card } from 'antd';

import { Pages } from '@/enums/PageState';
import { StakingProgram } from '@/enums/StakingProgram';
import { usePageState } from '@/hooks/usePageState';

import { CardTitle } from '../Card/CardTitle';
import { StakingContractSection } from './StakingContractSection';
import { WhatAreStakingContractsSection } from './WhatAreStakingContracts';

export const ManageStakingPage = () => {
  const { goto } = usePageState();
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
      {/* Pearl Beta */}
      <StakingContractSection stakingProgram={StakingProgram.Beta} />
      {/* Pearl alpha */}
      <StakingContractSection stakingProgram={StakingProgram.Alpha} />
    </Card>
  );
};
