import { EditOutlined } from '@ant-design/icons';
import { Button, ConfigProvider } from 'antd';
import { get, isEqual, omit } from 'lodash';
import { useCallback, useContext, useMemo } from 'react';

import { AgentType } from '@/enums/Agent';
import { Pages } from '@/enums/Pages';
import { usePageState } from '@/hooks/usePageState';
import { useServices } from '@/hooks/useServices';
import { LOCAL_FORM_THEME } from '@/theme';
import { Nullable } from '@/types/Util';

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

type MemeooorrFormValues = {
  description: string;
  env_variables: {
    GENAI_API_KEY: string;
    PERSONA: string;
    TWIKIT_USERNAME: string;
    TWIKIT_EMAIL: string;
    TWIKIT_PASSWORD: string;
    TWIKIT_COOKIES: string;
  };
};

const UpdateAgentForm = () => {
  const { goto } = usePageState();
  const { selectedAgentType, selectedService } = useServices();
  const { unsavedModal, isEditing, form } = useContext(UpdateAgentContext);

  const initialValues = useMemo<Nullable<MemeooorrFormValues>>(() => {
    if (!selectedService?.env_variables) return null;

    const envEntries = Object.entries(selectedService.env_variables);

    return envEntries.reduce(
      (acc, [key, { value }]) => {
        if (key === 'PERSONA') {
          acc.env_variables.PERSONA = value;
        } else if (key === 'GENAI_API_KEY') {
          acc.env_variables.GENAI_API_KEY = value;
        } else if (key === 'TWIKIT_EMAIL') {
          acc.env_variables.TWIKIT_EMAIL = value;
        } else if (key === 'TWIKIT_USERNAME') {
          acc.env_variables.TWIKIT_USERNAME = value;
        } else if (key === 'TWIKIT_PASSWORD') {
          acc.env_variables.TWIKIT_PASSWORD = value;
        }

        return acc;
      },
      { env_variables: {} } as MemeooorrFormValues,
    );
  }, [selectedService?.env_variables]);

  const handleClickBack = useCallback(() => {
    const unsavedFields = omit(
      get(form?.getFieldsValue(), 'env_variables'),
      'TWIKIT_COOKIES',
    );
    const previousValues = initialValues?.env_variables;

    const hasUnsavedChanges = !isEqual(unsavedFields, previousValues);
    if (hasUnsavedChanges) {
      unsavedModal?.openModal?.();
    } else {
      goto(Pages.Main);
    }
  }, [unsavedModal, goto, form, initialValues]);

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
      {selectedAgentType === AgentType.Memeooorr && (
        <MemeUpdateForm initialFormValues={initialValues} />
      )}
    </CardFlex>
  );
};

export const UpdateAgentPage = () => {
  return (
    <UpdateAgentProvider>
      <ConfigProvider theme={LOCAL_FORM_THEME}>
        <UpdateAgentForm />
      </ConfigProvider>
    </UpdateAgentProvider>
  );
};
