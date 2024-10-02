import { useQuery } from '@tanstack/react-query';
import { gql, request } from 'graphql-request';
import { useMemo } from 'react';
import { z } from 'zod';

import { SUBGRAPH_URL } from '@/constants/urls';
import { useStakingProgram } from '@/hooks/useStakingProgram';

const EpochTimeSchema = z.object({
  epoch: z.string(),
  epochLength: z.string(),
  blockTimestamp: z.string(),
  contractAddress: z.string(),
});
type EpochTime = z.infer<typeof EpochTimeSchema>;

export const useEpochEndTime = () => {
  const { activeStakingProgramAddress } = useStakingProgram();
  const fetchRewardsQuery = useMemo(() => {
    return gql`
      query {
        checkpoints(
          orderBy: epoch
          orderDirection: desc
          first: 1
          where: {
            contractAddress: "${activeStakingProgramAddress}"
          }
        ) {
          epoch
          epochLength
          blockTimestamp
          contractAddress
        }
      }
    `;
  }, [activeStakingProgramAddress]);

  const { data, isLoading } = useQuery({
    queryKey: ['epochEndTime'],
    queryFn: async () => {
      const response = (await request(SUBGRAPH_URL, fetchRewardsQuery)) as {
        checkpoints: EpochTime[];
      };
      return EpochTimeSchema.parse(response.checkpoints[0]);
    },
    select: (data) => {
      // last epoch end time + epoch length
      return Number(data.blockTimestamp) + Number(data.epochLength);
    },
    enabled: !!activeStakingProgramAddress,
  });

  return { data, isLoading };
};
