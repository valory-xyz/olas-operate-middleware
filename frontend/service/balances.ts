import { BalancesAndFundingRequirements } from '@/client';
import { CONTENT_TYPE_JSON_UTF8 } from '@/constants/headers';
import { BACKEND_URL_V2 } from '@/constants/urls';

/**
 * Get a single service from the backend
 */
const getBalancesAndFundingRequirements = async (
  serviceConfigId: string,
): Promise<BalancesAndFundingRequirements> => {
  return fetch(
    `${BACKEND_URL_V2}/service/${serviceConfigId}/user_fund_requirements`,
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
