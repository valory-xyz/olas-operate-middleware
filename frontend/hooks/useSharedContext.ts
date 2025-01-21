import { useContext } from 'react';

import { SharedContext } from '@/context/SharedProvider/SharedProvider';

export const useSharedContext = () => {
  const context = useContext(SharedContext);
  if (!context) {
    throw new Error('useSharedContext must be used within SharedContext');
  }
  return context;
};
