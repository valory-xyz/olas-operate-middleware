import { Button, Form, Input } from 'antd';
import { useContext } from 'react';

import { Nullable } from '@/types/Util';

// TODO: move the following hook/components to a shared place
// once Modius work is merged
import { useMemeFormValidate } from '../SetupPage/hooks/useMemeFormValidate';
import {
  InvalidGeminiApiCredentials,
  InvalidXCredentials,
  requiredRules,
  validateMessages,
  XAccountCredentials,
} from '../SetupPage/SetupYourAgent/SetupYourAgent';
import { UpdateAgentContext } from './context/UpdateAgentProvider';

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

// TODO: use exported commonFieldProps once Modius is merged
const commonFieldProps = { rules: requiredRules, hasFeedback: true };

type MemeUpdateFormProps = {
  initialFormValues: Nullable<MemeooorrFormValues>;
};

export const MemeUpdateForm = ({ initialFormValues }: MemeUpdateFormProps) => {
  const {
    isEditing,
    form,
    confirmUpdateModal: confirmModal,
  } = useContext(UpdateAgentContext);

  const {
    isValidating,
    geminiApiKeyValidationStatus,
    twitterCredentialsValidationStatus,
    handleValidate,
  } = useMemeFormValidate();

  const handleFinish = async (values: MemeooorrFormValues) => {
    const cookies = await handleValidate({
      personaDescription: values.env_variables.PERSONA,
      geminiApiKey: values.env_variables.GENAI_API_KEY,
      xEmail: values.env_variables.TWIKIT_EMAIL,
      xUsername: values.env_variables.TWIKIT_USERNAME,
      xPassword: values.env_variables.TWIKIT_PASSWORD,
    });
    if (!cookies) return;

    form?.setFieldValue(['env_variables', 'TWIKIT_COOKIES'], cookies);
    form?.setFieldValue(
      'description',
      `Memeooorr @${values.env_variables.TWIKIT_USERNAME}`,
    );

    confirmModal?.openModal();
  };

  return (
    <Form<MemeooorrFormValues>
      form={form}
      layout="vertical"
      disabled={!isEditing}
      onFinish={handleFinish}
      validateMessages={validateMessages}
      initialValues={{ ...initialFormValues }}
    >
      <Form.Item
        label="Persona description"
        name={['env_variables', 'PERSONA']}
        {...commonFieldProps}
      >
        <Input.TextArea
          placeholder="Describe your agent's persona"
          size="small"
          rows={4}
        />
      </Form.Item>

      {/* Gemini credentials */}
      <Form.Item
        label="Gemini API key"
        name={['env_variables', 'GENAI_API_KEY']}
        {...commonFieldProps}
      >
        <Input.Password placeholder="Google Gemini API key" />
      </Form.Item>
      {geminiApiKeyValidationStatus === 'invalid' && (
        <InvalidGeminiApiCredentials />
      )}

      {/* X */}
      <XAccountCredentials />
      {twitterCredentialsValidationStatus === 'invalid' && (
        <InvalidXCredentials />
      )}

      <Form.Item
        label="X Email"
        name={['env_variables', 'TWIKIT_EMAIL']}
        rules={[{ required: true, type: 'email' }]}
        hasFeedback
      >
        <Input placeholder="X Email" />
      </Form.Item>
      <Form.Item
        label="X Username"
        name={['env_variables', 'TWIKIT_USERNAME']}
        {...commonFieldProps}
      >
        <Input
          placeholder="X Username"
          addonBefore="@"
          onKeyDown={(e) => {
            if (e.key === '@') {
              e.preventDefault();
            }
          }}
        />
      </Form.Item>
      <Form.Item
        label="X Password"
        name={['env_variables', 'TWIKIT_PASSWORD']}
        {...commonFieldProps}
        rules={[
          ...requiredRules,
          {
            validator: (_, value) => {
              if (value && value.includes('$')) {
                return Promise.reject(
                  new Error(
                    'Password must not contain the “$” symbol. Please update your password on Twitter, then retry.',
                  ),
                );
              }
              return Promise.resolve();
            },
          },
        ]}
      >
        <Input.Password placeholder="X Password" />
      </Form.Item>

      {/* Hidden fields that need to be accessible in Confirm Update Modal */}
      <Form.Item name={['env_variables', 'TWIKIT_COOKIES']} hidden />
      <Form.Item name="description" hidden />

      <Form.Item hidden={!isEditing}>
        <Button
          size="large"
          type="primary"
          htmlType="submit"
          block
          loading={isValidating}
        >
          Save changes
        </Button>
      </Form.Item>
    </Form>
  );
};
