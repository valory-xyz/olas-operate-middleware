# Acquiring RPC Endpoints for Development

## Tenderly

We use Tenderly to fork the Gnosis Mainnet chain for development purposes. This allows us to interact with the chain without risking real funds.

### 1. Create a Tenderly Account

Go to [Tenderly](https://tenderly.co/) and create an account.

### 2. Create a Project

Create a new project in Tenderly.

### 3. Fork the Gnosis Mainnet

1. Go to the _Forks_ section under the _Development_ tab in your Tenderly dashboard.

2. Click _Create Fork_.

3. Select "Gnosis Chain" as the network.

4. Use Chain ID `100`.

5. Copy the RPC URL provided by Tenderly.

### 4. Set the RPC URL

Set the `FORK_URL` and `DEV_RPC` environment variables in your `.env` file to the RPC URL provided by Tenderly.

### 5. Fund Your Accounts

Click the _Fund Accounts_ button in Tenderly to fund your accounts with XDAI (native token) and [OLAS](https://gnosisscan.io/token/0xce11e14225575945b8e6dc0d4f2dd4c570f79d9f).

### 6. Keeping Your Fork Up-to-Date

It is important to update your fork periodically to ensure that your forked chain is up-to-date with mainnet. You can do this by creating a new fork in Tenderly and updating your `FORK_URL` and `DEV_RPC` environment variables.

Alternatively, you can try the Tenderly's virtual testnet feature, which can automatically update your fork for you relative to mainnet. Though, this sometimes results in instability.

## Hardhat (deprecated)

Hardhat is a local alternative to Tenderly for forking EVM chains. It is useful for development purposes, though the chain state is lost once the Hardhat node is turned off.
