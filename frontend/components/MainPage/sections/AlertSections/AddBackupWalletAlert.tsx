import { Flex, Typography } from 'antd';
import { isArray } from 'lodash';

import { Pages } from '@/enums/Pages';
import { useMultisigs } from '@/hooks/useMultisig';
import { usePageState } from '@/hooks/usePageState';
import { useMasterWalletContext } from '@/hooks/useWallet';

import { CustomAlert } from '../../../Alert';

const { Text } = Typography;

export const AddBackupWalletAlert = () => {
  const { goto } = usePageState();
  const { masterSafes } = useMasterWalletContext();
  const {
    masterSafesOwners: owners,
    masterSafesOwnersIsPending: ownersIsPending,
    masterSafesOwnersIsFetched: ownersIsFetched,
  } = useMultisigs(masterSafes);

  if (ownersIsPending) return null;
  if (!ownersIsFetched) return null;

  // all safes have min 1 owner, more than 1 owner, there is a backup
  if (isArray(owners) && owners.length > 1) return null;

  return (
    <CustomAlert
      type="warning"
      fullWidth
      showIcon
      message={
        <Flex align="center" justify="space-between" gap={2}>
          <span>Add backup wallet</span>
          <Text
            className="pointer hover-underline text-primary"
            onClick={() => goto(Pages.AddBackupWalletViaSafe)}
          >
            See instructions
          </Text>
        </Flex>
      }
    />
  );
};
