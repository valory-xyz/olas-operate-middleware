import {
  ExclamationCircleOutlined,
  InfoCircleOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import { Alert as AlertAntd, AlertProps } from 'antd';

type AlertType = 'primary' | 'info' | 'warning' | 'error';

const icons = {
  primary: <InfoCircleOutlined />,
  info: <InfoCircleOutlined />,
  warning: <WarningOutlined />,
  error: <ExclamationCircleOutlined />,
};

type CustomAlertProps = {
  type: AlertType;
  fullWidth?: boolean;
  className?: string;
} & Omit<AlertProps, 'type'>;

export const CustomAlert = ({
  type,
  fullWidth,
  className,
  ...rest
}: CustomAlertProps) => (
  <AlertAntd
    type={type === 'primary' ? undefined : type}
    className={`custom-alert custom-alert--${type} ${fullWidth ? 'custom-alert--full-width' : ''} ${className}`}
    icon={rest.showIcon ? icons[type] : undefined}
    {...rest}
  />
);
