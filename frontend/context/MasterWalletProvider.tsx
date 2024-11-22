import { QueryObserverBaseResult, useQuery } from '@tanstack/react-query';
import { createContext, PropsWithChildren, useContext, useState } from 'react';

import { MiddlewareWalletResponse } from '@/client';
import { FIVE_SECONDS_INTERVAL } from '@/constants/intervals';
import { REACT_QUERY_KEYS } from '@/constants/react-query-keys';
import {
  MasterEoa,
  MasterSafe,
  MasterWallets,
  WalletOwnerType,
  WalletType,
} from '@/enums/Wallet';
import { UsePause } from '@/hooks/usePause';
import { WalletService } from '@/service/Wallet';
import { convertMiddlewareChainToChainId } from '@/utils/middlewareHelpers';

import { OnlineStatusContext } from './OnlineStatusProvider';

type MasterWalletContext = {
  masterEoa?: MasterEoa;
  masterSafes?: MasterSafe[];
  masterWallets?: (MasterEoa | MasterSafe)[];
} & Partial<QueryObserverBaseResult<(MasterEoa | MasterSafe)[]>> &
  UsePause;

export const MasterWalletContext = createContext<MasterWalletContext>({
  masterEoa: undefined,
  masterSafes: undefined,
  masterWallets: undefined,
  paused: false,
  setPaused: () => {},
  togglePaused: () => {},
});

const transformMiddlewareWalletResponse = (
  data: MiddlewareWalletResponse,
): MasterWallets => {
  const masterEoa: MasterEoa = {
    address: data.address,
    owner: WalletOwnerType.Master,
    type: WalletType.EOA,
  };

  const masterSafes: MasterSafe[] = Object.entries(data.safes).map(
    ([middlewareChain, address]) => ({
      address,
      chainId: convertMiddlewareChainToChainId(middlewareChain),
      owner: WalletOwnerType.Master,
      type: WalletType.Safe,
    }),
  );

  return [masterEoa, ...masterSafes];
};

export const MasterWalletProvider = ({ children }: PropsWithChildren) => {
  const { isOnline } = useContext(OnlineStatusContext);

  const [paused, setPaused] = useState(false);

  const { data: masterWallets, refetch } = useQuery({
    queryKey: REACT_QUERY_KEYS.WALLETS_KEY,
    queryFn: WalletService.getWallets,
    refetchInterval: isOnline && !paused ? FIVE_SECONDS_INTERVAL : false,
    select: (data) => transformMiddlewareWalletResponse(data),
  });

  const masterEoa = masterWallets?.find(
    (wallet): wallet is MasterEoa =>
      wallet.type === WalletType.EOA && wallet.owner === WalletOwnerType.Master,
  );

  const masterSafes = masterWallets?.filter(
    (wallet): wallet is MasterSafe =>
      wallet.type === WalletType.Safe &&
      wallet.owner === WalletOwnerType.Master,
  );

  return (
    <MasterWalletContext.Provider
      value={{
        masterWallets,
        masterEoa,
        masterSafes,
        setPaused,
        paused,
        togglePaused: () => setPaused((prev) => !prev),
        refetch,
      }}
    >
      {children}
    </MasterWalletContext.Provider>
  );
};
