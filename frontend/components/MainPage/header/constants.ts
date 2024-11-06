import { formatUnits } from 'ethers/lib/utils';

import { CHAIN_CONFIGS } from '@/constants/chains';
import { SERVICE_TEMPLATES } from '@/constants/serviceTemplates';

export const requiredGas = Number(
  formatUnits(
    `${SERVICE_TEMPLATES[0].configurations[CHAIN_CONFIGS.OPTIMISM.chainId].monthly_gas_estimate}`,
    18,
  ),
);
