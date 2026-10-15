import abc
from typing import Sequence
from src.strategy.context import StrategyContext
from src.strategy.models import StrategyDecision


class Strategy(abc.ABC):
    """
    Universal abstract interface for user-defined trading strategies.

    Architecture & Lifecycle:
    - Strategies are evaluated sequentially bar-by-bar across completed candles.
    - Stateful: Strategies may maintain internal state across consecutive on_bar() calls.
    - Lifecycle Hooks:
      * on_start(): Called once before simulation starts. Resets state for clean replay.
      * on_bar(context): Called on each completed bar. Returns a sequence of decisions.
      * on_finish(): Called once after simulation completes.

    Return Contract:
    - on_bar() returns a Sequence of StrategyDecision objects.
    - An empty sequence (e.g., [] or ()) represents 'no action' / hold.

    Timing Contract:
    - A strategy evaluates the completed candle at index i (after its close).
    - Under baseline simulation rules, a market order request emitted at index i
      cannot fill earlier than the next eligible candle's open (index i + 1).
    - Order fills, intrabar path ambiguity, limit matching, and portfolio mutations
      are explicitly handled by the execution engine in Milestone 3.
    """

    def on_start(self) -> None:
        """
        Lifecycle hook called once before the simulation begins.
        Implementations should initialize or reset all internal state variables here.
        """
        pass

    @abc.abstractmethod
    def on_bar(self, context: StrategyContext) -> Sequence[StrategyDecision]:
        """
        Evaluates the current completed candle and context state.

        Args:
            context: StrategyContext providing read-only access to current_bar,
                     history up to current_bar, position snapshot, and account snapshot.

        Returns:
            Sequence[StrategyDecision]: Ordered collection of intended requests/actions.
                                        Return an empty sequence [] for no new requests.
        """
        pass

    def on_finish(self) -> None:
        """
        Lifecycle hook called once after the simulation sequence completes.
        Implementations may perform teardown or post-run analysis logging here.
        """
        pass
