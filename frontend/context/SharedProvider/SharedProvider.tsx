import { createContext, PropsWithChildren, useCallback, useRef } from 'react';

import { usePrevious } from '@/hooks/usePrevious';
import { Optional } from '@/types/Util';

import { useMainOlasBalance } from './useMainOlasBalance';

export const SharedContext = createContext<{
  // main olas balance
  isMainOlasBalanceLoading: boolean;
  mainOlasBalance: Optional<number>;
  previousMainOlasBalance: Optional<number>;
  hasMainOlasBalanceAnimatedOnLoad: boolean;
  setMainOlasBalanceAnimated: (value: boolean) => void;

  // others
}>({
  isMainOlasBalanceLoading: true,
  mainOlasBalance: undefined,
  previousMainOlasBalance: undefined,
  hasMainOlasBalanceAnimatedOnLoad: false,
  setMainOlasBalanceAnimated: () => {},
});

export const SharedProvider = ({ children }: PropsWithChildren) => {
  const hasAnimatedRef = useRef(false);

  const mainOlasBalanceDetails = useMainOlasBalance();
  const setMainOlasBalanceAnimated = useCallback((value: boolean) => {
    hasAnimatedRef.current = value;
  }, []);
  const previousMainOlasBalance = usePrevious(
    mainOlasBalanceDetails.mainOlasBalance,
  );

  return (
    <SharedContext.Provider
      value={{
        ...mainOlasBalanceDetails,
        previousMainOlasBalance,
        hasMainOlasBalanceAnimatedOnLoad: hasAnimatedRef.current,
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
