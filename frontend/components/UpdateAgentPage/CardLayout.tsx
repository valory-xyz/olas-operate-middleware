import { EditOutlined } from '@ant-design/icons';
import { Button } from 'antd';
import { useCallback, useContext } from 'react';

import { CardTitle } from '../Card/CardTitle';
import { CardFlex } from '../styled/CardFlex';
import { UpdateAgentContext } from './context/UpdateAgentProvider';

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

export const CardLayout = ({
  onClickBack,
  children,
}: {
  onClickBack: () => void;
  children: React.ReactNode;
}) => {
  const { isEditing } = useContext(UpdateAgentContext);
  return (
    <CardFlex
      bordered={false}
      title={
        <CardTitle
          backButtonCallback={onClickBack}
          title={isEditing ? 'Edit agent settings' : 'Agent settings'}
        />
      }
      extra={isEditing ? null : <EditButton />}
    >
      {children}
    </CardFlex>
  );
};
