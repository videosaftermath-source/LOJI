"""Taxes. Whatever is charged here is destroyed (leaves circulation)."""

import math


def TransferFee(amount: int, config: dict, discount: float = 0.0) -> int:
    """Commission the sender pays on top of a transfer (rounded up). `discount` lowers it (Ahorrador pets)."""
    Percent = float(config["transfer"]["fee_percent"]) * (1 - discount)
    if Percent <= 0 or amount <= 0:
        return 0
    return max(1, math.ceil(amount * Percent / 100))
