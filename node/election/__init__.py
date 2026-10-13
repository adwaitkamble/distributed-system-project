"""Election algorithm factory.

Lazily imports BullyElection / RingElection so this file can be imported
even before those modules exist (Phase 3).
"""

from node.election.strategy import ElectionStrategy


def create_election_strategy(algorithm: str, **kwargs) -> ElectionStrategy:
    """Instantiate the correct election strategy.

    Args:
        algorithm: "bully" or "ring"
        **kwargs:  forwarded to the strategy constructor

    Raises:
        ValueError: unknown algorithm name
    """
    if algorithm == "bully":
        from node.election.bully import BullyElection
        return BullyElection(**kwargs)
    elif algorithm == "ring":
        from node.election.ring import RingElection
        return RingElection(**kwargs)
    else:
        raise ValueError(f"Unknown election algorithm: '{algorithm}'")
