import { createContext, PropsWithChildren, useCallback, useRef } from 'react';

import { Optional } from '@/types/Util';

import { useMainOlasBalance } from './useMainOlasBalance';

export const SharedContext = createContext<{
  // main olas balance
  isMainOlasBalanceLoading: boolean;
  mainOlasBalance: Optional<number>;
  hasMainOlasBalanceAnimated: boolean;
  setMainOlasBalanceAnimated: (value: boolean) => void;

  // others
}>({
  isMainOlasBalanceLoading: true,
  mainOlasBalance: undefined,
  hasMainOlasBalanceAnimated: false,
  setMainOlasBalanceAnimated: () => {},
});

export const SharedProvider = ({ children }: PropsWithChildren) => {
  const hasAnimatedRef = useRef(false);

  const setMainOlasBalanceAnimated = useCallback((value: boolean) => {
    hasAnimatedRef.current = value;
  }, []);

  return (
    <SharedContext.Provider
      value={{
        ...useMainOlasBalance(),
        hasMainOlasBalanceAnimated: hasAnimatedRef.current,
        setMainOlasBalanceAnimated,
      }}
    >
      {children}
    </SharedContext.Provider>
  );
};

// TODO:
// - (DONE) trigger only when the main olas balance is loaded for the first time
// - (DONE) trigger only when the main olas balance changes
// - each olas balance should be agent-specific
