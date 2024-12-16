/**
 * Cookies returned by agent-twitter-client
 * when log in
 */
export type XCookie = {
  key: string;
  value: string;
  domain?: string;
  path?: string;
  secure?: boolean;
  httpOnly?: boolean;
  sameSite?: string;
  expires?: string;
};
