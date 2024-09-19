import { InfoCircleOutlined } from '@ant-design/icons';
import Tooltip, { TooltipPlacement } from 'antd/es/tooltip';

export const InfoTooltip = ({
  placement = 'topLeft',
  children,
}: {
  placement?: TooltipPlacement;
  children: React.ReactNode;
}) => (
  <Tooltip arrow={false} title={children} placement={placement}>
    <InfoCircleOutlined />
  </Tooltip>
);
