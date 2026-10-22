from enforced import (
    Ok,
    Err,
    InvalidDataError,
    protect,
    typecheck,
    to_json,
    dataclass,
    field,
    enforce
    )
from enforced.data_types import NegativeInt, PositiveFloat
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
    @enforce.exempt
    def withdraw(self, amount: Amount) -> Amount:
        return amount
    def subtract(self, amount: Amount) -> NegativeInt:
        return -int(amount)



@dataclass(slots = True, deep = True, check_return = True)
class Transaction:
    amount: Amount
    type: str
    rand: list[PositiveFloat] = field(default_factory = list)

    def some_method(self, val: int = 0) -> int:
        return val



async def protection_simulation():
    async def worker(raise_err: bool = False) -> str:
        match raise_err:
            case True:
                raise ValueError("An error occurred")
            case False:
                return "Hello from coroutine"
    match await protect(worker()):
        case Ok(result):
            print("Success:", result, type(result))
        case Err(error):
            print("Error:", error, type(error))
    match await protect(worker(raise_err = True)):
        case Ok(result):
            print("Success with error:", result, type(result))
        case Err(error):
            print("Error as expected:", error, type(error))



if __name__ == "__main__":
    acc = Account(3)
    print(acc.deposit(100))
    try:
        print(acc.withdraw('50'))
    except InvalidDataError as e:
        print("Caught an InvalidDataError:\n", e, type(e))
    transaction = Transaction(amount = 100, type = "deposit",) #rand = [1.23, 4.56, 7.89, 1.23, 4.56, 7.891, 4.56, 7.891, 4.56, 7.891, 4.56, 7.89,])
    transaction.some_method()
    print(transaction)
    print(greet("Alice"))
    print(acc.subtract(20))
    asyncio.run(protection_simulation())
    print(
        "Transaction as JSON:\n",
        to_json(transaction)
        )
