import { formatUnits } from 'ethers/lib/utils';

import { CHAIN_CONFIG } from '@/config/chains';
import { SERVICE_TEMPLATES } from '@/constants/serviceTemplates';

export const requiredGas = Number(
  formatUnits(
    `${SERVICE_TEMPLATES[0].configurations[CHAIN_CONFIG.OPTIMISM.chainId].monthly_gas_estimate}`,
    18,
  ),
);
