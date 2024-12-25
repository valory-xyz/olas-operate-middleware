import { Modal } from 'antd';
import { useContext } from 'react';

import { useService } from '@/hooks/useService';

import { UpdateAgentContext } from '../context/UpdateAgentProvider';

export const ConfirmUpdateModal = () => {
  const { isServiceRunning } = useService();
  const { confirmUpdateModal } = useContext(UpdateAgentContext);
  if (!confirmUpdateModal) return null;

  const okText = isServiceRunning ? 'Save and restart agent' : 'Save';

  return (
    <Modal
      title="Confirm changes"
      open={confirmUpdateModal.open}
      onOk={confirmUpdateModal.confirm}
      onCancel={confirmUpdateModal.cancel}
      okText={okText}
    >
      <p>These changes will only take effect when you restart the agent.</p>
    </Modal>
  );
};
