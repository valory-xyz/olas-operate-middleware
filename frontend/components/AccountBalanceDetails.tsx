import { useState } from 'react';

import { MODAL_WIDTH } from '@/constants/width';

import { CustomModal } from './styled/CustomModal';

export const AccountBalanceDetails = () => {
  const [isModalVisible, setIsModalVisible] = useState(true);

  return (
    <CustomModal
      title="Account Balance Details"
      open={isModalVisible}
      width={MODAL_WIDTH}
      bodyPadding
      onCancel={() => setIsModalVisible(false)}
      footer={null}
    >
      <div>Some contents...</div>
    </CustomModal>
  );
};
