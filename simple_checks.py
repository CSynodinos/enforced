from enforced import (
    Ok,
    Err,
    protect,
    typecheck,
    dataclass,
    enforce,
    skip_typecheck
    )
from enforced.data_types import NegativeInt
import asyncio


@typecheck(check_return = True)
def greet(name: str) -> str:
    """Return a greeting for the given name."""
    return f"Hello, {name}"



type Amount = int | float


@enforce(check_return = True)
class Account:
    """A simple bank account class."""
    def __init__(self, balance: Amount = 0.0) -> None:
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



async def protection_simulation():
    async def worker(raise_err: bool = False) -> str:
        match raise_err:
            case True:
                raise ValueError("An error occurred")
            case False:
                return "Hello from coroutine"
    match await protect(worker()):
        case Ok(value):
            print("Success:", value)
        case Err(error):
            print("Error:", error)
    match await protect(worker(raise_err = True)):
        case Ok(value):
            print("Success with error:", value)
        case Err(error):
            print("Error as expected:", error)



if __name__ == "__main__":
    acc = Account(3)
    print(acc.deposit(100))
    print(acc.withdraw(50))
    txn = Transaction(amount = 100, type = "deposit")
    print(txn)
    print(greet("Alice"))
    print(acc.subtract(20))
    asyncio.run(protection_simulation())
