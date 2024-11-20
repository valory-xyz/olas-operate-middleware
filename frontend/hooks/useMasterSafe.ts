import { useQuery } from '@tanstack/react-query';
import { Contract } from 'ethers';

import { GNOSIS_SAFE_ABI } from '@/abis/gnosisSafe';
import { PROVIDERS } from '@/constants/providers';
import { REACT_QUERY_KEYS } from '@/constants/react-query-keys';
import { MasterSafe } from '@/enums/Wallet';
import { Address } from '@/types/Address';

export const useMasterSafe = (masterSafe: MasterSafe) => {
  return useQuery<Address[]>({
    queryKey: REACT_QUERY_KEYS.MULTISIG_GET_OWNERS_KEY(masterSafe),
    queryFn: async () => {
      const contract = new Contract(
        masterSafe.address,
        GNOSIS_SAFE_ABI,
        PROVIDERS[masterSafe.chainId].provider,
      );
      return contract.functions.getOwners() as Promise<Address[]>;
    },
  });
};
