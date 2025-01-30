import { IdcardOutlined } from '@ant-design/icons';
import { Button, Flex, Typography } from 'antd';
import { FC, useCallback } from 'react';

import { COLOR } from '@/constants/colors';
import { UNICODE_SYMBOLS } from '@/constants/symbols';
import { SetupScreen } from '@/enums/SetupScreen';
import { useSetup } from '@/hooks/useSetup';

const { Title, Paragraph } = Typography;

export const EarlyAccessOnly: FC = () => {
  const { goto } = useSetup();

  const onGoBack = useCallback(() => {
    goto(SetupScreen.AgentSelection);
  }, [goto]);

  return (
    <Flex
      gap={20}
      vertical
      align="center"
      justify="center"
      style={{ padding: 48 }}
    >
      <IdcardOutlined style={{ fontSize: '48px', color: COLOR.TEXT_LIGHT }} />
      <Title level={3} className="m-0">
        Early access only
      </Title>
      <Paragraph className="text-center text-light m-0">
        This agent is available only to early adopters. Fill out the form to
        request access.
      </Paragraph>
      <Button
        type="link"
        href="https://example.com"
        target="_blank"
        rel="noopener noreferrer"
      >
        Request access&nbsp;{UNICODE_SYMBOLS.EXTERNAL_LINK}
      </Button>
      <Button type="default" onClick={onGoBack}>
        Go back
      </Button>
    </Flex>
  );
};
