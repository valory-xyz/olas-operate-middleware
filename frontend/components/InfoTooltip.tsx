import { InfoCircleOutlined } from '@ant-design/icons';
import Tooltip, { TooltipProps } from 'antd/es/tooltip';

import { COLOR } from '@/constants/colors';

export const InfoTooltip = ({
  placement = 'topLeft',
  children,
  ...rest
}: {
  children: React.ReactNode;
} & TooltipProps) => (
  <Tooltip arrow={false} title={children} placement={placement} {...rest}>
    <InfoCircleOutlined style={{ color: COLOR.TEXT_LIGHT }} />
  </Tooltip>
);
