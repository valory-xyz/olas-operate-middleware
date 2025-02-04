define setup_env
    $(eval ENV_FILE := $(1).env)
    @echo " - setup env $(ENV_FILE)"
    $(eval include $(1).env)
    $(eval export)
	@cp $(ENV_FILE) .env
endef


./trader/:
	pwd
	git clone https://github.com/valory-xyz/meme-ooorr.git

./dist/aea_win.exe: ./electron/bins/ ./trader/
	mkdir -p dist
	cd meme-ooorr && poetry lock --no-update && poetry install && poetry add gql==3.5.0 hypothesis==6.21.6 pycoingecko==3.2.0 numpy==2.2.0 pandas>=2.2.3 pyfolio==0.9.2 scipy==1.14.1 && poetry run pyinstaller --collect-all gql --collect-all hypothesis --collect-all pycoingecko --collect-all scipy --hidden-import numpy --collect-all pandas --collect-all pyfolio --collect-all twitter_text --collect-all google.generativeai --collect-all peewee --collect-data eth_account --collect-all aea --collect-all autonomy --collect-all operate --collect-all aea_ledger_ethereum --collect-all aea_ledger_cosmos --collect-all aea_ledger_ethereum_flashbots --hidden-import aea_ledger_ethereum --hidden-import aea_ledger_cosmos --hidden-import aea_ledger_ethereum_flashbots --hidden-import grpc --hidden-import openapi_core --collect-all google.protobuf --collect-all openapi_core --collect-all openapi_spec_validator --collect-all asn1crypto --hidden-import py_ecc --hidden-import pytz --collect-all twikit --collect-all twitter_text_parser --collect-all textblob --onefile pyinstaller/memeooorr_bin.py --name trader_win
	cp -f meme-ooorr/dist/trader_win.exe ./dist/aea_win.exe
	cp -f meme-ooorr/dist/trader_win.exe ./electron/bins/aea_win.exe
	pwd


./dist/aea_bin: ./trader/
	mkdir -p dist
	cd meme-ooorr && poetry lock --no-update && poetry install && poetry add gql==3.5.0 hypothesis==6.21.6 pycoingecko==3.2.0 numpy==2.2.0 pandas>=2.2.3 pyfolio==0.9.2 scipy==1.14.1 && poetry run pyinstaller  --collect-all gql --collect-all hypothesis --collect-all pycoingecko --collect-all scipy --hidden-import numpy --collect-all pandas --collect-all pyfolio --collect-all twitter_text --collect-all google.generativeai --collect-all peewee --collect-data eth_account --collect-all aea --collect-all autonomy --collect-all operate --collect-all aea_ledger_ethereum --collect-all aea_ledger_cosmos --collect-all aea_ledger_ethereum_flashbots --hidden-import aea_ledger_ethereum --hidden-import aea_ledger_cosmos --hidden-import aea_ledger_ethereum_flashbots --hidden-import grpc --hidden-import openapi_core --collect-all google.protobuf --collect-all openapi_core --collect-all openapi_spec_validator --collect-all asn1crypto --hidden-import py_ecc --hidden-import pytz --collect-all twikit --collect-all twitter_text_parser --collect-all textblob --onefile pyinstaller/memeooorr_bin.py --name trader_bin
	cp -f meme-ooorr/dist/trader_bin ./dist/aea_bin
	pwd


./dist/tendermint_win.exe: ./electron/bins/ ./operate/
	pwd
	poetry install && poetry run pyinstaller operate/services/utils/tendermint.py --onefile --name tendermint_win
	cp dist/tendermint_win.exe ./electron/bins/tendermint_win.exe


./dist/pearl_win.exe: ./operate/ ./dist/aea_win.exe ./dist/tendermint_win.exe
	pwd
	poetry install && poetry run pyinstaller --collect-data eth_account --collect-all aea --collect-all coincurve --collect-all autonomy --collect-all operate --collect-all aea_ledger_ethereum --collect-all aea_ledger_cosmos --collect-all aea_ledger_ethereum_flashbots --hidden-import aea_ledger_ethereum --hidden-import aea_ledger_cosmos --hidden-import aea_ledger_ethereum_flashbots operate/pearl.py --onefile --name pearl_win


./electron/bins/:
	mkdir -p ./electron/bins/

./electron/bins/tendermint.exe: ./electron/bins/
	curl -L https://github.com/tendermint/tendermint/releases/download/v0.34.19/tendermint_0.34.19_windows_amd64.tar.gz -o tendermint.tar.gz
	tar -xvf tendermint.tar.gz tendermint.exe
	cp ./tendermint.exe ./electron/bins/tendermint.exe

.PHONY: build
build: ./dist/pearl_win.exe ./electron/bins/tendermint.exe
	$(call setup_env, prod)
	cp -f dist/pearl_win.exe ./electron/bins/pearl_win.exe
	NODE_ENV=${NODE_ENV} GNOSIS_RPC=${GNOSIS_RPC} OPTIMISM_RPC=${OPTIMISM_RPC} BASE_RPC=${BASE_RPC} ETHEREUM_RPC=${ETHEREUM_RPC} MODE_RPC=${MODE_RPC} yarn build:frontend
	NODE_ENV=${NODE_ENV} GNOSIS_RPC=${GNOSIS_RPC} OPTIMISM_RPC=${OPTIMISM_RPC} BASE_RPC=${BASE_RPC} ETHEREUM_RPC=${ETHEREUM_RPC} MODE_RPC=${MODE_RPC} GH_TOKEN=${GH_TOKEN} node build-win.js


.PHONY: build-tenderly
build-tenderly:  ./dist/pearl_win.exe
	$(call setup_env, dev-tenderly)
	cp -f dist/pearl_win.exe ./electron/bins/pearl_win.exe
	NODE_ENV=${NODE_ENV} GNOSIS_RPC=${GNOSIS_RPC} OPTIMISM_RPC=${OPTIMISM_RPC} BASE_RPC=${BASE_RPC} ETHEREUM_RPC=${ETHEREUM_RPC} MODE_RPC=${MODE_RPC} yarn build:frontend
	GH_TOKEN=${GH_TOKEN} node build-win-tenderly.js


define setup_env
    $(eval ENV_FILE := $(1).env)
    @echo " - setup env $(ENV_FILE)"
    $(eval include $(1).env)
    $(eval export)
	@cp $(ENV_FILE) .env
endef

# Default values
CHAIN ?= mode
TOKEN ?= USDC
AMOUNT ?= 44
WALLET_ADDRESS ?= 0x0
CONFIG_TYPE ?= standard
FAST_FORWARD_SECONDS ?= 3600


# Tenderly RPC URLs
GNOSIS_RPC_URL = https://virtual.gnosis.rpc.tenderly.co/d33f24ed-3a9e-4df1-91c5-0a7786f335ad
MODIUS_RPC_URL = https://virtual.mode.rpc.tenderly.co/9f5ab06c-f005-4f8d-8bb2-786cb7b8f865
OPTIMISM_RPC_URL = https://virtual.mode.rpc.tenderly.co/9f5ab06c-f005-4f8d-8bb2-786cb7b8f865
BASE_RPC_URL = https://virtual.base.rpc.tenderly.co/9087b239-8e18-4ec3-91ef-e31a8cbe1066

# Token configurations
# Gnosis Chain Tokens
GNOSIS_USDC = 0xDDAfbb505ad214D7b80b1f830fcCc89B60fb7A83
GNOSIS_OLAS = 0xcE11e14225575945b8E6Dc0D4F2dD4C570f79d9f

# Mode Chain Tokens
MODE_USDC = 0xd988097fb8612cc24eeC14542bC03424c656005f
MODE_OLAS = 0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85

# Optimism Chain Tokens
OPTIMISM_USDC = 0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85

# Base Chain Tokens
BASE_USDC = 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913

# Token decimals
USDC_DECIMALS = 6
OLAS_DECIMALS = 18

help:
	@echo "Available Commands:"
	@echo "  make fund-erc20     - Fund wallet with ERC20 tokens"
	@echo "  make fund-native    - Fund wallet with native tokens (ETH/xDAI)"
	@echo ""
	@echo "Parameters:"
	@echo "  CHAIN          - Chain name (mode, optimism, base, gnosis)"
	@echo "  TOKEN          - Token symbol (USDC, OLAS)"
	@echo "  AMOUNT         - Amount to fund"
	@echo "  WALLET_ADDRESS - Address to fund"
	@echo "  CONFIG_TYPE    - Funding type (standard, modius, optimus)"

validate-address:
	@if ! echo "$(WALLET_ADDRESS)" | grep -qE "^0x[a-fA-F0-9]{40}$$"; then \
		echo "Error: Invalid wallet address format"; \
		exit 1; \
	fi

validate-chain:
	@if [ "$(CHAIN)" != "mode" ] && [ "$(CHAIN)" != "optimism" ] && [ "$(CHAIN)" != "base" ] && [ "$(CHAIN)" != "gnosis" ]; then \
		echo "Error: Invalid chain. Supported: mode, optimism, base, gnosis"; \
		exit 1; \
	fi

validate-token:
	@if [ "$(TOKEN)" != "USDC" ] && [ "$(TOKEN)" != "OLAS" ]; then \
		echo "Error: Invalid token. Supported: USDC, OLAS"; \
		exit 1; \
	fi
	@if [ "$(TOKEN)" = "OLAS" ] && [ "$(CHAIN)" != "mode" ] && [ "$(CHAIN)" != "gnosis" ]; then \
		echo "Error: OLAS token is only supported on Mode and Gnosis chains"; \
		exit 1; \
	fi

get-rpc-url:
ifeq ($(CHAIN),gnosis)
	$(eval RPC_URL=$(GNOSIS_RPC_URL))
else ifeq ($(CHAIN),mode)
	$(eval RPC_URL=$(MODIUS_RPC_URL))
else ifeq ($(CHAIN),optimism)
	$(eval RPC_URL=$(OPTIMISM_RPC_URL))
else
	$(eval RPC_URL=$(BASE_RPC_URL))
endif

define get_token_address
$(shell echo "$($(shell echo $(CHAIN) | tr a-z A-Z)_$(TOKEN))")
endef

define calculate_amount_in_units
$(shell python3 -c "print(hex(int($(AMOUNT) * 10**$($(TOKEN)_DECIMALS))))")
endef

fund-erc20: validate-chain validate-token validate-address get-rpc-url
	$(eval TOKEN_ADDRESS=$(call get_token_address))
	$(eval AMOUNT_IN_UNITS=$(shell python3 -c "print(hex(int(float('$(AMOUNT)') * 10**$($(TOKEN)_DECIMALS))))"))
	@echo "Funding $(AMOUNT) $(TOKEN) to $(WALLET_ADDRESS) on $(CHAIN)"
	@echo "Token Address: $(TOKEN_ADDRESS)"
	@echo "Amount in hex: $(AMOUNT_IN_UNITS)"
	@curl -s -X POST "$(RPC_URL)" \
		-H "Content-Type: application/json" \
		-d '{ \
			"jsonrpc": "2.0", \
			"method": "tenderly_setErc20Balance", \
			"params": [ \
				"$(TOKEN_ADDRESS)", \
				"$(WALLET_ADDRESS)", \
				"$(AMOUNT_IN_UNITS)" \
			], \
			"id": 1 \
		}' | jq '.'
	@echo "Funding request completed"

fund-native: validate-chain validate-address get-rpc-url
	$(eval AMOUNT_TO_FUND=$(AMOUNT))
ifeq ($(CONFIG_TYPE),modius)
	$(eval AMOUNT_TO_FUND=0.6)
	@echo "Modius config: Setting amount to $(AMOUNT_TO_FUND) ETH"
else ifeq ($(CONFIG_TYPE),optimus)
	$(eval AMOUNT_TO_FUND=100)
	@echo "Optimus config: Setting amount to $(AMOUNT_TO_FUND) ETH"
endif
	$(eval AMOUNT_IN_WEI=$(shell echo "$(AMOUNT_TO_FUND) * 10^18" | bc))
	@echo "Funding $(AMOUNT_TO_FUND) ETH to $(WALLET_ADDRESS) on $(CHAIN)"
	@curl -s -X POST "$(RPC_URL)" \
		-H "Content-Type: application/json" \
		-d '{ \
			"jsonrpc": "2.0", \
			"method": "tenderly_addBalance", \
			"params": [ \
				"$(WALLET_ADDRESS)", \
				"0x$(shell printf '%x' $(AMOUNT_IN_WEI))" \
			], \
			"id": 1 \
		}' | jq '.'
	@echo "Funding request completed"

check-balance: validate-chain validate-address get-rpc-url
	@echo "Checking balance for $(WALLET_ADDRESS) on $(CHAIN)..."
	@curl -s -X POST "$(RPC_URL)" \
		-H "Content-Type: application/json" \
		-d '{ \
			"jsonrpc": "2.0", \
			"method": "eth_getBalance", \
			"params": [ \
				"$(WALLET_ADDRESS)", \
				"latest" \
			], \
			"id": 1 \
		}' | jq '.'

fast-forward-time: validate-chain get-rpc-url
	$(eval HEX_SECONDS=$(shell python3 -c "print(hex(int($(FAST_FORWARD_SECONDS))))"))
	@echo "Fast forwarding time by $(FAST_FORWARD_SECONDS) seconds ($(HEX_SECONDS)) on $(CHAIN) network..."
	@curl -s -X POST "$(RPC_URL)" \
		-H "Content-Type: application/json" \
		-d '{ \
			"id": 1, \
			"jsonrpc": "2.0", \
			"method": "evm_increaseTime", \
			"params": [ \
				86400\
			] \
		}' | jq '.'

# Get current timestamp in multiple formats
timestamp: validate-chain get-rpc-url
	@echo "Getting current timestamp on $(CHAIN) network..."
	@curl -s -X POST "$(RPC_URL)" \
		-H "Content-Type: application/json" \
		-d '{ \
			"id": 1, \
			"jsonrpc": "2.0", \
			"method": "eth_getBlockByNumber", \
			"params": [ \
				"latest", \
				false \
			] \
		}' | jq -r '.result.timestamp' | xargs -I {} sh -c '\
		echo "Hex timestamp: {}"; \
		python3 -c "import datetime; \
		ts = int(\"{}\", 16); \
		print(\"Unix timestamp:\", ts); \
		print(\"Date (UTC):\", datetime.datetime.utcfromtimestamp(ts).strftime(\"%Y-%m-%d %H:%M:%S\"))"'

.PHONY: help validate-address validate-chain validate-token get-rpc-url fund-erc20 fund-native check-balance fast-forward-time timestamp