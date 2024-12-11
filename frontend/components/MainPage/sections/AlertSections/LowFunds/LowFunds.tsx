import { LowOperatingBalanceAlert } from './LowOperatingBalanceAlert';
import { LowSafeSignerBalanceAlert } from './LowSafeSignerBalanceAlert';

export const LowFunds = () => (
  <>
    <LowOperatingBalanceAlert />
    <LowSafeSignerBalanceAlert />
  </>
);
