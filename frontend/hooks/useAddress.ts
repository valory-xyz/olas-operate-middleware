import { CHAINS } from '@/constants/chains';

import { useServices } from './useServices';

export const useAddress = () => {
  const { service } = useServices();

  const multisigAddress =
    service?.chain_configs?.[CHAINS.GNOSIS.chainId]?.chain_data?.multisig;

  const instanceAddress =
    service?.chain_configs?.[CHAINS.GNOSIS.chainId]?.chain_data?.instances?.[0];

  return { instanceAddress, multisigAddress };
};
