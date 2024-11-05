/**
 * Validates environment variables
 */

require('dotenv').config();
const { z, ZodError } = require('zod');
const { app } = require('electron');

const nodeEnvRegex = new RegExp(/^(development|production)$/);

// Update z.object keys if env variable names change
const envSchema = z.object({
  NODE_ENV: z
    .string()
    .regex(
      nodeEnvRegex,
      'Invalid NODE_ENV, must be `development` or `production`',
    ),
  BASE_DEV_RPC: z.string().url('Invalid BASE_DEV_RPC must be a valid URL'),
  ETHEREUM_DEV_RPC: z
    .string()
    .url('Invalid ETHEREUM_DEV_RPC_URL must be a valid URL'),
  GNOSIS_DEV_RPC: z.string().url('Invalid GNOSIS_DEV_RPC must be a valid URL'),
  OPTIMISM_DEV_RPC: z
    .string()
    .url('Invalid OPTIMISM_DEV_RPC must be a valid URL'),
});

const validateEnv = () => {
  const { env } = process;
  try {
    envSchema.parse(env);
  } catch (error) {
    console.error(`Invalid environment variables in .env file`);
    console.log(JSON.stringify(error, null, 2));

    if (error instanceof ZodError) {
      for (const issue of error.errors) {
        console.error(issue.message);
      }
    } else {
      console.error('An unexpected error occurred:', error);
    }

    app.quit();
  }
};

module.exports = { validateEnv };
