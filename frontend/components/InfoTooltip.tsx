import { InfoCircleOutlined } from '@ant-design/icons';
import Tooltip, { TooltipPlacement } from 'antd/es/tooltip';

import { COLOR } from '@/constants/colors';

export const InfoTooltip = ({
  placement = 'topLeft',
  children,
}: {
  placement?: TooltipPlacement;
  children: React.ReactNode;
}) => (
  <Tooltip arrow={false} title={children} placement={placement}>
    <InfoCircleOutlined style={{ color: COLOR.TEXT_LIGHT }} />
  </Tooltip>
);
