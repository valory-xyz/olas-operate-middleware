import { Skeleton, Typography } from 'antd';
import { useCallback, useEffect, useState } from 'react';
import styled from 'styled-components';
import { useInterval } from 'usehooks-ts';

import { useAddress } from '@/hooks/useAddress';
import { getLatestTransaction } from '@/service/Ethers';
import { TransactionInfo } from '@/types/TransactionInfo';
import { getTimeAgo } from '@/utils/time';

const { Text } = Typography;

const Loader = styled(Skeleton.Input)`
  line-height: 1;
  span {
    width: 120px !important;
    height: 12px !important;
    margin-top: 6px !important;
  }
`;

const POLLING_INTERVAL = 60 * 1000; // 1 minute

/**
 * TODO:
 * - add cache if the same block number is requested
 *
 * Components to display the last transaction time and link to the transaction on GnosisScan
 * by agent safe.
 */
export const LastTransaction = () => {
  const { multisigAddress } = useAddress();

  const [isFetching, setIsFetching] = useState(true);
  const [transaction, setTransaction] = useState<TransactionInfo | null>(null);

  const fetchTransaction = useCallback(async () => {
    if (!multisigAddress) return;

    getLatestTransaction(`${process.env.GNOSIS_RPC}`, multisigAddress)
      .then((tx) => setTransaction(tx))
      .catch((error) =>
        console.error('Failed to get latest transaction', error),
      )
      .finally(() => setIsFetching(false));
  }, [multisigAddress]);

  // Fetch the latest transaction on mount
  useEffect(() => {
    fetchTransaction();
  }, [fetchTransaction]);

  // Poll for the latest transaction
  useInterval(() => fetchTransaction(), POLLING_INTERVAL);

  if (isFetching) {
    return <Loader active size="small" />;
  }

  if (!transaction) {
    return (
      <Text type="secondary" className="text-xs">
        No transactions yet
      </Text>
    );
  }

  return (
    <Text
      type="secondary"
      className="text-xs pointer"
      onClick={() =>
        window.open(`https://gnosisscan.io/tx/${transaction.hash}`)
      }
    >
      Last txn: {getTimeAgo(transaction.timestamp)} ↗
    </Text>
  );
};
