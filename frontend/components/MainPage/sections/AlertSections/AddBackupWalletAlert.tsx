import { Flex, Typography } from 'antd';
import { isNil } from 'lodash';

import { Pages } from '@/enums/Pages';
import { MasterSafe } from '@/enums/Wallet';
import { useMultisig } from '@/hooks/useMultisig';
import { usePageState } from '@/hooks/usePageState';

import { CustomAlert } from '../../../Alert';

const { Text } = Typography;

export const AddBackupWalletAlert = (masterSafe: MasterSafe) => {
  const { goto } = usePageState();
  const { data: masterSafeOwners } = useMultisig(masterSafe);

  if (isNil(masterSafeOwners)) return null;
  if (masterSafeOwners) return null;

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
