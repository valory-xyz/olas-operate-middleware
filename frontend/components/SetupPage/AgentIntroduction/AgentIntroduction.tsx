import { Divider, Flex, Typography } from 'antd';
import React, { FC, useCallback, useMemo, useState } from 'react';

import { SetupScreen } from '@/enums/SetupScreen';
import { useServices } from '@/hooks/useServices';
import { useSetup } from '@/hooks/useSetup';

import {
  AGENTS_FUND_ONBOARDING_STEPS,
  MODIUS_ONBOARDING_STEPS,
  PREDICTION_ONBOARDING_STEPS,
} from './constants';
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
      setCurrentStep((prev) => prev + 1);
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

/**
 * Display the introduction (onboarding) of the selected agent.
 */
export const AgentIntroduction: FC = () => {
  const { goto } = useSetup();
  const { selectedAgentType, selectedAgentConfig } = useServices();

  const introductionSteps = useMemo(() => {
    if (selectedAgentType === 'trader') return PREDICTION_ONBOARDING_STEPS;
    if (selectedAgentType === 'memeooorr') return AGENTS_FUND_ONBOARDING_STEPS;
    if (selectedAgentType === 'modius') return MODIUS_ONBOARDING_STEPS;

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
      <Divider style={{ margin: '12px 0 0 0' }} />
      <Introduction
        steps={introductionSteps}
        onOnboardingComplete={onComplete}
      />
    </>
  );
};
