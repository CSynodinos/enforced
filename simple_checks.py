from enforced import (
    Ok,
    Err,
    InvalidDataError,
    protect,
    unwrap_protected,
    validate,
    to_json,
    dataclass,
    field,
    enforce
    )
from enforced.data_types import NegativeInt, PositiveFloat, Number
import asyncio


@validate
def greet(name: str) -> str:
    return f"Hello, {name}"


@enforce
class Account:

    def __init__(self, balance: Number = 0.0) -> None:
        self.balance = balance
        return

    def deposit(self, amount: Number) -> Number:
        return amount

    def withdraw(self, amount: Number) -> Number:
        return amount

    def subtract(self, amount: Number) -> NegativeInt:
        return -int(amount)



@dataclass(slots = True, deep = True, check_return = True)
class Transaction:
    amount: Number
    type: str
    rand: list[PositiveFloat] = field(default_factory = list)

    def some_method(self, val: int = 0) -> int:
        return val


async def protection_simulation() -> None:

    async def worker(raise_err: bool = False) -> str:
        match raise_err:
            case True:
                raise ValueError("An error occurred")
            case False:
                return "Hello from coroutine"

    #* Using protect with a coroutine that succeeds
    match await protect(worker()):
        case Ok(result):
            print("Success:", result, type(result))
        case Err(error):
            print("Error:", error, type(error))

    #* Using protect with a coroutine that raises an error
    match await protect(worker(raise_err = True)):
        case Ok(result):
            print("Success with error:", result, type(result))
        case Err(error):
            print("Error as expected:", error, type(error))

    #* Using unwrapper
    unwrap_protected(
        await protect(worker())
        )

    try:
        unwrap_protected(1)
    except Exception as e:
        print("Caught an error during unwrap_protected:", e)

    return


if __name__ == "__main__":
    acc = Account(3)
    print(f"New balance: {acc.balance}")
    print(acc.deposit(100))
    try:
        print(acc.withdraw('50'))
    except InvalidDataError as e:
        print("Caught an InvalidDataError:\n", e, type(e), "\n Context:", e.context, "\n Problems:", e.problems)
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
