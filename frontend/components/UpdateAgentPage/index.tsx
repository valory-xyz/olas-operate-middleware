import { ConfigProvider } from 'antd';

import { AgentType } from '@/enums/Agent';
import { useServices } from '@/hooks/useServices';
import { LOCAL_FORM_THEME } from '@/theme';

import { UpdateAgentProvider } from './context/UpdateAgentProvider';
import { MemeUpdatePage } from './MemeUpdatePage';
import { ModiusUpdatePage } from './ModiusUpdateForm';

export const UpdateAgentPage = () => {
  const { selectedAgentType } = useServices();
  return (
    <UpdateAgentProvider>
      <ConfigProvider theme={LOCAL_FORM_THEME}>
        {selectedAgentType === AgentType.Memeooorr && <MemeUpdatePage />}
        {selectedAgentType === AgentType.Modius && <ModiusUpdatePage />}
      </ConfigProvider>
    </UpdateAgentProvider>
  );
};
