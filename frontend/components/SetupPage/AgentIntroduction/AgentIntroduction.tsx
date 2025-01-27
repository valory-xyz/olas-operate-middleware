import { Divider, Flex, Typography } from 'antd';
import React, { FC, useCallback, useMemo, useState } from 'react';

import { SetupScreen } from '@/enums/SetupScreen';
import { useServices } from '@/hooks/useServices';
import { useSetup } from '@/hooks/useSetup';

import { IntroductionStep, OnboardingStep } from './IntroductionStep';

const { Text } = Typography;

type IntroductionProps = {
  steps: OnboardingStep[];
  onOnboardingComplete: () => void;
};

const Introduction = ({ steps, onOnboardingComplete }: IntroductionProps) => {
  const { goto } = useSetup();
  const [currentStep, setCurrentStep] = useState(0);

  const onNextStep = useCallback(() => {
    if (currentStep === steps.length - 1) {
      onOnboardingComplete();
    } else {
      setCurrentStep((prev) => (prev + 1) % steps.length);
    }
  }, [currentStep, steps.length, onOnboardingComplete]);

  const onPreviousStep = useCallback(() => {
    if (currentStep === 0) {
      goto(SetupScreen.AgentSelection);
    } else {
      setCurrentStep((prev) => prev - 1);
    }
  }, [currentStep, goto]);

  return (
    <IntroductionStep
      title={steps[currentStep].title}
      desc={steps[currentStep].desc}
      imgSrc={steps[currentStep].imgSrc}
      helper={steps[currentStep].helper}
      btnText={currentStep === steps.length - 1 ? 'Set up agent' : 'Continue'}
      onPrev={onPreviousStep}
      onNext={onNextStep}
    />
  );
};

const predictionAgentSteps: OnboardingStep[] = [
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

const agentsFunSteps: OnboardingStep[] = [
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

const modiusSteps: OnboardingStep[] = [
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
 * Display the introduction (onboarding) of the selected agent.
 */
export const AgentIntroduction: FC = () => {
  const { goto } = useSetup();
  const { selectedAgentType, selectedAgentConfig } = useServices();

  const introductionSteps = useMemo(() => {
    if (selectedAgentType === 'trader') return predictionAgentSteps;
    if (selectedAgentType === 'memeooorr') return agentsFunSteps;
    if (selectedAgentType === 'modius') return modiusSteps;

    throw new Error('Invalid agent type');
  }, [selectedAgentType]);

  const onComplete = useCallback(() => {
    // if the selected type requires setting up an agent,
    // should be redirected to setup screen.
    if (selectedAgentConfig.requiresSetup) {
      goto(SetupScreen.SetupYourAgent);
    } else {
      goto(SetupScreen.SetupEoaFunding);
    }
  }, [goto, selectedAgentConfig.requiresSetup]);

  return (
    <>
      <Flex align="center" justify="center" style={{ paddingTop: 12 }}>
        <Text>{selectedAgentConfig.displayName}</Text>
      </Flex>
      <Divider style={{ margin: '12px 0' }} />
      <Introduction
        steps={introductionSteps}
        onOnboardingComplete={onComplete}
      />
    </>
  );
};
