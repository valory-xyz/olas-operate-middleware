import React, { FC } from 'react';

import { CardFlex } from '@/components/styled/CardFlex';

export const AgentIntroduction: FC = () => {
  return (
    <CardFlex gap={10} styles={{ body: { padding: '12px 24px' } }}>
      <h1>Agent Introduction</h1>
      <p>This is a dummy text for the Agent Introduction component.</p>
    </CardFlex>
  );
};
