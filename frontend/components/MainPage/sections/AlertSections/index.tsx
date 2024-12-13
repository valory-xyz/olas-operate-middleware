import { CardSection } from '@/components/styled/CardSection';
import { useFeatureFlag } from '@/hooks/useFeatureFlag';

import { AddBackupWalletAlert } from './AddBackupWalletAlert';
import { AvoidSuspensionAlert } from './AvoidSuspensionAlert';
import { LowFunds } from './LowFunds/LowFunds';
import { NewStakingProgramAlert } from './NewStakingProgramAlert';
import { NoAvailableSlotsOnTheContract } from './NoAvailableSlotsOnTheContract';
import { UpdateAvailableAlert } from './UpdateAvailableAlert';

export const AlertSections = () => {
  const isLowFundsEnabled = useFeatureFlag('low-funds');

  return (
    <CardSection vertical>
      <UpdateAvailableAlert />
      <AddBackupWalletAlert />
      <NewStakingProgramAlert />
      <AvoidSuspensionAlert />
      {isLowFundsEnabled && <LowFunds />}
      <NoAvailableSlotsOnTheContract />
    </CardSection>
  );
};
