import { Button, Flex, Modal, Typography } from 'antd';
import Image from 'next/image';
import { FC, useEffect, useState } from 'react';
import { CSSProperties } from 'styled-components';

import { MODAL_WIDTH } from '@/constants/sizes';
import { useStore } from '@/hooks/useStore';

import { Alert } from '../common/Alert';
import { CardSection } from '../styled/CardSection';

const { Title, Text, Paragraph } = Typography;
const COVER_PREV_BLOCK_BORDER_STYLE: CSSProperties = { marginBottom: '-1px' };

const UpdateDownloadAlert: FC = () => {
  const [downloadPercentage, setDownloadPercentage] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setDownloadPercentage((prev) => {
        const newPercentage = prev + 1;
        if (newPercentage > 100) {
          clearInterval(interval);
          return 0;
        }
        return newPercentage;
      });
    }, 1000);

    return () => clearInterval(interval);
  }, []);

  // TODO: Implement restartApp in store
  const restartApp = () => {
    // console.log('Restart app');
  };

  if (!downloadPercentage) return null;

  const isAppReady = downloadPercentage === 100;

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
                  Downloading the update... {downloadPercentage}%
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

export const NotifyUpdateModal: FC = () => {
  const { storeState } = useStore();

  const [isModalVisible, setIsModalVisible] = useState(false);
  // console.log('storeState', storeState);

  useEffect(() => {
    // setIsModalVisible(true); // TODO: remove

    if (!storeState) return;
    if (!storeState?.isUpdateAvailable) return;

    setIsModalVisible(true);
  }, [storeState]);

  const handleInstall = () => {
    // console.log('Install button clicked');
  };

  const handleCancel = () => {
    setIsModalVisible(false);
  };

  return (
    <Modal
      open={isModalVisible} // Set to true to show the modal
      title={null}
      onCancel={handleCancel}
      width={MODAL_WIDTH}
      closable={false}
      footer={[
        <Flex key="footer" vertical gap={12}>
          <Button
            key="install"
            type="primary"
            size="large"
            block
            onClick={handleInstall}
          >
            Download and install now
          </Button>
          <Button key="cancel" size="large" block onClick={handleCancel}>
            Install on next launch
          </Button>
        </Flex>,
      ]}
    >
      <Flex align="center" justify="center" gap={12} vertical>
        <Image
          src="/splash-robot-head-dock.png"
          width={100}
          height={100}
          alt="OLAS logo"
        />

        <Title level={5} className="m-0">
          Update Available
        </Title>

        <Paragraph className="mb-8">
          A new version of Pearl is ready to be downloaded and installed.
        </Paragraph>
      </Flex>
    </Modal>
  );
};

export const NotifyUpdateInstallation = () => (
  <>
    <UpdateDownloadAlert />
    <NotifyUpdateModal />
  </>
);
