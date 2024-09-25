import { Card } from 'antd';
import styled from 'styled-components';

type CardFlexProps = {
  gap?: number;
  noBodyPadding?: boolean;
};
export const CardFlex = styled(Card)<CardFlexProps>`
  .ant-card-body {
    ${(props) => {
      const { gap } = props;

      const gapStyle = gap ? `gap: ${gap}px;` : '';
      const paddingStyle = props.noBodyPadding ? 'padding: 0;' : undefined;

      return `${gapStyle} ${paddingStyle}`;
    }}
    display: flex;
    flex-direction: column;
  }
`;
