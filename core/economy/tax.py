"""Taxes. Whatever is charged here is destroyed (leaves circulation)."""

import math

DEFAULT_BRACKETS = [[0, 5.0], [1_000, 8.0], [10_000, 12.0], [50_000, 15.0]]


def Brackets(config: dict) -> list[list[float]]:
    """[[from, percent], ...] sorted, always starting at 0."""
    Rows = sorted(config["transfer"].get("brackets") or DEFAULT_BRACKETS, key=lambda R: R[0])
    if Rows[0][0] != 0:
        Rows = [[0, 0.0]] + Rows
    return Rows


def BracketTax(amount: int, config: dict) -> float:
    """Progressive tax: each slice of the amount pays its own bracket's rate (no jumps at the limits)."""
    Rows = Brackets(config)
    Tax = 0.0
    for i, (Start, Percent) in enumerate(Rows):
        End = Rows[i + 1][0] if i + 1 < len(Rows) else math.inf
        if amount <= Start:
            break
        Tax += (min(amount, End) - Start) * Percent / 100
    return Tax


def TransferFee(amount: int, config: dict, discount: float = 0.0) -> int:
    """Tax the sender pays on top of a transfer (rounded up). `discount` lowers it (Ahorrador pets)."""
    if amount <= 0:
        return 0
    Tax = BracketTax(amount, config) * (1 - discount)
    return math.ceil(Tax - 1e-9) if Tax > 0 else 0


def EffectiveRate(amount: int, config: dict, discount: float = 0.0) -> float:
    return TransferFee(amount, config, discount) / amount if amount else 0.0


def FormatBrackets(rows) -> str:
    return ", ".join(f"{int(Start)}:{Percent:g}" for Start, Percent in rows)


def ParseBrackets(text: str) -> list[list[float]]:
    """'0:5, 1000:8, 10000:12' -> [[0, 5.0], [1000, 8.0], [10000, 12.0]]. Raises ValueError."""
    Rows = []
    for Part in text.replace(";", ",").split(","):
        if not Part.strip():
            continue
        if ":" not in Part:
            raise ValueError(f"`{Part.strip()}` no tiene el formato `desde:porcentaje`.")
        Start, Percent = Part.split(":", 1)
        Start = Start.strip().replace(".", "")
        if not Start.isdigit():
            raise ValueError(f"`{Start}` no es una cantidad válida.")
        try:
            Value = float(Percent.strip().replace(",", ".").rstrip("%"))
        except ValueError:
            raise ValueError(f"`{Percent.strip()}` no es un porcentaje válido.")
        if not 0 <= Value <= 50:
            raise ValueError("Cada porcentaje tiene que estar entre 0 y 50.")
        Rows.append([int(Start), Value])
    if not Rows:
        raise ValueError("Pon al menos un tramo, ej. `0:5`.")
    Rows.sort(key=lambda R: R[0])
    if Rows[0][0] != 0:
        raise ValueError("El primer tramo tiene que empezar en 0.")
    if len({R[0] for R in Rows}) != len(Rows):
        raise ValueError("Hay dos tramos que empiezan en la misma cantidad.")
    return Rows
