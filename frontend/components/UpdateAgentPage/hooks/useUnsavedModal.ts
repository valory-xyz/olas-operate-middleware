import { useCallback } from 'react';

import { ModalProps, useModal } from './useModal';

export const useUnsavedModal = (): ModalProps => {
  const modal = useModal();

  const confirm = useCallback(() => {
    // Do something
  }, []);

  return {
    ...modal,
    confirm,
  };
};
