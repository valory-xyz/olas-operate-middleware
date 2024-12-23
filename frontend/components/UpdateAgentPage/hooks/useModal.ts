import { useCallback, useState } from 'react';

export interface ModalProps {
  open: boolean;
  openModal: () => void;
  closeModal: () => void;
  cancel: () => void;
  confirm: () => void;
}

export const useModal = (): ModalProps => {
  const [open, setOpen] = useState(false);
  const openModal = () => setOpen(true);
  const closeModal = () => setOpen(false);

  const cancel = useCallback(async () => {
    closeModal();
  }, []);

  const confirm = useCallback(async () => {
    closeModal();
  }, []);

  return {
    open,
    openModal,
    closeModal,
    cancel,
    confirm,
  };
};
