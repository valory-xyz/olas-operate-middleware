import { Button, Form, Input, Typography } from 'antd';
import { useContext, useMemo } from 'react';

import { useServices } from '@/hooks/useServices';

import { CustomAlert } from '../Alert';
import { MemeFormValues, UpdateAgentContext } from '.';

export const MemeUpdateForm = () => {
  const {
    isEditing,
    form,
    confirmUpdateModal: confirmModal,
  } = useContext(UpdateAgentContext);
  const { selectedService } = useServices();

  const { env_variables } = selectedService || {};

  const initialValues = useMemo<MemeFormValues | null>(() => {
    if (!env_variables) {
      return null;
    }

    const envEntries = Object.entries(env_variables);

    return envEntries.reduce((acc, [key, { value }]) => {
      if (key === 'PERSONA') {
        acc.PERSONA = value;
      } else if (key === 'GENAI_API_KEY') {
        acc.GENAI_API_KEY = value;
      } else if (key === 'TWIKIT_EMAIL') {
        acc.TWIKIT_EMAIL = value;
      } else if (key === 'TWIKIT_USERNAME') {
        acc.TWIKIT_USERNAME = value;
      } else if (key === 'TWIKIT_PASSWORD') {
        acc.TWIKIT_PASSWORD = value;
      }

      return acc;
    }, {} as MemeFormValues);
  }, [env_variables]);

  return (
    <Form
      form={form}
      layout="vertical"
      disabled={!isEditing}
      onFinish={confirmModal?.openModal}
      initialValues={{ ...initialValues }}
    >
      <Form.Item label="Persona description" name="PERSONA">
        <Input.TextArea
          placeholder="Describe your agent's persona"
          autoSize={{ minRows: 3, maxRows: 5 }}
        />
      </Form.Item>
      <Form.Item label="Gemini API key" name="GENAI_API_KEY">
        <Input.Password placeholder="Google Gemini API key" />
      </Form.Item>
      <Form.Item>
        <Typography.Title
          level={4}
          style={{
            marginTop: 0,
            paddingTop: 16,
            borderTop: '1px solid lightgrey',
          }}
        >
          X account credentials
        </Typography.Title>
        <Typography.Text>
          Login details enables your agent to view X and interact with other
          agents.
        </Typography.Text>
      </Form.Item>
      <Form.Item>
        <CustomAlert
          type="warning"
          style={{ padding: 8 }}
          showIcon
          description={`To avoid your X account getting suspended for bot activity, complete the onboarding steps. You can find them on your profile page under "Let's get you set up".`}
        />
      </Form.Item>
      <Form.Item label="X Email" name="TWIKIT_EMAIL">
        <Input placeholder="X Email" />
      </Form.Item>
      <Form.Item label="X Username" name="TWIKIT_USERNAME">
        <Input placeholder="X Username" prefix="@" />
      </Form.Item>
      <Form.Item label="X Password" name="TWIKIT_PASSWORD">
        <Input.Password placeholder="X Password" />
      </Form.Item>
      <Form.Item hidden={!isEditing}>
        <Button size="large" type="primary" htmlType="submit" block>
          Save changes
        </Button>
      </Form.Item>
    </Form>
  );
};
