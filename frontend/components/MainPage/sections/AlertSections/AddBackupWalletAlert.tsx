import { Flex, Typography } from 'antd';
import { isArray, isEmpty, isNil } from 'lodash';

import { Pages } from '@/enums/Pages';
import { useMultisig, useMultisigs } from '@/hooks/useMultisig';
import { usePageState } from '@/hooks/usePageState';
import { useMasterWalletContext } from '@/hooks/useWallet';

import { CustomAlert } from '../../../Alert';
import { useServices } from '@/hooks/useServices';

const { Text } = Typography;

export const AddBackupWalletAlert = () => {
  const { goto } = usePageState();
  const { selectedAgentConfig } = useServices();
  const { masterSafes, masterEoa,  } = useMasterWalletContext();
  const {
    owners,
    ownersIsFetched: masterSafeOwnersIsFetched,
    backupOwners,
  } = useMultisig(masterSafes?.find(masterSafe => {
    return masterSafe.evmChainId === selectedAgentConfig.evmHomeChainId;
  }));

  if (!masterSafeOwnersIsFetched) return null;
  
  if (isNil(backupOwners)) return null;
  if (isArray(backupOwners) && backupOwners.length > 0) return null;

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
