import { EditFilled } from '@ant-design/icons';
import { Button, Flex, Form, FormInstance, Typography } from 'antd';
import FormItem from 'antd/es/form/FormItem';
import {
  createContext,
  Dispatch,
  memo,
  PropsWithChildren,
  SetStateAction,
  useContext,
  useState,
} from 'react';

import { useServices } from '@/hooks/useServices';

import { CardTitle } from '../Card/CardTitle';
import { CardFlex } from '../styled/CardFlex';
import { CardSection } from '../styled/CardSection';
import { useConfirmModal } from './hooks/useConfirmModal';
import { ModalProps } from './hooks/useModal';
import { useUnsavedModal } from './hooks/useUnsavedModal';
import {
  DynamicAlert,
  DynamicElement,
  DynamicInput,
  DynamicTextArea,
  ElementType,
} from './types';

const agentFields: DynamicElement[] = [
  {
    label: 'Persona description',
    type: ElementType.TEXTAREA,
  },
  {
    label: 'Gemini API key',
    type: 'input_password',
  },
];

const xFields: DynamicElement[] = [
  {
    id: 'x-account-credentials',
    header: 'X account credentials',
    type: ElementType.HEADER,
  },
  {
    id: 'x-account-warning',
    type: ElementType.ALERT_WARNING,
    content:
      'To avoid your X account getting suspended for bot activity, complete the onboarding steps. You can find them on your profile page under "Let\'s get you set up".',
  },
  {
    id: 'x-email',
    label: 'X Email',
    type: ElementType.INPUT_TEXT,
  },
  {
    id: 'x-username',
    label: 'X Username',
    type: ElementType.INPUT_TEXT,
  },
  {
    id: 'x-password',
    label: 'X Password',
    type: ElementType.INPUT_PASSWORD,
  },
];

const sections = [agentFields, xFields];

const Field = memo(function Field({ field }: { field: DynamicElement }) {
  // HEADER
  if (field.type === ElementType.HEADER) {
    return (
      <Flex dir="column" gap={2}>
        <Typography.Title level={5}>{field.header}</Typography.Title>
        {field.description && (
          <Typography.Paragraph>{field.description}</Typography.Paragraph>
        )}
      </Flex>
    );
  }
  //   INPUTS
  if (field.type.startsWith('input')) {
    const inputField = field as DynamicInput;
    return <FormItem label={inputField.label}></FormItem>;
  }
  //   ALERTS
  if (field.type.includes('alert')) {
    const alertField = field as DynamicAlert;
    return <div>{alertField.content}</div>;
  }
  // TEXTAREA
  if (field.type === ElementType.TEXTAREA) {
    const textAreaField = field as DynamicTextArea;
    return <FormItem label={textAreaField.value}></FormItem>;
  }
  return <div>Error</div>;
});

export const UpdateAgentContext = createContext<
  Partial<{
    confirmModal: ModalProps;
    unsavedModal: ModalProps;
    form: FormInstance;
    isEditing: boolean;
    setIsEditing: Dispatch<SetStateAction<boolean>>;
  }>
>({});

const UpdateAgentProvider = ({ children }: PropsWithChildren) => {
  const [form] = Form.useForm();
  const [isEditing, setIsEditing] = useState(false);

  const confirmModal = useConfirmModal();
  const unsavedModal = useUnsavedModal();

  return (
    <UpdateAgentContext.Provider
      value={{
        confirmModal,
        unsavedModal,
        form,
        isEditing,
        setIsEditing,
      }}
    >
      {children}
    </UpdateAgentContext.Provider>
  );
};

export const UpdateAgentPage = () => {
  const { selectedService } = useServices();
  const { form } = useContext(UpdateAgentContext);

  return (
    <UpdateAgentProvider>
      <CardFlex
        bordered={false}
        title={<CardTitle title="Staking rewards history" />}
        noBodyPadding="true"
        extra={<Button size="large" icon={<EditFilled />} />}
      >
        <Form form={form} initialValues={selectedService}>
          {sections.map((section, index) => (
            <CardSection
              key={index}
              gap={8}
              padding="12px 24px"
              justify="space-between"
              align="center"
              borderbottom="true"
            >
              {section.map((field) => (
                <Field key={field.id} field={field} />
              ))}
            </CardSection>
          ))}
        </Form>
      </CardFlex>
    </UpdateAgentProvider>
  );
};
