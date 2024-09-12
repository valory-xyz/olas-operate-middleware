import { isNumber } from 'lodash';

export const getTimeAgo = (timestamp: number) => {
  if (!isNumber(timestamp)) {
    return new Error('Invalid timestamp');
  }

  // const now = new Date();
  // const pastDate = new Date(timestamp); // Parse the ISO 8601 timestamp string
  // const timeDifference = now.getTime() - pastDate.getTime(); // Difference in milliseconds

  const now = new Date();
  const timeDifference = now.getTime() - new Date(timestamp * 1000).getTime(); // Difference in milliseconds

  const seconds = Math.floor(timeDifference / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);

  if (days > 0) {
    return days === 1 ? '1 day ago' : `${days} days ago`;
  } else if (hours > 0) {
    return hours === 1 ? '1 hour ago' : `${hours} hours ago`;
  } else if (minutes > 0) {
    return minutes === 1 ? '1 minute ago' : `${minutes} minutes ago`;
  } else {
    return 'Few seconds ago';
  }
};
