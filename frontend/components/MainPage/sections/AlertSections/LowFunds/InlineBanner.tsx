import { CopyOutlined } from '@ant-design/icons';
import { Button, Typography } from 'antd';
import styled from 'styled-components';

import { COLOR } from '@/constants/colors';
import { Address } from '@/types/Address';
import { copyToClipboard } from '@/utils/copyToClipboard';
import { truncateAddress } from '@/utils/truncate';

const { Text } = Typography;

const InlineBannerContainer = styled.div`
  display: flex;
  padding: 8px 8px 8px 12px;
  justify-content: space-between;
  align-items: center;
  align-self: stretch;
  background-color: ${COLOR.WHITE};
  box-shadow:
    0px 1px 2px 0px rgba(0, 0, 0, 0.03),
    0px 1px 6px -1px rgba(0, 0, 0, 0.02),
    0px 2px 4px 0px rgba(0, 0, 0, 0.02);
  color: ${COLOR.TEXT};
  border-radius: 8px;
  margin-top: 8px;
`;

type InlineBannerProps = { text: string; address: Address };

export const InlineBanner = ({ text, address }: InlineBannerProps) => {
  return (
    <InlineBannerContainer>
      <div>{text}</div>
      <div>
        <Text className="text-light">{truncateAddress(address)}</Text>
        <Button
          size="small"
          onClick={() => copyToClipboard(address)}
          className="ml-12"
        >
          <CopyOutlined />
        </Button>
      </div>
    </InlineBannerContainer>
  );
};
