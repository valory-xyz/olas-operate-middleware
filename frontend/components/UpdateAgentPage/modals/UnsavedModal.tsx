import { Modal } from 'antd';
import { useContext } from 'react';

import { UpdateAgentContext } from '../context/UpdateAgentProvider';

export const UnsavedModal = () => {
  const { unsavedModal } = useContext(UpdateAgentContext);
  if (!unsavedModal) return null;
  return (
    <Modal
      title="Unsaved changes"
      open={unsavedModal.open}
      onOk={unsavedModal.confirm}
      onCancel={unsavedModal.cancel}
    >
      <p>You have unsaved changes. Are you sure you want to leave this page?</p>
    </Modal>
  );
};
