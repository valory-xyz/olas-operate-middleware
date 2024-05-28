import { Button, Flex, Modal } from 'antd';
import { FC, useEffect, useState } from 'react';

import { MODAL_WIDTH } from '@/constants/sizes';

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
          <Button key="install" type="primary" onClick={handleInstall} block>
            Install
          </Button>
          <Button key="cancel" onClick={handleCancel} block>
            Cancel
          </Button>
        </Flex>,
      ]}
    >
      {/* Modal content goes here */}
      <p>Are you sure you want to install the updates?</p>
    </Modal>
  );
};
