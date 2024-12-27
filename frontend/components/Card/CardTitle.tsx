import { ArrowLeftOutlined } from '@ant-design/icons';
import { Flex, Typography } from 'antd';
import Button from 'antd/es/button';
import { isFunction } from 'lodash';
import { ReactNode } from 'react';

type CardTitleProps = {
  title: string | ReactNode;
  backButtonCallback?: () => void;
};

export const CardTitle = ({ title, backButtonCallback }: CardTitleProps) => (
  <Flex justify="start" align="center" gap={12}>
    {isFunction(backButtonCallback) && (
      <Button onClick={backButtonCallback} icon={<ArrowLeftOutlined />} />
    )}
    <Typography.Title className="m-0" level={4}>
      {title}
    </Typography.Title>
  </Flex>
);
