import { BACKEND_URL } from '@/constants/urls';

/**
 * Gets account status "is_setup"
 */
const getAccount = () =>
  fetch(`${BACKEND_URL}/account`).then((res) => {
    if (res.ok) return res.json();
    throw new Error('Failed to get account');
  });

/**
 * Creates a local user account
 */
const createAccount = (password: string) =>
  fetch(`${BACKEND_URL}/account`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
    },
    body: JSON.stringify({ password }),
  }).then((res) => {
    if (res.ok) return res.json();
    throw new Error('Failed to create account');
  });

/**
 * Updates user's password
 */
const updateAccount = (oldPassword: string, newPassword: string) =>
  fetch(`${BACKEND_URL}/account`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
    },
    body: JSON.stringify({
      old_password: oldPassword,
      new_password: newPassword,
    }),
  }).then((res) => {
    if (res.ok) return res.json();
    throw new Error('Failed to update account');
  });

/**
 * Logs in a user
 */
const loginAccount = (password: string) =>
  fetch(`${BACKEND_URL}/account/login`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
    },
    body: JSON.stringify({
      password,
    }),
  }).then((res) => {
    if (res.ok) return res.json();
    throw new Error('Failed to login');
  });

export const AccountService = {
  getAccount,
  createAccount,
  updateAccount,
  loginAccount,
};
