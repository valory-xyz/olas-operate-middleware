import { Flex, Typography } from 'antd';
import { isArray } from 'lodash';

import { Pages } from '@/enums/Pages';
import { MasterSafe } from '@/enums/Wallet';
import { useMultisig } from '@/hooks/useMultisig';
import { usePageState } from '@/hooks/usePageState';

import { CustomAlert } from '../../../Alert';

const { Text } = Typography;

export const AddBackupWalletAlert = (masterSafe: MasterSafe) => {
  const { goto } = usePageState();
  const { owners, ownersIsPending, ownersIsFetched } = useMultisig(masterSafe);

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
