import { LeftOutlined } from '@ant-design/icons';
import { Button, Flex, Typography } from 'antd';
import { AnimatePresence, motion } from 'framer-motion';
import Image from 'next/image';

import { APP_WIDTH } from '@/constants/width';

const { Title, Text } = Typography;

export type OnboardingStep = {
  title: string;
  desc: string;
  imgSrc: string;
  helper?: string;
};

type AnimatedImageProps = {
  imgSrc: string;
  alt: string;
  width: number;
  height: number;
};

const AnimatedImage = ({ imgSrc, alt, width, height }: AnimatedImageProps) => (
  <AnimatePresence mode="wait">
    <motion.div
      key={imgSrc}
      initial={{ opacity: 0, x: 10, scale: 0.99 }}
      animate={{ opacity: 1, x: 0, scale: 1 }}
      exit={{ opacity: 0, x: -10, scale: 0.99 }}
      transition={{
        opacity: { duration: 0.1 },
        scale: { duration: 0.1 },
        duration: 0.1,
      }}
    >
      <Image src={imgSrc} alt={alt} width={width} height={height} priority />
    </motion.div>
  </AnimatePresence>
);

const AnimatedContent = ({
  title,
  desc,
  helper,
}: Pick<OnboardingStep, 'title' | 'desc' | 'helper'>) => (
  <AnimatePresence mode="wait">
    <motion.div
      key={title}
      initial={{ opacity: 0, x: 5 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -5 }}
      transition={{ duration: 0.1 }}
    >
      <Flex vertical gap={8}>
        <Title level={5} className="m-0">
          {title}
        </Title>
        <Text>{desc}</Text>
        {helper && (
          <Text type="secondary" className="text-sm">
            {helper}
          </Text>
        )}
      </Flex>
    </motion.div>
  </AnimatePresence>
);

type IntroductionProps = OnboardingStep & {
  btnText: string;
  onPrev: () => void;
  onNext: () => void;
};

export const IntroductionStep = ({
  title,
  desc,
  imgSrc,
  helper,
  btnText,
  onPrev,
  onNext,
}: IntroductionProps) => {
  return (
    <div style={{ overflow: 'hidden' }}>
      {/* TODO: width & height needs to be fixed */}
      <AnimatedImage
        imgSrc={`/${imgSrc}.svg`}
        alt={title}
        width={APP_WIDTH - 8}
        height={400 - 8}
      />

      <div className="p-24">
        <Flex vertical gap={24}>
          <AnimatedContent title={title} desc={desc} helper={helper} />

          <Flex gap={12}>
            <Button
              onClick={onPrev}
              size="large"
              style={{ minWidth: 40 }}
              icon={<LeftOutlined />}
            />
            <Button onClick={onNext} type="primary" block size="large">
              {btnText}
            </Button>
          </Flex>
        </Flex>
      </div>
    </div>
  );
};
