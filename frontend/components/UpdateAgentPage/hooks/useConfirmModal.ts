import { useCallback, useContext } from 'react';

import { UpdateAgentContext } from '..';
import { useModal } from './useModal';

export const useConfirmModal = () => {
  const { form } = useContext(UpdateAgentContext);
  const modal = useModal();
  const confirm = useCallback(async () => form?.submit(), [form]);

  return {
    ...modal,
    confirm,
  };
};
