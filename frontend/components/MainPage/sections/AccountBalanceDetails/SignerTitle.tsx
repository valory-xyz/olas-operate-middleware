import { Typography } from 'antd';

import { InfoTooltip } from '@/components/InfoTooltip';

const { Paragraph } = Typography;

export const SignerTitle = () => (
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
