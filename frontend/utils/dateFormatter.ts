/**
 *
 * @param timeInMs - time in milliseconds
 * @returns formatted date string
 * @example formatDate(number) => Jan 11, 2025, 10:17:13 PM GMT+5:30
 */
export const formatDate = (timeInMs: number) => {
  if (timeInMs === 0) return null;

  return Intl.DateTimeFormat('en-US', {
    dateStyle: 'medium',
    timeStyle: 'long',
  }).format(new Date(timeInMs));
};
