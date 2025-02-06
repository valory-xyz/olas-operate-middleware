import { useContext } from 'react';

import { RewardContext } from '@/context/RewardProvider';

export const useRewardContext = () => useContext(RewardContext);
