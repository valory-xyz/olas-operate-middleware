import { EditOutlined } from '@ant-design/icons';
import { Button, ConfigProvider } from 'antd';
import { useContext } from 'react';

import { AgentType } from '@/enums/Agent';
import { Pages } from '@/enums/Pages';
import { usePageState } from '@/hooks/usePageState';
import { useServices } from '@/hooks/useServices';

import { CardTitle } from '../Card/CardTitle';
import { CardFlex } from '../styled/CardFlex';
import {
  UpdateAgentContext,
  UpdateAgentProvider,
} from './context/UpdateAgentProvider';
import { MemeUpdateForm } from './MemeUpdateForm';

// TODO: consolidate theme into mainTheme
const LOCAL_THEME = { components: { Input: { fontSize: 16 } } };

const EditButton = () => {
  const { setIsEditing, isEditing } = useContext(UpdateAgentContext);

  const handleEdit = () => {
    setIsEditing?.((prev) => !prev);
  };

  if (isEditing) {
    return null;
  }

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

  const handleClickBack = () => {
    if (hasUnsavedChanges) {
      unsavedModal?.openModal?.();
    } else {
      goto(Pages.Main);
    }
  };

  return (
    <ConfigProvider theme={LOCAL_THEME}>
      <CardFlex
        bordered={false}
        title={
          <CardTitle
            showBackButton={true}
            backButtonCallback={handleClickBack}
            title={isEditing ? 'Edit agent settings' : 'Agent settings'}
          />
        }
        extra={<EditButton />}
      >
        {selectedAgentType === AgentType.Memeooorr && <MemeUpdateForm />}
      </CardFlex>
    </ConfigProvider>
  );
};

export const UpdateAgentPage = () => {
  return (
    <UpdateAgentProvider>
      <UpdateAgentPageCard />
    </UpdateAgentProvider>
  );
};
