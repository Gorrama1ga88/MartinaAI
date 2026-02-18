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


class MartinaChain(Enum):
    MAINNET = 1
    GOERLI = 5
    OPTIMISM = 10
    POLYGON = 137
    ARBITRUM = 42161
    BASE = 8453
    BSC = 56
    AVALANCHE = 43114


# -----------------------------------------------------------------------------
# Data types
# -----------------------------------------------------------------------------


@dataclass
class MartinaOrder:
    order_id: int
    token_in: str
    token_out: str
    amount_in: int
    amount_out_min: int
    deadline: int
    filled: bool
    cancelled: bool
    placed_at_block: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "token_in": self.token_in,
            "token_out": self.token_out,
            "amount_in": self.amount_in,
            "amount_out_min": self.amount_out_min,
            "deadline": self.deadline,
            "filled": self.filled,
            "cancelled": self.cancelled,
            "placed_at_block": self.placed_at_block,
        }


@dataclass
class MartinaExecuteResult:
    order_id: int
    amount_out: int
    tx_hash: str
    success: bool
    block_number: Optional[int] = None
    gas_used: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "amount_out": self.amount_out,
            "tx_hash": self.tx_hash,
            "success": self.success,
            "block_number": self.block_number,
            "gas_used": self.gas_used,
        }


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def martina_domain_hash(chain_id: int, contract_address: str) -> bytes:
    payload = f"MartinaAI_{chain_id}_{contract_address}"
    return hashlib.sha256(payload.encode()).digest()


def get_w3(chain_id: int, rpc_url: Optional[str] = None) -> "Web3":
    if Web3 is None:
        raise RuntimeError("web3 not installed; pip install web3")
    url = rpc_url or CHAIN_RPC.get(chain_id, "http://127.0.0.1:8545")
    w3 = Web3(Web3.HTTPProvider(url))
    if not w3.is_connected():
        raise ConnectionError(f"Could not connect to RPC: {url}")
    return w3


def to_checksum(addr: str) -> str:
    if Web3 is None:
        return addr
    return Web3.to_checksum_address(addr)


def get_contract(w3: "Web3", address: str, abi: list) -> "Contract":
    if Contract is None:
        raise RuntimeError("web3 not installed")
    return w3.eth.contract(address=to_checksum(address), abi=abi)


def get_erc20(w3: "Web3", token_address: str) -> "Contract":
    return get_contract(w3, token_address, ERC20_ABI)


def get_martinaai(w3: "Web3", contract_address: str) -> "Contract":
    return get_contract(w3, contract_address, MARTINAAI_ABI)


def apply_slippage_martina(amount: int, bps: int, denom: int = MARTINA_BPS_DENOM) -> int:
    return amount * (denom - bps) // denom


def deadline_from_now(offset_sec: int = DEFAULT_DEADLINE_OFFSET_SEC) -> int:
    return int(time.time()) + offset_sec


def format_amount(amount: int, decimals: int) -> str:
    return str(Decimal(amount) / (10**decimals))


def parse_amount(amount_human: str, decimals: int) -> int:
    return int(Decimal(amount_human) * (10**decimals))


def get_token_decimals(w3: "Web3", token_address: str) -> int:
    try:
        c = get_erc20(w3, token_address)
        return c.functions.decimals().call()
    except Exception:
        return 18


def get_token_balance(w3: "Web3", token_address: str, account: str) -> int:
    c = get_erc20(w3, token_address)
    return c.functions.balanceOf(to_checksum(account)).call()


# -----------------------------------------------------------------------------
# MartinaAI client
# -----------------------------------------------------------------------------


class MartinaAIClient:
    """Client for MartinaAI trading bot contract."""

    def __init__(
        self,
        w3: "Web3",
        contract_address: str,
        chain_id: Optional[int] = None,
    ):
        self._w3 = w3
        self._chain_id = chain_id or w3.eth.chain_id
        self._contract_address = to_checksum(contract_address)
        self._contract = get_martinaai(w3, contract_address)

    @property
    def chain_id(self) -> int:
        return self._chain_id

    @property
    def contract_address(self) -> str:
        return self._contract_address

    def is_paused(self) -> bool:
        return self._contract.functions.botPaused().call()

    def get_operator(self) -> str:
        return self._contract.functions.martinaOperator().call()

    def get_router(self) -> str:
        return self._contract.functions.router().call()

    def get_treasury(self) -> str:
        return self._contract.functions.treasury().call()

    def get_vault(self) -> str:
        return self._contract.functions.vault().call()

    def get_order_count(self) -> int:
        return self._contract.functions.orderCounter().call()

    def get_genesis_block(self) -> int:
        return self._contract.functions.genesisBlock().call()

    def get_order(self, order_id: int) -> MartinaOrder:
        raw = self._contract.functions.getOrder(order_id).call()
        return MartinaOrder(
            order_id=order_id,
            token_in=raw[0],
            token_out=raw[1],
            amount_in=raw[2],
            amount_out_min=raw[3],
            deadline=raw[4],
            filled=raw[5],
            cancelled=raw[6],
            placed_at_block=raw[7],
        )

    def build_place_order_tx(
        self,
        token_in: str,
        token_out: str,
        amount_in: int,
        amount_out_min: int,
        deadline: Optional[int] = None,
        from_address: Optional[str] = None,
        gas_limit: int = DEFAULT_GAS_LIMIT_ORDER,
    ) -> dict[str, Any]:
        deadline = deadline or deadline_from_now()
        token_in = to_checksum(token_in)
        token_out = to_checksum(token_out)
        fn = self._contract.functions.placeOrder(
            token_in, token_out, amount_in, amount_out_min, deadline
        )
        return fn.build_transaction({
            "from": to_checksum(from_address) if from_address else None,
            "gas": gas_limit,
        })

    def build_execute_order_tx(
        self,
        order_id: int,
        from_address: Optional[str] = None,
        gas_limit: int = DEFAULT_GAS_LIMIT_SWAP,
    ) -> dict[str, Any]:
        fn = self._contract.functions.executeOrder(order_id)
        return fn.build_transaction({
            "from": to_checksum(from_address) if from_address else None,
            "gas": gas_limit,
        })

    def build_cancel_order_tx(
        self,
        order_id: int,
        from_address: Optional[str] = None,
    ) -> dict[str, Any]:
        fn = self._contract.functions.cancelOrder(order_id)
        return fn.build_transaction({
            "from": to_checksum(from_address) if from_address else None,
        })

    def build_execute_swap_direct_tx(
        self,
        token_in: str,
        token_out: str,
        amount_in: int,
        amount_out_min: int,
        deadline: Optional[int] = None,
        from_address: Optional[str] = None,
        gas_limit: int = DEFAULT_GAS_LIMIT_SWAP,
    ) -> dict[str, Any]:
        deadline = deadline or deadline_from_now()
        token_in = to_checksum(token_in)
        token_out = to_checksum(token_out)
        fn = self._contract.functions.executeSwapDirect(
            token_in, token_out, amount_in, amount_out_min, deadline
        )
        return fn.build_transaction({
            "from": to_checksum(from_address) if from_address else None,
            "gas": gas_limit,
        })

    def place_order(
        self,
        token_in: str,
        token_out: str,
        amount_in: int,
        amount_out_min: int,
        private_key: Optional[str] = None,
        account: Optional["LocalAccount"] = None,
        deadline: Optional[int] = None,
    ) -> int:
        if account is None and private_key:
            if Account is None:
                raise RuntimeError("eth_account not installed")
            account = Account.from_key(private_key)
        if account is None:
            raise ValueError("provide either private_key or account")
        if self.is_paused():
            raise RuntimeError("MartinaAI bot is paused")
        tx = self.build_place_order_tx(
            token_in, token_out, amount_in, amount_out_min,
            deadline=deadline, from_address=account.address,
        )
        tx.pop("from", None)
        signed = account.sign_transaction(tx)
        tx_hash = self._w3.eth.send_raw_transaction(signed.raw_transaction)
        self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        return self.get_order_count()

    def execute_order(
        self,
        order_id: int,
        private_key: Optional[str] = None,
        account: Optional["LocalAccount"] = None,
    ) -> MartinaExecuteResult:
        if account is None and private_key:
            if Account is None:
                raise RuntimeError("eth_account not installed")
            account = Account.from_key(private_key)
        if account is None:
            raise ValueError("provide either private_key or account")
        if self.is_paused():
            raise RuntimeError("MartinaAI bot is paused")
        tx = self.build_execute_order_tx(order_id, from_address=account.address)
        tx.pop("from", None)
        signed = account.sign_transaction(tx)
        tx_hash = self._w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        success = receipt["status"] == 1
        amount_out = 0
        if success:
            try:
                order = self.get_order(order_id)
                amount_out = order.amount_out_min
            except Exception:
                pass
        return MartinaExecuteResult(
            order_id=order_id,
            amount_out=amount_out,
            tx_hash=tx_hash.hex(),
            success=success,
            block_number=receipt.get("blockNumber"),
            gas_used=receipt.get("gasUsed"),
        )

    def cancel_order(
        self,
        order_id: int,
        private_key: Optional[str] = None,
        account: Optional["LocalAccount"] = None,
    ) -> str:
        if account is None and private_key:
            if Account is None:
                raise RuntimeError("eth_account not installed")
            account = Account.from_key(private_key)
        if account is None:
            raise ValueError("provide either private_key or account")
        tx = self.build_cancel_order_tx(order_id, from_address=account.address)
        tx.pop("from", None)
        signed = account.sign_transaction(tx)
        tx_hash = self._w3.eth.send_raw_transaction(signed.raw_transaction)
        self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        return tx_hash.hex()


# -----------------------------------------------------------------------------
# Retry helper
# -----------------------------------------------------------------------------


def with_retry_martina(
    fn: Callable[[], Any],
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
) -> Any:
    last_err = None
    for attempt in range(max_attempts):
        try:
            return fn()
        except exceptions as e:
            last_err = e
            if attempt < max_attempts - 1:
                time.sleep(delay * (backoff ** attempt))
    raise last_err


# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------


def load_martina_config(
    config_path: Optional[str] = None,
    env_prefix: str = "MARTINAAI_",
) -> dict[str, Any]:
    out = {}
    if config_path and os.path.isfile(config_path):
        with open(config_path, "r") as f:
            try:
                out = json.load(f)
            except json.JSONDecodeError:
                pass
    for key, value in os.environ.items():
        if key.startswith(env_prefix):
            k = key[len(env_prefix):].lower()
            if value.isdigit():
                out[k] = int(value)
            elif value.lower() in ("true", "false"):
                out[k] = value.lower() == "true"
            else:
                out[k] = value
    return out


def create_martina_client_from_config(config: Optional[dict[str, Any]] = None) -> MartinaAIClient:
    config = config or load_martina_config()
    chain_id = config.get("chain_id", 1)
    rpc = config.get("rpc_url") or CHAIN_RPC.get(chain_id)
    contract_addr = config.get("contract_address")
    if not contract_addr:
        raise ValueError("config must contain contract_address (or MARTINAAI_CONTRACT_ADDRESS)")
    w3 = get_w3(chain_id, rpc)
    return MartinaAIClient(w3, contract_addr, chain_id)


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="MartinaAI SDK — place and execute orders")
    parser.add_argument("--chain", type=int, default=1, help="Chain ID")
    parser.add_argument("--rpc", type=str, default=None, help="RPC URL")
    parser.add_argument("--contract", type=str, required=True, help="MartinaAI contract address")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_info = sub.add_parser("info", help="Contract info")
    p_orders = sub.add_parser("order-count", help="Get order count")
    p_get = sub.add_parser("get-order", help="Get order by ID")
    p_get.add_argument("order_id", type=int)
    args = parser.parse_args()

    w3 = get_w3(args.chain, args.rpc)
    client = MartinaAIClient(w3, args.contract, args.chain)

    if args.cmd == "info":
        print("operator:", client.get_operator())
        print("router:", client.get_router())
        print("treasury:", client.get_treasury())
        print("vault:", client.get_vault())
        print("paused:", client.is_paused())
        print("order_count:", client.get_order_count())
        print("genesis_block:", client.get_genesis_block())
    elif args.cmd == "order-count":
        print(client.get_order_count())
    elif args.cmd == "get-order":
        order = client.get_order(args.order_id)
        print(json.dumps(order.to_dict(), indent=2))


if __name__ == "__main__":
    main()


# -----------------------------------------------------------------------------
# Mock client for tests
# -----------------------------------------------------------------------------


class MockMartinaAIClient:
    def __init__(self, chain_id: int = 1):
        self._chain_id = chain_id
        self._order_count = 0
        self._orders = {}
        self._paused = False
        self._operator = "0x" + "1" * 40
        self._router = "0x" + "2" * 40
        self._treasury = "0x" + "3" * 40
        self._vault = "0x" + "4" * 40

    @property
    def chain_id(self) -> int:
        return self._chain_id

    def is_paused(self) -> bool:
        return self._paused

    def get_operator(self) -> str:
        return self._operator

    def get_router(self) -> str:
        return self._router

    def get_treasury(self) -> str:
        return self._treasury

    def get_vault(self) -> str:
        return self._vault

    def get_order_count(self) -> int:
        return self._order_count

    def get_order(self, order_id: int) -> MartinaOrder:
        if order_id not in self._orders:
            raise ValueError("Order not found")
        return self._orders[order_id]

    def place_order_mock(self, token_in: str, token_out: str, amount_in: int, amount_out_min: int, deadline: int) -> int:
        self._order_count += 1
        self._orders[self._order_count] = MartinaOrder(
            order_id=self._order_count,
            token_in=token_in,
            token_out=token_out,
            amount_in=amount_in,
            amount_out_min=amount_out_min,
            deadline=deadline,
            filled=False,
            cancelled=False,
            placed_at_block=0,
        )
        return self._order_count


# -----------------------------------------------------------------------------
# Batch order fetch
# -----------------------------------------------------------------------------


def fetch_all_orders(client: MartinaAIClient) -> list[MartinaOrder]:
    count = client.get_order_count()
    out = []
    for i in range(1, count + 1):
        try:
            out.append(client.get_order(i))
        except Exception as e:
            logger.warning("get_order %s failed: %s", i, e)
    return out


# -----------------------------------------------------------------------------
# Validation
# -----------------------------------------------------------------------------


def is_valid_evm_address_martina(addr: str) -> bool:
    if not addr or len(addr) != 42:
        return False
    if addr[:2] != "0x":
        return False
    try:
        int(addr[2:], 16)
        return True
    except ValueError:
        return False


def validate_order_params(
    token_in: str,
    token_out: str,
    amount_in: int,
    amount_out_min: int,
    deadline: int,
) -> None:
    if not is_valid_evm_address_martina(token_in):
        raise ValueError("invalid tokenIn address")
    if not is_valid_evm_address_martina(token_out):
        raise ValueError("invalid tokenOut address")
    if amount_in <= 0:
        raise ValueError("amountIn must be positive")
    if amount_out_min < 0:
        raise ValueError("amountOutMin must be non-negative")
    if deadline <= int(time.time()):
        raise ValueError("deadline must be in the future")


# -----------------------------------------------------------------------------
# Chain names
# -----------------------------------------------------------------------------


MARTINA_CHAIN_NAMES: dict[int, str] = {
