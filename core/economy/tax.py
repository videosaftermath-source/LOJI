"""Taxes. Whatever is charged here is destroyed (leaves circulation)."""

import math


def TransferFee(amount: int, config: dict) -> int:
    """Commission the sender pays on top of a transfer (rounded up)."""
    Percent = float(config["transfer"]["fee_percent"])
    if Percent <= 0 or amount <= 0:
        return 0
    return max(1, math.ceil(amount * Percent / 100))
