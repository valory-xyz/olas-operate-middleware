import React, { FC, useMemo } from 'react';

import { CardFlex } from '@/components/styled/CardFlex';
import { useServices } from '@/hooks/useServices';

const Introduction = ({ steps }: { steps: IntroductionStep[] }) => {
  window.console.log(steps);

  return (
    <CardFlex gap={10} styles={{ body: { padding: '12px 24px' } }}>
      <h1>Agent Introduction</h1>
      <p>This is a dummy text for the Agent Introduction component.</p>
    </CardFlex>
  );
};

type IntroductionStep = {
  title: string;
  desc: string;
  imgSrc: string;
  helper?: string;
};

const predictionAgentSteps: IntroductionStep[] = [
  {
    title: 'Monitor prediction markets',
    desc: 'Your prediction agent actively scans prediction markets to identify new opportunities for investment.',
    imgSrc: 'setup-agent-prediction-1',
  },
  {
    title: 'Place intelligent bets',
    desc: 'Uses AI to make predictions and place bets on events by analyzing market trends and real-time information.',
    imgSrc: 'setup-agent-prediction-2',
  },
  {
    title: 'Collect earnings',
    desc: 'It collects earnings on the go, as the results of the corresponding prediction markets are finalized.',
    imgSrc: 'setup-agent-prediction-3',
  },
];

const agentsFunSteps: IntroductionStep[] = [
  {
    title: 'Create your agent’s persona',
    desc: 'Your agent will post autonomously on X, crafting content based on the persona you provide.',
    imgSrc: 'setup-agent-agents.fun-1',
  },
  {
    title: 'Create and interact with memecoins',
    desc: 'Your agent will autonomously create its own tokens and explore memecoins deployed by other agents.',
    helper:
      'This isn’t financial advice. Agents.Fun operates at your own risk and may experience losses — use responsibly!',
    imgSrc: 'setup-agent-agents.fun-2',
  },
  {
    title: 'Engage with the X community',
    desc: 'Your agent will connect with users and other agents on X, responding, liking, and quoting their posts.',
    imgSrc: 'setup-agent-agents.fun-3',
  },
];

const modiusSteps: IntroductionStep[] = [
  {
    title: 'Gather market data',
    desc: 'Your Modius autonomous investment trading agent collects up-to-date market data from CoinGecko, focusing on select DeFi protocols on the Mode chain.',
    imgSrc: 'setup-agent-modius-1',
  },
  {
    title: 'Choose the best strategy',
    desc: 'Modius learns autonomously, adapts to changing market conditions, and selects the best next strategy to invest on your behalf.',
    imgSrc: 'setup-agent-modius-2',
  },
  {
    title: 'Take action',
    desc: 'Based on its analysis and real-time market data, your Modius agent decides when its more convenient to buy, sell, or hold specific assets.',
    imgSrc: 'setup-agent-modius-3',
  },
];

/**
 * Display the introduction of the selected agent.
 */
export const AgentIntroduction: FC = () => {
  const { selectedAgentType } = useServices();

  const introductionSteps = useMemo(() => {
    if (selectedAgentType === 'trader') return predictionAgentSteps;
    if (selectedAgentType === 'memeooorr') return agentsFunSteps;
    if (selectedAgentType === 'modius') return modiusSteps;

    throw new Error('Invalid agent type');
  }, [selectedAgentType]);

  return (
    <CardFlex
      gap={10}
      styles={{ body: { padding: '12px 24px' } }}
      style={{ border: 'none' }}
    >
      <Introduction steps={introductionSteps} />
    </CardFlex>
  );
};
