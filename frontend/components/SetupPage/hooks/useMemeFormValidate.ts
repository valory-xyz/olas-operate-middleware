import { useCallback, useState } from 'react';

import { useElectronApi } from '@/hooks/useElectronApi';

import {
  validateGeminiApiKey,
  validateTwitterCredentials,
} from '../SetupYourAgent/validation';

type ValidationStatus = 'valid' | 'invalid' | 'unknown';

type FieldValues = {
  personaDescription: string;
  geminiApiKey: string;
  xEmail: string;
  xUsername: string;
  xPassword: string;
};

export const useMemeFormValidate = () => {
  const electronApi = useElectronApi();

  const [submitButtonText, setSubmitButtonText] = useState('Continue');
  const [geminiApiKeyValidationStatus, setGeminiApiKeyValidationStatus] =
    useState<ValidationStatus>('unknown');
  const [
    twitterCredentialsValidationStatus,
    setTwitterCredentialsValidationStatus,
  ] = useState<ValidationStatus>('unknown');

  const handleValidate = useCallback(
    async (values: Record<keyof FieldValues, string>) => {
      setGeminiApiKeyValidationStatus('unknown');
      setTwitterCredentialsValidationStatus('unknown');

      setSubmitButtonText('Validating Gemini API key...');
      const isGeminiApiValid = await validateGeminiApiKey(values.geminiApiKey);
      setGeminiApiKeyValidationStatus(isGeminiApiValid ? 'valid' : 'invalid');
      if (!isGeminiApiValid) return;

      // validate the twitter credentials
      setSubmitButtonText('Validating Twitter credentials...');
      const { isValid: isTwitterCredentialsValid, cookies } =
        electronApi?.validateTwitterLogin
          ? await validateTwitterCredentials(
              values.xEmail,
              values.xUsername,
              values.xPassword,
              electronApi.validateTwitterLogin,
            )
          : { isValid: false, cookies: undefined };
      setTwitterCredentialsValidationStatus(
        isTwitterCredentialsValid ? 'valid' : 'invalid',
      );
      if (!isTwitterCredentialsValid) return;
      if (!cookies) return;

      // wait for agent setup to complete
      setSubmitButtonText('Setting up agent...');

      return cookies;
    },
    [electronApi.validateTwitterLogin],
  );

  return {
    submitButtonText,
    setSubmitButtonText,
    geminiApiKeyValidationStatus,
    setGeminiApiKeyValidationStatus,
    twitterCredentialsValidationStatus,
    setTwitterCredentialsValidationStatus,
    handleValidate,
  };
};
