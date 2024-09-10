import { Tag } from 'antd';

import { StakingProgramStatus } from '@/enums/StakingProgramStatus';

export const StakingContractTag = ({
  status,
}: {
  status?: StakingProgramStatus;
}) => {
  if (status === StakingProgramStatus.Selected) {
    return <Tag color="purple">Active</Tag>;
  }
  return null;
};
