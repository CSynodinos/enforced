from pyvalidate import (
    typecheck,
    dataclass,
    enforced,
    skip_typecheck
    )
from pyvalidate.data_types import NegativeInt


@typecheck(check_return = True)
def greet(name: str) -> str:
    """Return a greeting for the given name."""
    return f"Hello, {name}"



type Amount = int | float


@enforced(check_return = True)
class Account:
    """A simple bank account class."""
    def __init__(self, balance: Amount = "0.0") -> None:
        self.balance = balance
    def deposit(self, amount: Amount) -> Amount:
        return amount
    @skip_typecheck
    def withdraw(self, amount: Amount) -> Amount:
        return amount
    def subtract(self, amount: Amount) -> NegativeInt:
        return -int(amount)



@dataclass
class Transaction:
    amount: Amount
    type: str


if __name__ == "__main__":
    acc = Account(3)
    print(acc.deposit(100))
    print(acc.withdraw(50))
    txn = Transaction(amount = 100, type = "deposit")
    print(txn)
    print(greet("Alice"))
    print(acc.subtract(-20))
