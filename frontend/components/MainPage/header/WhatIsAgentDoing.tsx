import { Button } from 'antd';

import { Pages } from '@/enums/Pages';
import { usePageState } from '@/hooks/usePageState';

export const WhatIsAgentDoing = () => {
  const { goto } = usePageState();
  return (
    <Button
      type="link"
      className="p-0 text-xs"
      onClick={() => goto(Pages.AgentActivity)}
    >
      What&apos;s my agent doing?
    </Button>
  );
};
