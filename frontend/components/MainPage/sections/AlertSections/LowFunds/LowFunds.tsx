import { EmptyFunds } from './EmptyFunds';
import { LowOperatingBalanceAlert } from './LowOperatingBalanceAlert';
import { LowSafeSignerBalanceAlert } from './LowSafeSignerBalanceAlert';
import { MainNeedsFunds } from './MainNeedsFunds';

export const LowFunds = () => (
  <>
    <EmptyFunds />
    <MainNeedsFunds />
    <LowOperatingBalanceAlert />
    <LowSafeSignerBalanceAlert />
  </>
);
