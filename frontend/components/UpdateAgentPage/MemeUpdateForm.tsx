import { Button, Form, Input } from 'antd';
import { useContext, useMemo } from 'react';

import { useServices } from '@/hooks/useServices';

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

type MemeFormValues = {
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

export const MemeUpdateForm = () => {
  const {
    isEditing,
    form,
    confirmUpdateModal: confirmModal,
  } = useContext(UpdateAgentContext);

  const {
    geminiApiKeyValidationStatus,
    twitterCredentialsValidationStatus,
    handleValidate,
  } = useMemeFormValidate();

  const { selectedService } = useServices();

  const { env_variables } = selectedService || {};

  const initialValues = useMemo<MemeFormValues | null>(() => {
    if (!env_variables) {
      return null;
    }

    const envEntries = Object.entries(env_variables);

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
      { env_variables: {} } as MemeFormValues,
    );
  }, [env_variables]);

  const handleFinish = async (values: MemeFormValues) => {
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
    <Form<MemeFormValues>
      form={form}
      layout="vertical"
      disabled={!isEditing}
      onFinish={handleFinish}
      validateMessages={validateMessages}
      initialValues={{ ...initialValues }}
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
        <Button size="large" type="primary" htmlType="submit" block>
          Save changes
        </Button>
      </Form.Item>
    </Form>
  );
};
