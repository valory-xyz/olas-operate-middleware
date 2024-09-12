import { Typography } from 'antd';

const { Text } = Typography;

/**
 * logic to improve activity
 * - Pool for the last transaction agent safe has made (TODO: agent safe or agent instance?)
 * - Update the time of the last transaction
 */

export const LastTransaction = () => {
  return (
    <Text type="secondary" className="text-xs">
      Last txn: 15 mins ago ↗
    </Text>
  );
};
