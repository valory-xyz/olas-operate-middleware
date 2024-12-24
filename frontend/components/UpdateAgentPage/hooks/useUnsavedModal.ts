import { useCallback } from 'react';

import { ModalProps, useModal } from './useModal';

export const useUnsavedModal = ({
  confirmCallback,
}: {
  confirmCallback: () => void;
}): ModalProps => {
  const modal = useModal();

  const confirm = useCallback(async () => {
    confirmCallback();
    modal.closeModal();
  }, [confirmCallback, modal]);

  return {
    ...modal,
    confirm,
  };
};
