import { EditFilled } from '@ant-design/icons';
import { Button, Form, FormInstance } from 'antd';
import { noop } from 'lodash';
import {
  createContext,
  Dispatch,
  PropsWithChildren,
  SetStateAction,
  useCallback,
  useContext,
  useState,
} from 'react';

import { AgentType } from '@/enums/Agent';
import { Pages } from '@/enums/Pages';
import { usePageState } from '@/hooks/usePageState';
import { useServices } from '@/hooks/useServices';
import { ServicesService } from '@/service/Services';

import { CardTitle } from '../Card/CardTitle';
import { CardFlex } from '../styled/CardFlex';
import { useConfirmUpdateModal } from './hooks/useConfirmModal';
import { ModalProps } from './hooks/useModal';
import { useUnsavedModal } from './hooks/useUnsavedModal';
import { MemeUpdateForm } from './MemeUpdateForm';
import { ConfirmUpdateModal } from './modals/ConfirmUpdateModal';
import { UnsavedModal } from './modals/UnsavedModal';

export const UpdateAgentContext = createContext<
  Partial<{
    confirmUpdateModal: ModalProps;
    unsavedModal: ModalProps;
    form: FormInstance;
    isEditing: boolean;
    setIsEditing: Dispatch<SetStateAction<boolean>>;
  }>
>({});

export type MemeFormValues = {
  GENAI_API_KEY: string;
  PERSONA: string;
  TWIKIT_USERNAME: string;
  TWIKIT_EMAIL: string;
  TWIKIT_PASSWORD: string;
};

const UpdateAgentProvider = ({ children }: PropsWithChildren) => {
  const [form] = Form.useForm<MemeFormValues>();
  const { selectedService } = useServices();
  const { goto } = usePageState();
  const [isEditing, setIsEditing] = useState(false);

  const confirmUpdateCallback = useCallback(async () => {
    const formValues = form.getFieldsValue() as MemeFormValues;
    if (selectedService && selectedService.service_config_id) {
      await ServicesService.patchService({
        serviceConfigId: selectedService?.service_config_id,
        partialServiceTemplate: {
          env_variables: {
            ...Object.entries(formValues).reduce(
              (acc, [key, value]) => ({ ...acc, [key]: { value } }),
              {},
            ),
          },
        },
      });
    }
  }, [form, selectedService]);

  const confirmUnsavedCallback = useCallback(async () => {
    goto(Pages.Main);
  }, [goto]);

  const confirmUpdateModal = useConfirmUpdateModal({
    confirmCallback: confirmUpdateCallback,
  });

  const unsavedModal = useUnsavedModal({
    confirmCallback: confirmUnsavedCallback,
  });

  return (
    <UpdateAgentContext.Provider
      value={{
        confirmUpdateModal,
        unsavedModal,
        form,
        isEditing,
        setIsEditing,
      }}
    >
      <ConfirmUpdateModal />
      <UnsavedModal />
      {children}
    </UpdateAgentContext.Provider>
  );
};

const EditButton = () => {
  const { setIsEditing, isEditing } = useContext(UpdateAgentContext);

  const handleEdit = () => {
    setIsEditing?.((prev) => !prev);
  };

  if (isEditing) {
    return null;
  }

  return (
    <Button icon={<EditFilled />} onClick={handleEdit}>
      Edit
    </Button>
  );
};

export const UpdateAgentPage = () => {
  return (
    <UpdateAgentProvider>
      <UpdateAgentPageCard />
    </UpdateAgentProvider>
  );
};

const UpdateAgentPageCard = () => {
  const { selectedAgentType } = useServices();
  const { unsavedModal, isEditing } = useContext(UpdateAgentContext);
  return (
    <CardFlex
      bordered={false}
      title={
        <CardTitle
          showBackButton={true}
          backButtonCallback={unsavedModal?.openModal ?? noop}
          title={isEditing ? 'Edit agent settings' : 'Agent settings'}
        />
      }
      extra={<EditButton />}
    >
      {selectedAgentType === AgentType.Memeooorr && <MemeUpdateForm />}
    </CardFlex>
  );
};
