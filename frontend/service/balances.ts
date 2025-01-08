import { BalancesAndFundingRequirements } from '@/client';
import { CONTENT_TYPE_JSON_UTF8 } from '@/constants/headers';
import { BACKEND_URL_V2 } from '@/constants/urls';

import balances from './balances.json';

/**
 * Get a single service from the backend
 * @param serviceHash
 * @returns
 */
const getBalancesAndFundingRequirements = async (
  serviceConfigId: string,
): Promise<BalancesAndFundingRequirements> => {
  return Promise.resolve(balances);

  // TODO: Remove this once the backend is ready
  return fetch(
    `${BACKEND_URL_V2}/services/${serviceConfigId}/balances_and_fund_requirements`,
    {
      method: 'GET',
      headers: { ...CONTENT_TYPE_JSON_UTF8 },
    },
  ).then((response) => {
    if (response.ok) {
      return response.json();
    }
    throw new Error(
      `Failed to balances and fund requirements for ${serviceConfigId}`,
    );
  });
};

export const BalanceService = {
  getBalancesAndFundingRequirements,
};
