import { z } from 'zod';

export type Address = string;

export const AddressSchema = z.string().refine((value) => {
  return /^0x[0-9a-fA-F]{40}$/.test(value);
});
