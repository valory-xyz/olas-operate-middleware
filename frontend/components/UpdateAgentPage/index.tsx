import { EditOutlined } from '@ant-design/icons';
import { Button, ConfigProvider } from 'antd';
import { useCallback, useContext } from 'react';

import { AgentType } from '@/enums/Agent';
import { Pages } from '@/enums/Pages';
import { usePageState } from '@/hooks/usePageState';
import { useServices } from '@/hooks/useServices';
import { LOCAL_FORM_THEME } from '@/theme';

import { CardTitle } from '../Card/CardTitle';
import { CardFlex } from '../styled/CardFlex';
import {
  UpdateAgentContext,
  UpdateAgentProvider,
} from './context/UpdateAgentProvider';
import { MemeUpdateForm } from './MemeUpdateForm';

const EditButton = () => {
  const { setIsEditing } = useContext(UpdateAgentContext);

  const handleEdit = useCallback(() => {
    setIsEditing?.((prev) => !prev);
  }, [setIsEditing]);

  return (
    <Button icon={<EditOutlined />} onClick={handleEdit}>
      Edit
    </Button>
  );
};

const UpdateAgentPageCard = () => {
  const { selectedAgentType } = useServices();
  const { goto } = usePageState();
  const { unsavedModal, isEditing, form } = useContext(UpdateAgentContext);

  const hasUnsavedChanges = form?.isFieldsTouched();

  const handleClickBack = useCallback(() => {
    if (hasUnsavedChanges) {
      unsavedModal?.openModal?.();
    } else {
      goto(Pages.Main);
    }
  }, [hasUnsavedChanges, unsavedModal, goto]);

  return (
    <CardFlex
      bordered={false}
      title={
        <CardTitle
          backButtonCallback={handleClickBack}
          title={isEditing ? 'Edit agent settings' : 'Agent settings'}
        />
      }
      extra={isEditing ? null : <EditButton />}
    >
      {selectedAgentType === AgentType.Memeooorr && <MemeUpdateForm />}
    </CardFlex>
  );
};

export const UpdateAgentPage = () => {
  return (
    <UpdateAgentProvider>
      <ConfigProvider theme={LOCAL_FORM_THEME}>
        <UpdateAgentPageCard />
      </ConfigProvider>
    </UpdateAgentProvider>
  );
};
