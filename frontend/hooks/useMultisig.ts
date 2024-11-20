import { useQuery } from '@tanstack/react-query';
import { Contract } from 'ethers';

import { GNOSIS_SAFE_ABI } from '@/abis/gnosisSafe';
import { PROVIDERS } from '@/constants/providers';
import { REACT_QUERY_KEYS } from '@/constants/react-query-keys';
import { Safe } from '@/enums/Wallet';
import { Address } from '@/types/Address';

/**
 * Hook to fetch multisig owners
 * @param safe
 * @returns multisig owners
 * @note extend with further multisig functions as needed
 */
export const useMultisig = (safe: Safe) => {
  return useQuery<Address[]>({
    queryKey: REACT_QUERY_KEYS.MULTISIG_GET_OWNERS_KEY(safe),
    queryFn: async () => {
      const contract = new Contract(
        safe.address,
        GNOSIS_SAFE_ABI,
        PROVIDERS[safe.chainId].provider,
      );
      return contract.functions.getOwners() as Promise<Address[]>;
    },
  });
};
