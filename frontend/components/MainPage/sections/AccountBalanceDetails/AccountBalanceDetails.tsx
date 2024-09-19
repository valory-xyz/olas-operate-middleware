import { WalletOutlined } from '@ant-design/icons';
import { Card, Flex, Typography } from 'antd';
import { useMemo } from 'react';

import { AddressLink } from '@/components/AddressLink';
import { InfoBreakdownList } from '@/components/InfoBreakdown';
import { InfoTooltip } from '@/components/InfoTooltip';
import { CustomModal } from '@/components/styled/CustomModal';
import { COLOR } from '@/constants/colors';
import { MODAL_WIDTH } from '@/constants/width';
import { useBalance } from '@/hooks/useBalance';
import { useWallet } from '@/hooks/useWallet';
import { balanceFormat } from '@/utils/numberFormatters';

import { Container, infoBreakdownParentStyle } from './styles';

const { Title, Paragraph } = Typography;

const SignerTitle = () => (
  <>
    Signer&nbsp;
    <InfoTooltip>
      <Paragraph className="text-sm">
        Your wallet and agent’s wallet use Safe, a multi-signature wallet. The
        app is designed to trigger transactions on these Safe wallets via
        Signers.
      </Paragraph>
      <Paragraph className="text-sm">
        This setup enables features like the backup wallet.
      </Paragraph>
      <Paragraph className="text-sm m-0">
        Note: Signer’s XDAI balance is included in wallet XDAI balances.
      </Paragraph>
    </InfoTooltip>
  </>
);

const YourWalletDetails = () => {
  const { masterSafeAddress } = useWallet();

  return (
    <>
      <Flex vertical gap={12}>
        <WalletOutlined style={{ fontSize: 24, color: COLOR.TEXT_LIGHT }} />
        <Flex justify="space-between" align="center" className="w-full">
          <Title level={5} className="m-0">
            Your wallet
          </Title>
          <AddressLink address={masterSafeAddress} />
        </Flex>
      </Flex>
    </>
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
    <Card>
      <Flex vertical gap={8}>
        <Title level={5} className="m-0">
          OLAS
        </Title>
        <InfoBreakdownList
          list={olasBalances.map((item) => ({
            left: item.title,
            right: `${item.value} OLAS`,
          }))}
          parentStyle={infoBreakdownParentStyle}
        />
      </Flex>
    </Card>
  );
};

const XdaiBalance = () => {
  const { safeBalance } = useBalance();
  const xdaiBalances = useMemo(() => {
    return [
      {
        title: 'Available',
        value: balanceFormat(safeBalance?.ETH ?? 0, 2),
      },
    ];
  }, [safeBalance?.ETH]);

  return (
    <Card>
      <Flex vertical gap={8}>
        <Title level={5} className="m-0">
          XDAI
        </Title>
        <InfoBreakdownList
          list={xdaiBalances.map((item) => ({
            left: item.title,
            right: `${item.value} XDAI`,
          }))}
          parentStyle={infoBreakdownParentStyle}
        />
      </Flex>
    </Card>
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
    <Card>
      <Flex vertical gap={8}>
        <InfoBreakdownList
          list={signerInfo.map((item) => ({
            left: item.title,
            right: item.value,
            rightClassName: 'font-normal',
          }))}
          parentStyle={infoBreakdownParentStyle}
        />
      </Flex>
    </Card>
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
      <Container>
        <YourWalletDetails />
        <OlasBalance />
        <XdaiBalance />
        <Signer />
      </Container>
    </CustomModal>
  );
};
