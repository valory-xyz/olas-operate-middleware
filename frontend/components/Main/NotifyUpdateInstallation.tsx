import { Button, Flex, Modal, Typography } from 'antd';
import Image from 'next/image';
import { FC, useEffect, useState } from 'react';

import { MODAL_WIDTH } from '@/constants/sizes';

const { Title, Paragraph } = Typography;

export const NotifyUpdateInstallation: FC = () => {
  const [isModalVisible, setIsModalVisible] = useState(false);

  useEffect(() => {
    // TODO: should from electron API store
    setIsModalVisible(true);
  }, []);

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
