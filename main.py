# MartinaAI SDK — Single-file client for MartinaAI trading bot contract.
# SPDX-License-Identifier: MIT

from __future__ import annotations

import os
import json
import time
import hashlib
import logging
import argparse
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Callable, Optional, Sequence

try:
    from web3 import Web3
    from web3.contract import Contract
    from eth_account import Account
    from eth_account.signers.local import LocalAccount
except ImportError:
    Web3 = None
    Contract = None
    Account = None
    LocalAccount = None

logger = logging.getLogger("martinaai")

# -----------------------------------------------------------------------------
# MartinaAI constants (unique; not shared with other projects)
# -----------------------------------------------------------------------------

MARTINA_BPS_DENOM = 10000
MARTINA_MAX_SLIPPAGE_BPS = 100
MARTINA_MIN_PATH_LEN = 2
MARTINA_MAX_PATH_LEN = 5
MARTINA_DOMAIN_TAG_HEX = "0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c"
DEFAULT_DEADLINE_OFFSET_SEC = 600
DEFAULT_GAS_LIMIT_ORDER = 400_000
DEFAULT_GAS_LIMIT_SWAP = 350_000

# MartinaAI contract ABI (order + execute + config)
MARTINAAI_ABI = [
    {
        "inputs": [
            {"name": "tokenIn", "type": "address"},
            {"name": "tokenOut", "type": "address"},
            {"name": "amountIn", "type": "uint256"},
            {"name": "amountOutMin", "type": "uint256"},
            {"name": "deadline", "type": "uint256"},
        ],
        "name": "placeOrder",
        "outputs": [{"name": "orderId", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"name": "orderId", "type": "uint256"}],
        "name": "executeOrder",
        "outputs": [{"name": "amountOut", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"name": "orderId", "type": "uint256"}],
        "name": "cancelOrder",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"name": "tokenIn", "type": "address"},
            {"name": "tokenOut", "type": "address"},
            {"name": "amountIn", "type": "uint256"},
            {"name": "amountOutMin", "type": "uint256"},
            {"name": "deadline", "type": "uint256"},
        ],
        "name": "executeSwapDirect",
        "outputs": [{"name": "amountOut", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"name": "orderId", "type": "uint256"}],
        "name": "getOrder",
        "outputs": [
            {"name": "tokenIn", "type": "address"},
            {"name": "tokenOut", "type": "address"},
            {"name": "amountIn", "type": "uint256"},
            {"name": "amountOutMin", "type": "uint256"},
            {"name": "deadline", "type": "uint256"},
            {"name": "filled", "type": "bool"},
            {"name": "cancelled", "type": "bool"},
            {"name": "placedAtBlock", "type": "uint256"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {"inputs": [], "name": "getOrderCount", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "orders", "outputs": [
        {"name": "tokenIn", "type": "address"},
        {"name": "tokenOut", "type": "address"},
        {"name": "amountIn", "type": "uint256"},
        {"name": "amountOutMin", "type": "uint256"},
        {"name": "deadline", "type": "uint256"},
        {"name": "filled", "type": "bool"},
        {"name": "cancelled", "type": "bool"},
        {"name": "placedAtBlock", "type": "uint256"},
    ], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "martinaOperator", "outputs": [{"name": "", "type": "address"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "router", "outputs": [{"name": "", "type": "address"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "treasury", "outputs": [{"name": "", "type": "address"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "vault", "outputs": [{"name": "", "type": "address"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "botPaused", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "orderCounter", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "genesisBlock", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
]

ERC20_ABI = [
    {"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "symbol", "outputs": [{"name": "", "type": "string"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}], "name": "allowance", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
]

CHAIN_RPC = {
    1: os.environ.get("ETHEREUM_RPC", "https://eth.llamarpc.com"),
    5: os.environ.get("GOERLI_RPC", "https://rpc.ankr.com/eth_goerli"),
    10: os.environ.get("OPTIMISM_RPC", "https://mainnet.optimism.io"),
    137: os.environ.get("POLYGON_RPC", "https://polygon-rpc.com"),
    42161: os.environ.get("ARBITRUM_RPC", "https://arb1.arbitrum.io/rpc"),
    8453: os.environ.get("BASE_RPC", "https://mainnet.base.org"),
    56: os.environ.get("BSC_RPC", "https://bsc-dataseed.binance.org"),
    43114: os.environ.get("AVAX_RPC", "https://api.avax.network/ext/bc/C/rpc"),
}


