import { useQuery } from '@tanstack/react-query';
import { Flex } from 'antd';
import useToken from 'antd/es/theme/useToken';
import semver from 'semver';

import { CustomAlert } from '@/components/Alert';
import { ArrowUpRightSvg } from '@/components/custom-icons/ArrowUpRight';
import { DOWNLOAD_URL } from '@/constants/urls';

enum SemverComparisonResult {
  OUTDATED = -1,
  EQUAL = 0,
  UPDATED = 1,
}

export const UpdateAvailableAlert = () => {
  const [, token] = useToken();

  const { data: isPearlOutdated, isFetched } = useQuery<boolean>({
    queryKey: ['isPearlOutdated'],
    queryFn: async (): Promise<boolean> => {
      const response = await fetch(
        'https://api.github.com/repos/valory-xyz/olas-operate-app/releases/latest',
      );
      if (!response.ok) return false;

      const data = await response.json();
      const latestTag = data.tag_name;

      const latestVersion = semver.parse(latestTag);

      const currentVersion = semver.parse(
        process.env.NEXT_PUBLIC_PEARL_VERSION ?? '0.0.0',
      );

      if (!latestVersion || !currentVersion) {
        return false;
      }

      const comparison: SemverComparisonResult = semver.compare(
        currentVersion,
        latestVersion,
      );

      return comparison === SemverComparisonResult.OUTDATED;
    },
    refetchInterval: 1000 * 60 * 5, // 5 minutes
  });

  if (!isFetched || !isPearlOutdated) {
    return null;
  }

  return (
    <CustomAlert
      type="info"
      fullWidth
      showIcon
      message={
        <Flex align="center" justify="space-between" gap={2}>
          <span>A new version of Pearl is available</span>
          <a href={DOWNLOAD_URL} target="_blank">
            Download{' '}
            <ArrowUpRightSvg
              fill={token.colorPrimary}
              style={{ marginBottom: -2 }}
            />
          </a>
        </Flex>
      }
    />
  );
};
