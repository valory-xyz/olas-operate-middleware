import { isEmpty } from 'lodash';

import { EnvProvisionType, ServiceTemplate } from '@/client';
import { SERVICE_TEMPLATES } from '@/constants/serviceTemplates';
import { AgentType } from '@/enums/Agent';
import { ServicesService } from '@/service/Services';
import { Service } from '@/types/Service';
import { DeepPartial } from '@/types/Util';

export const updateServiceIfNeeded = async (
  service: Service,
): Promise<void> => {
  const partialServiceTemplate: DeepPartial<ServiceTemplate> = {};
  const serviceTemplate = SERVICE_TEMPLATES.find(
    (template) => template.name === service.name,
  );

  if (!serviceTemplate) return;

  // Check if the hash is different
  if (service.hash !== serviceTemplate.hash) {
    partialServiceTemplate.hash = serviceTemplate.hash;
  }

  // Temporary: check if the service has the default description
  if (
    serviceTemplate.agentType === AgentType.Memeooorr &&
    service.description === serviceTemplate.description
  ) {
    const xUsername = service.env_variables?.TWIKIT_USERNAME?.value;
    if (xUsername) {
      partialServiceTemplate.description = `Memeooorr @${xUsername}`;
    }
  }

  // Check if fixed env variables of the service were updated in the template
  const envVariablesToUpdate: ServiceTemplate['env_variables'] = {};
  Object.entries(service.env_variables).forEach(([key, item]) => {
    const templateEnvVariable = serviceTemplate.env_variables[key];
    if (!templateEnvVariable) return;

    if (
      templateEnvVariable.provision_type === EnvProvisionType.FIXED &&
      templateEnvVariable.value !== item.value
    ) {
      envVariablesToUpdate[key] = templateEnvVariable;
    }
  });

  if (!isEmpty(envVariablesToUpdate)) {
    partialServiceTemplate.env_variables = envVariablesToUpdate;
  }

  // Check if fund_requirements were updated
  const serviceHomeChain = service.home_chain;
  const serviceHomeChainFundRequirements =
    service.chain_configs[serviceHomeChain].chain_data.user_params
      .fund_requirements;
  const templateFundRequirements =
    serviceTemplate.configurations[serviceHomeChain].fund_requirements;

  if (
    Object.entries(serviceHomeChainFundRequirements).some(([key, item]) => {
      return (
        templateFundRequirements[key].agent !== item.agent ||
        templateFundRequirements[key].safe !== item.safe
      );
    })
  ) {
    // Need to pass all fund requirements from the template
    // even if some of them were updated
    partialServiceTemplate.configurations = {
      [serviceHomeChain]: {
        fund_requirements: templateFundRequirements,
      },
    };
  }

  if (isEmpty(partialServiceTemplate)) return;

  await ServicesService.updateService({
    serviceConfigId: service.service_config_id,
    partialServiceTemplate,
  });
};
