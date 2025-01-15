import { useContext } from 'react';

import { RewardContext } from '@/context/RewardProvider';

export const useReward = () => useContext(RewardContext);
