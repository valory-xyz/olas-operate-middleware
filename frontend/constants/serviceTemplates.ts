import { ServiceTemplate, EnvProvisionType } from '@/client';
import { StakingProgramId } from '@/enums/StakingProgram';

import { CHAINS } from './chains';

export const SERVICE_TEMPLATES: ServiceTemplate[] = [
  {
    name: 'Trader Agent',
    hash: 'bafybeidicxsruh3r4a2xarawzan6ocwyvpn3ofv42po5kxf7x6ck7kn22u',
    description: 'Trader agent for omen prediction markets',
    image:
      'https://operate.olas.network/_next/image?url=%2Fimages%2Fprediction-agent.png&w=3840&q=75',
    service_version: 'v0.18.4',
    home_chain_id: '100',
    configurations: {
      100: {
        staking_program_id: StakingProgramId.OptimusAlpha, // default, may be overwritten
        nft: 'bafybeig64atqaladigoc3ds4arltdu63wkdrk3gesjfvnfdmz35amv7faq',
        rpc: 'http://localhost:8545',
        agent_id: 14,
        threshold: 1,
        use_staking: true,
        use_mech_marketplace: true,
        cost_of_bond: 10000000000000000,
        monthly_gas_estimate: 10000000000000000000,
        fund_requirements: {
          agent: 100000000000000000,
          safe: 5000000000000000000,
        },
      },
    },
    env_variables: {
      GNOSIS_LEDGER_RPC: {
        name: "Gnosis ledger RPC",
        env_variable_name: "GNOSIS_LEDGER_RPC",
        description: "",
        value: "",
        provision_type: EnvProvisionType.COMPUTED
      },
      // ETHEREUM_LEDGER_RPC: {
      //   name: "Ethereum ledger RPC",
      //   env_variable_name: "ETHEREUM_LEDGER_RPC",
      //   description: "",
      //   value: "",
      //   provision_type: EnvProvisionType.COMPUTED
      // },
      // BASE_LEDGER_RPC: {
      //   name: "Base ledger RPC",
      //   env_variable_name: "BASE_LEDGER_RPC",
      //   description: "",
      //   value: "",
      //   provision_type: EnvProvisionType.COMPUTED
      // },
      // OPTIMISM_LEDGER_RPC: {
      //   name: "Optimism ledger RPC",
      //   env_variable_name: "OPTIMISM_LEDGER_RPC",
      //   description: "",
      //   value: "",
      //   provision_type: EnvProvisionType.COMPUTED
      // },      
      STAKING_CONTRACT_ADDRESS: {
        name: "Staking contract address",
        env_variable_name: "STAKING_CONTRACT_ADDRESS",
        description: "",
        value: "",
        provision_type: EnvProvisionType.COMPUTED
      },
      MECH_ACTIVITY_CHECKER_CONTRACT: {
        name: "Mech activity checker contract",
        env_variable_name: "MECH_ACTIVITY_CHECKER_CONTRACT",
        description: "",
        value: "",
        provision_type: EnvProvisionType.COMPUTED
      },
      MECH_CONTRACT_ADDRESS: {
        name: "Mech contract address",
        env_variable_name: "MECH_CONTRACT_ADDRESS",
        description: "",
        value: "",
        provision_type: EnvProvisionType.COMPUTED
      },
      MECH_REQUEST_PRICE: {
        name: "Mech request price",
        env_variable_name: "MECH_REQUEST_PRICE",
        description: "",
        value: "",
        provision_type: EnvProvisionType.COMPUTED
      },
      USE_MECH_MARKETPLACE: {
        name: "Use Mech marketplace",
        env_variable_name: "USE_MECH_MARKETPLACE",
        description: "",
        value: "",
        provision_type: EnvProvisionType.COMPUTED
      },
      REQUESTER_STAKING_INSTANCE_ADDRESS: {
        name: "Requester staking instance address",
        env_variable_name: "REQUESTER_STAKING_INSTANCE_ADDRESS",
        description: "",
        value: "",
        provision_type: EnvProvisionType.COMPUTED
      },
      PRIORITY_MECH_ADDRESS: {
        name: "Priority Mech address",
        env_variable_name: "PRIORITY_MECH_ADDRESS",
        description: "",
        value: "",
        provision_type: EnvProvisionType.COMPUTED
      }
    },
  },
  //   {
  //     name: 'Optimus Test',
  //     hash: 'bafybeibzujtdlgsft3hnjmboa5yfni7vqc2iocjlyti5nadc55jxj3kxbu',
  //     description: 'Optimus',
  //     image:
  //       'https://operate.olas.network/_next/image?url=%2Fimages%2Fprediction-agent.png&w=3840&q=75',
  //     service_version: 'v0.2.9',
  //     home_chain_id: `${CHAINS.OPTIMISM.chainId}`,
  //     configurations: {
  //       [CHAINS.OPTIMISM.chainId]: {
  //         staking_program_id: StakingProgramId.OptimusAlpha, // default, may be overwritten
  //         nft: 'bafybeig64atqaladigoc3ds4arltdu63wkdrk3gesjfvnfdmz35amv7faq',
  //         // rpc: 'http://localhost:8545',
  //         agent_id: 40,
  //         threshold: 1,
  //         use_staking: true,
  //         use_mech_marketplace: false,
  //         cost_of_bond: 1000,
  //         monthly_gas_estimate: 1000,
  //         fund_requirements: {
  //           agent: 1000,
  //           safe: 1000,
  //         },
  //       },
  //       [CHAINS.ETHEREUM.chainId]: {
  //         staking_program_id: StakingProgramId.OptimusAlpha, // default, may be overwritten
  //         nft: 'bafybeig64atqaladigoc3ds4arltdu63wkdrk3gesjfvnfdmz35amv7faq',
  //         // rpc: 'http://localhost:8545',
  //         agent_id: 40,
  //         threshold: 1,
  //         use_staking: false,
  //         use_mech_marketplace: false,
  //         cost_of_bond: 1,
  //         monthly_gas_estimate: 1000,
  //         fund_requirements: {
  //           agent: 1000,
  //           safe: 1000,
  //         },
  //       },
  //       [CHAINS.BASE.chainId]: {
  //         staking_program_id: StakingProgramId.OptimusAlpha, // default, may be overwritten
  //         nft: 'bafybeig64atqaladigoc3ds4arltdu63wkdrk3gesjfvnfdmz35amv7faq',
  //         // rpc: 'http://localhost:8545',
  //         agent_id: 40,
  //         threshold: 1,
  //         use_staking: false,
  //         use_mech_marketplace: false,
  //         cost_of_bond: 1,
  //         monthly_gas_estimate: 1000,
  //         fund_requirements: {
  //           agent: 1000,
  //           safe: 1000,
  //         },
  //       },
  //     },
  //   },
];
