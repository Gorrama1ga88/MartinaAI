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
