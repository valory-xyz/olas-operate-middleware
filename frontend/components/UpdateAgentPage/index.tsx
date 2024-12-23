import { EditFilled } from '@ant-design/icons';
import {
  Alert,
  Button,
  Flex,
  Form,
  FormInstance,
  Input,
  Typography,
} from 'antd';
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

import { Pages } from '@/enums/Pages';
import { usePageState } from '@/hooks/usePageState';
import { useServices } from '@/hooks/useServices';

import { CardTitle } from '../Card/CardTitle';
import { CardFlex } from '../styled/CardFlex';
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
    description:
      'Login details enables your agent to view X and interact with other agents.',
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

const Field = memo(function Field({
  field,
  initialValues,
}: {
  field: DynamicElement;
  initialValues: any;
}) {
  // HEADER
  if (field.type === ElementType.HEADER) {
    return (
      <Flex dir="column" gap={0}>
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
    return (
      <Flex vertical gap={0}>
        <FormItem label={inputField.label} name={inputField.label}>
          <Input defaultValue={initialValues[inputField.label]} />
        </FormItem>
      </Flex>
    );
  }
  //   ALERTS
  if (field.type.includes('alert')) {
    const alertField = field as DynamicAlert;
    return <Alert type="warning" description={alertField.content}></Alert>;
  }
  // TEXTAREA
  if (field.type === ElementType.TEXTAREA) {
    const textAreaField = field as DynamicTextArea;
    return (
      <FormItem label={textAreaField.label} name={textAreaField.label}>
        <Input.TextArea defaultValue={initialValues[textAreaField.label]} />
      </FormItem>
    );
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

const EditButton = () => {
  const { setIsEditing, isEditing } = useContext(UpdateAgentContext);

  return (
    <Button
      size="large"
      icon={<EditFilled />}
      onClick={() => setIsEditing?.(!isEditing)}
    />
  );
};

export const UpdateAgentPage = () => {
  const { selectedService } = useServices();
  const { form } = useContext(UpdateAgentContext);
  const { goto } = usePageState();

  return (
    <UpdateAgentProvider>
      <CardFlex
        bordered={false}
        title={
          <CardTitle
            showBackButton={true}
            backButtonCallback={() => goto(Pages.Main)}
            title="Agent settings"
          />
        }
        noBodyPadding="true"
        extra={<Button size="large" icon={<EditButton />} />}
      >
        <Form form={form} layout="vertical">
          {sections.map((section, index) => (
            <Flex key={index} gap={2} vertical style={{ padding: '16px' }}>
              {section.map((field) => (
                <Field
                  key={field.id}
                  field={field}
                  initialValues={selectedService}
                />
              ))}
            </Flex>
          ))}
        </Form>
      </CardFlex>
    </UpdateAgentProvider>
  );
};
