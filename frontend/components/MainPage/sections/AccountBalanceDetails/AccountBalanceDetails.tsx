import { WalletOutlined } from '@ant-design/icons';
import { Card, Flex, Typography } from 'antd';
import { useMemo } from 'react';
import styled from 'styled-components';

import { AddressLink } from '@/components/AddressLink';
import { InfoBreakdownList } from '@/components/InfoBreakdown';
import { CustomModal } from '@/components/styled/CustomModal';
import { COLOR } from '@/constants/colors';
import { MODAL_WIDTH } from '@/constants/width';
import { useBalance } from '@/hooks/useBalance';
import { useWallet } from '@/hooks/useWallet';
import { balanceFormat } from '@/utils/numberFormatters';

import { SignerTitle } from './SignerTitle';
import { Container, infoBreakdownParentStyle } from './styles';
import { YourAgentWallet } from './YourAgentWallet';

const { Title, Text } = Typography;

const MainCard = styled(Card)`
  > .ant-card-body {
    padding: 16px;
  }
`;

const YourWalletDetails = () => {
  const { masterSafeAddress } = useWallet();

  return (
    <Flex vertical gap={12}>
      <WalletOutlined style={{ fontSize: 24, color: COLOR.TEXT_LIGHT }} />
      <Flex justify="space-between" align="center" className="w-full">
        <Title level={5} className="m-0">
          Your wallet
        </Title>
        <AddressLink address={masterSafeAddress} />
      </Flex>
    </Flex>
  );
};

const OlasBalance = () => {
  const { safeBalance, totalOlasStakedBalance } = useBalance();
  const olasBalances = useMemo(() => {
    return [
      {
        title: 'Available',
        value: balanceFormat(safeBalance?.OLAS ?? 0, 2),
      },
      {
        title: 'Staked',
        value: balanceFormat(totalOlasStakedBalance ?? 0, 2),
      },
    ];
  }, [safeBalance?.OLAS, totalOlasStakedBalance]);

  return (
    <Flex vertical gap={8}>
      <Text strong>OLAS</Text>
      <InfoBreakdownList
        list={olasBalances.map((item) => ({
          left: item.title,
          leftClassName: 'text-light',
          right: `${item.value} OLAS`,
        }))}
        parentStyle={infoBreakdownParentStyle}
      />
    </Flex>
  );
};

const XdaiBalance = () => {
  const { safeBalance } = useBalance();
  const xdaiBalances = useMemo(() => {
    return [
      {
        title: <Text strong>XDAI</Text>,
        value: balanceFormat(safeBalance?.ETH ?? 0, 2),
      },
    ];
  }, [safeBalance?.ETH]);

  return (
    <Flex vertical gap={8}>
      <InfoBreakdownList
        list={xdaiBalances.map((item) => ({
          left: item.title,
          leftClassName: 'text-light',
          right: `${item.value} XDAI`,
        }))}
        parentStyle={infoBreakdownParentStyle}
      />
    </Flex>
  );
};

const Signer = () => {
  const { masterEoaAddress } = useWallet();

  const signerInfo = useMemo(() => {
    return [
      {
        title: <SignerTitle />,
        value: <AddressLink address={masterEoaAddress} />,
      },
    ];
  }, [masterEoaAddress]);

  return (
    <Flex vertical gap={8}>
      <InfoBreakdownList
        list={signerInfo.map((item) => ({
          left: item.title,
          leftClassName: 'text-light',
          right: item.value,
          rightClassName: 'font-normal',
        }))}
        parentStyle={infoBreakdownParentStyle}
      />
    </Flex>
  );
};

type AccountBalanceDetailsProps = {
  hideAccountBalanceDetailsModal: () => void;
};

export const AccountBalanceDetails = ({
  hideAccountBalanceDetailsModal,
}: AccountBalanceDetailsProps) => {
  return (
    <CustomModal
      title="Account balance details"
      open
      width={MODAL_WIDTH}
      bodyPadding
      onCancel={hideAccountBalanceDetailsModal}
      footer={null}
    >
      <MainCard className="main-card">
        <Container>
          <YourWalletDetails />
          <OlasBalance />
          <XdaiBalance />
          <Signer />
          <YourAgentWallet />
        </Container>
      </MainCard>
    </CustomModal>
  );
};
