import { CloseOutlined } from '@ant-design/icons';
import {
  Button,
  ConfigProvider,
  Flex,
  Skeleton,
  ThemeConfig,
  Typography,
} from 'antd';
import { isEmpty, isNil } from 'lodash';
import { useMemo } from 'react';

import { AddressLink } from '@/components/AddressLink';
import { CardTitle } from '@/components/Card/CardTitle';
import { InfoBreakdownList } from '@/components/InfoBreakdown';
import { CardFlex } from '@/components/styled/CardFlex';
import { getNativeTokenSymbol } from '@/config/tokens';
import { ChainId } from '@/enums/Chain';
import { Pages } from '@/enums/Pages';
import { TokenSymbol } from '@/enums/Token';
import { useBalanceContext } from '@/hooks/useBalanceContext';
import { usePageState } from '@/hooks/usePageState';
import { useMasterWalletContext } from '@/hooks/useWallet';
import { type Address } from '@/types/Address';
import { Optional } from '@/types/Util';
import { balanceFormat } from '@/utils/numberFormatters';

import { Container, infoBreakdownParentStyle } from './styles';
import { SignerTitle } from './Titles';
import { YourAgentWallet } from './YourAgent';

const { Text } = Typography;

const yourWalletTheme: ThemeConfig = {
  components: {
    Card: { paddingLG: 16 },
  },
};

const YourWalletTitle = () => <CardTitle title="Your wallets" />;

const Address = () => {
  const { masterSafes } = useMasterWalletContext();

  if (!masterSafes) return <Skeleton />;
  if (isEmpty(masterSafes)) return null;

  const masterSafeAddress = masterSafes[0].address; // TODO: handle multiple safes in future

  return (
    <Flex vertical gap={8}>
      <InfoBreakdownList
        list={[
          {
            left: 'Address',
            leftClassName: 'text-light',
            right: <AddressLink address={masterSafeAddress} />,
            rightClassName: 'font-normal',
          },
        ]}
        parentStyle={infoBreakdownParentStyle}
      />
    </Flex>
  );
};

const OlasBalance = () => {
  const { masterSafes } = useMasterWalletContext();
  const { walletBalances, totalStakedOlasBalance } = useBalanceContext();

  const masterSafeOlasBalance: number = walletBalances
    ?.filter((balance) => balance.symbol === TokenSymbol.OLAS)
    .reduce((acc, balance) => acc + balance.balance, 0);

  const olasBalances = useMemo(() => {
    return [
      {
        title: 'Available',
        value: balanceFormat(masterSafeOlasBalance ?? 0, 2),
      },
      {
        title: 'Staked',
        value: balanceFormat(totalStakedOlasBalance ?? 0, 2),
      },
    ];
  }, [masterSafeOlasBalance, totalStakedOlasBalance]);

  if (!masterSafes) return <Skeleton />;
  if (isEmpty(masterSafes)) return null;

  return (
    <Flex vertical gap={8}>
      <Text strong>{TokenSymbol.OLAS}</Text>
      <InfoBreakdownList
        list={olasBalances.map((item) => ({
          left: item.title,
          leftClassName: 'text-light',
          right: `${item.value} ${TokenSymbol.OLAS}`,
        }))}
        parentStyle={infoBreakdownParentStyle}
      />
    </Flex>
  );
};

const MasterSafeNativeBalance = () => {
  const { masterSafes, masterEoa } = useMasterWalletContext();
  const { walletBalances } = useBalanceContext();

  const masterSafeNativeBalance: Optional<number> = useMemo(() => {
    if (isNil(masterSafes)) return;
    if (isNil(walletBalances)) return;

    if (isEmpty(masterSafes)) return 0;
    if (isEmpty(walletBalances)) return 0;

    const masterSafe = masterSafes[0]; // TODO: handle multiple safes in future

    return walletBalances
      .filter(
        ({ walletAddress }) =>
          walletAddress === masterSafe.address || // TODO: handle multiple safes in future
          walletAddress === masterEoa?.address,
      )
      .reduce((acc, balance) => acc + balance.balance, 0);
  }, [masterEoa?.address, masterSafes, walletBalances]);

  const nativeTokenSymbol = getNativeTokenSymbol(ChainId.Gnosis);

  return (
    <Flex vertical gap={8}>
      <InfoBreakdownList
        list={[
          {
            left: <Text strong>{getNativeTokenSymbol(ChainId.Gnosis)}</Text>,
            leftClassName: 'text-light',
            right: `${balanceFormat(masterSafeNativeBalance, 2)} ${nativeTokenSymbol}`,
          },
        ]}
        parentStyle={infoBreakdownParentStyle}
      />
    </Flex>
  );
};

const MasterEoaSignerNativeBalance = () => {
  const { masterEoa } = useMasterWalletContext();
  const { walletBalances } = useBalanceContext();

  const masterEoaBalance: Optional<number> = useMemo(() => {
    if (isNil(masterEoa)) return;
    if (isNil(walletBalances)) return;

    return walletBalances
      .filter(
        (
          { walletAddress, isNative }, // TODO: support chainId grouping, for multi-agent
        ) => walletAddress === masterEoa.address && isNative,
      )
      .reduce((acc, balance) => acc + balance.balance, 0);
  }, [masterEoa, walletBalances]);

  const nativeTokenSymbol = useMemo(
    () => getNativeTokenSymbol(ChainId.Gnosis),
    [],
  ); // TODO: support multi chain

  return (
    <Flex vertical gap={8}>
      <InfoBreakdownList
        list={[
          {
            left: (
              <SignerTitle
                signerText="Your wallet signer address:"
                signerAddress={masterEoa?.address}
              />
            ),
            leftClassName: 'text-light',
            right: `${balanceFormat(masterEoaBalance, 2)} ${nativeTokenSymbol}`,
          },
        ]}
        parentStyle={infoBreakdownParentStyle}
      />
    </Flex>
  );
};

export const YourWalletPage = () => {
  const { goto } = usePageState();

  return (
    <ConfigProvider theme={yourWalletTheme}>
      <CardFlex
        bordered={false}
        title={<YourWalletTitle />}
        extra={
          <Button
            size="large"
            icon={<CloseOutlined />}
            onClick={() => goto(Pages.Main)}
          />
        }
      >
        <Container style={{ margin: 8 }}>
          <Address />
          <OlasBalance />
          <MasterSafeNativeBalance />
          <MasterEoaSignerNativeBalance />
          <YourAgentWallet />
        </Container>
      </CardFlex>
    </ConfigProvider>
  );
};
