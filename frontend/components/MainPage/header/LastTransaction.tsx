import { Typography } from 'antd';

const { Text } = Typography;

// TODO: Implement LastTransaction component
export const LastTransaction = () => {
  return (
    <Text type="secondary" className="text-xs">
      Last txn: 15 mins ago ↗
    </Text>
  );
};
