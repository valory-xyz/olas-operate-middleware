import { useContext } from 'react';

import { SharedContext } from '@/context/SharedProvider/SharedProvider';

export const useSharedContext = () => useContext(SharedContext);
