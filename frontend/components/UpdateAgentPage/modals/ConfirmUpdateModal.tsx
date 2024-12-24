import { Modal } from 'antd';
import { useContext } from 'react';

import { UpdateAgentContext } from '..';

export const ConfirmUpdateModal = () => {
  const { confirmUpdateModal: confirmModal } = useContext(UpdateAgentContext);
  return (
    <Modal
      title="Confirm changes"
      open={confirmModal?.open}
      onOk={confirmModal?.confirm}
      onCancel={confirmModal?.cancel}
    >
      <p>These changes will only take effect when you restart the agent.</p>
    </Modal>
  );
};
