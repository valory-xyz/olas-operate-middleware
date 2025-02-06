import { isEmpty, isNil } from 'lodash';

export const isNilOrEmpty = <T>(
  values: T | null | undefined,
): values is null | undefined | Extract<T, never> => {
  return isNil(values) || isEmpty(values);
};
