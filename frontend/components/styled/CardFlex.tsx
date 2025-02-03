import { Card } from 'antd';
import styled from 'styled-components';

type CardFlexProps = {
  gap?: number;
  noBodyPadding?: 'true' | 'false';
  noBorder?: boolean;
};
export const CardFlex = styled(Card).withConfig({
  shouldForwardProp: (prop: string) =>
    !['gap', 'noBodyPadding', 'noBorder'].includes(prop),
})<CardFlexProps>`
  ${(props) => !!props.noBorder && 'border: none;'}

  .ant-card-body {
    ${(props) => {
      const { gap, noBodyPadding } = props;
      const gapStyle = gap ? `gap: ${gap}px;` : '';
      const paddingStyle = noBodyPadding === 'true' ? 'padding: 0;' : '';
      return `${gapStyle} ${paddingStyle}`;
    }}
    display: flex;
    flex-direction: column;
  }
`;
