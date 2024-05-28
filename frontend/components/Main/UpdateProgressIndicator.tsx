import { Button, Flex, Typography } from 'antd';
import { FC, useEffect, useState } from 'react';
import { CSSProperties } from 'styled-components';

import { useElectronApi } from '@/hooks/useElectronApi';

import { Alert } from '../common/Alert';
import { CardSection } from '../styled/CardSection';

const { Text, Paragraph } = Typography;
const COVER_PREV_BLOCK_BORDER_STYLE: CSSProperties = { marginBottom: '-1px' };

export const UpdateProgressIndicator: FC = () => {
  const [progressPercent, setProgressPercent] = useState(0);
  const [isDownloaded, setUpdateDownloaded] = useState(false);

  const { quitAndInstall, ipcRenderer } = useElectronApi();

  useEffect(() => {
    ipcRenderer?.on?.(
      'download-progress',
      (_event: unknown, progress: unknown) => {
        const progressInfo = progress as { percent?: number | undefined };
        setProgressPercent(progressInfo.percent || 0);
      },
    );

    ipcRenderer?.on?.('update-downloaded', () => {
      setUpdateDownloaded(true);
    });

    return () => {
      ipcRenderer?.removeAllListeners?.('download-progress');
      ipcRenderer?.removeAllListeners?.('update-downloaded');
    };
  }, [ipcRenderer, setProgressPercent, setUpdateDownloaded]);

  const restartApp = () => {
    quitAndInstall?.();
  };

  if (!progressPercent) {
    return null;
  }

  const isAppReady = progressPercent === 100;

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
                  Downloading the update... {progressPercent}%
                </Paragraph>
              )}
            </Flex>

            {isAppReady && (
              <Button
                type="primary"
                ghost
                onClick={restartApp}
                loading={!isDownloaded}
              >
                Install Update
              </Button>
            )}
          </Flex>
        }
      />
    </CardSection>
  );
};
