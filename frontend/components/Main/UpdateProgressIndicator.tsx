import { Button, Flex, Typography } from 'antd';
import { isNil } from 'lodash';
import { FC } from 'react';
import { CSSProperties } from 'styled-components';

import { useElectronApi } from '@/hooks/useElectronApi';
import { useStore } from '@/hooks/useStore';

import { Alert } from '../common/Alert';
import { CardSection } from '../styled/CardSection';

const { Text, Paragraph } = Typography;
const COVER_PREV_BLOCK_BORDER_STYLE: CSSProperties = { marginBottom: '-1px' };

export const UpdateProgressIndicator: FC = () => {
  const { storeState } = useStore();
  const { store, quitAndInstall } = useElectronApi();

  const restartApp = () => {
    store?.set?.('isUpdateAvailable', false);
    quitAndInstall?.();
  };

  if (
    isNil(storeState?.downloadPercentage) ||
    isNaN(storeState.downloadPercentage)
  ) {
    return null;
  }

  const isAppReady = storeState.downloadPercentage === 100;

  return (
    <CardSection style={COVER_PREV_BLOCK_BORDER_STYLE}>
      <Alert
        type="primary"
        showIcon
        fullWidth
        message={
          <Flex justify="space-between" align="center">
            <Flex vertical gap={4}>
              <Text className="font-weight-600 mb-4">Preparing for update</Text>
              {isAppReady ? null : (
                <Paragraph className="mb-4">
                  Downloading the update... {storeState.downloadPercentage}%
                </Paragraph>
              )}
            </Flex>

            {isAppReady && (
              <Button type="primary" ghost onClick={restartApp}>
                Install Update
              </Button>
            )}
          </Flex>
        }
      />
    </CardSection>
  );
};
