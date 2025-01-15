import { createContext, PropsWithChildren } from 'react';

import { Optional } from '@/types/Util';

import { useMainOlasBalance } from './useMainOlasBalance';

export const SharedContext = createContext<{
  isMainOlasBalanceLoading: boolean;
  mainOlasBalance: Optional<number>;
}>({
  isMainOlasBalanceLoading: true,
  mainOlasBalance: undefined,
});

export const SharedProvider = ({ children }: PropsWithChildren) => {
  return (
    <SharedContext.Provider value={{ ...useMainOlasBalance() }}>
      {children}
    </SharedContext.Provider>
  );
};
