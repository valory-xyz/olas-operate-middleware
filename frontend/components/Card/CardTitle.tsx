import { ArrowLeftOutlined } from '@ant-design/icons';
import { Flex, Typography } from 'antd';
import Button from 'antd/es/button';
import { ReactNode } from 'react';

export const CardTitle = ({
  title,
  showBackButton,
  backButtonCallback,
}: {
  title: string | ReactNode;
  showBackButton?: boolean;
  backButtonCallback?: () => void;
}) => (
  <Flex justify="start" align="center" gap={12}>
    {showBackButton && (
      <Button onClick={backButtonCallback} icon={<ArrowLeftOutlined />} />
    )}
    <Typography.Title className="m-0" level={4}>
      {title}
    </Typography.Title>
  </Flex>
);
