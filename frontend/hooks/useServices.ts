import { useContext } from 'react';

import { ServicesContext } from '@/context/ServicesProvider';

export const useServices = () => useContext(ServicesContext);
