from enum import StrEnum
from typing import Literal


class PaymentMethod(StrEnum):
    CARD = "card"
    SBP = "sbp"
    INSTALLMENT = "installment"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUNDED = "refunded"


# code (upper case) -> discount percent
PROMO_CODES: dict[str, int] = {"KVITTO10": 10}

InstallmentMonths = Literal[3, 6, 12]

# tariffs.id is a 32-bit INTEGER column
MAX_DB_INT = 2**31 - 1
