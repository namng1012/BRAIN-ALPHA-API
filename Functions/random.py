"""Integer and float samplers for reproducible random FASTEXPR parameter generation.

Both samplers support uniform and balanced distributions, with entropy-stream
isolation so parameter draws are independent when seeded. The balanced distribution
splits ranges into quintile buckets following 252-trading-day proportions.
"""

import itertools
import os
from typing import Literal

import numpy as np


class IntegerSampler:
    """Draws integers from an inclusive range, uniformly or in balanced buckets.

    The balanced distribution splits the range into five buckets cut at fixed
    *fractions* of the range rather than at fixed day counts: the range size is
    not fixed (a rolling window may be 252 days, a lag may be 5), so the cut
    points scale with it.

    The fractions are the quintiles of a 252-trading-day year, so a 252-day
    window splits into 1-5, 6-22, 23-66, 67-126 and 127-252. Any other range
    keeps the same proportions.
    """

    # The cut points of the five buckets, as fractions of the range size.
    BUCKET_FRACTIONS = (5 / 252, 22 / 252, 66 / 252, 126 / 252)

    # The number of buckets a balanced draw splits the range into.
    BUCKET_COUNT = len(BUCKET_FRACTIONS) + 1

    @classmethod
    def buckets(cls, min_value: int, max_value: int) -> list[tuple[int, int]]:
        """Partition an inclusive integer range into five nonempty buckets.

        The cuts are the range's quintiles: a 252-value range splits into
        1-5, 6-22, 23-66, 67-126 and 127-252, and a smaller range keeps the same
        proportions.
        """
        count = max_value - min_value + 1
        if count < cls.BUCKET_COUNT:
            # Too few integers to split: each bucket is a single value.
            return [(value, value) for value in range(min_value, max_value + 1)]

        # Bucket boundaries are end-exclusive offsets from min_value.
        cuts = [0]
        for index, fraction in enumerate(cls.BUCKET_FRACTIONS, start=1):
            scaled_cut = round(count * fraction)
            # Every bucket must hold at least one integer, so a cut may not fall
            # below the previous one nor above the room left for the later buckets.
            lower_bound = cuts[-1] + 1
            upper_bound = count - (cls.BUCKET_COUNT - index)
            cuts.append(max(lower_bound, min(scaled_cut, upper_bound)))
        cuts.append(count)

        return [
            (min_value + left, min_value + right - 1)
            for left, right in itertools.pairwise(cuts)
        ]

    @classmethod
    def sample(
        cls,
        value_range: tuple[int, int],
        seed: int | None = None,
        stream: int = 0,
        *,
        distribution: Literal["uniform", "balanced"] = "uniform",
    ) -> int:
        """Draw one integer from the inclusive range `value_range`.

        `distribution="uniform"` (default): every integer is equally likely.

        `distribution="balanced"`: one of the five buckets is drawn uniformly,
        then an integer inside that bucket is drawn uniformly. The buckets are the
        range's quintiles, so a 252-value range splits into 1-5, 6-22, 23-66,
        67-126 and 127-252, each with probability 20%. Every integer stays
        possible, but the probability of any single integer is not equal across
        the range.

        `seed=None` draws fresh entropy from the OS CSPRNG, so the draw is not
        anchored to any fixed constant.

        `stream` picks the entropy sub-stream: draws that share a seed but sit on
        different streams are independent, so adding a new draw for another
        category never shifts the value an existing draw produces. The same seed
        and stream replay the same integer bit-exact.
        """
        min_value, max_value = value_range
        if min_value > max_value:
            raise ValueError("value_range must be an inclusive (min, max) pair")
        if distribution not in ("uniform", "balanced"):
            raise ValueError("distribution must be 'uniform' or 'balanced'")

        if seed is None:
            seed = int.from_bytes(os.urandom(8), "big")
        rng = np.random.default_rng([seed, stream])

        if distribution == "uniform":
            return int(rng.integers(min_value, max_value + 1))

        buckets = cls.buckets(min_value, max_value)
        bucket = buckets[int(rng.integers(0, len(buckets)))]
        return int(rng.integers(bucket[0], bucket[1] + 1))


class FloatSampler:
    """Draws floats from an inclusive range, uniformly or in balanced buckets.

    The float counterpart of `IntegerSampler`: same bucket fractions, same
    entropy-stream discipline, same replay guarantee. The differences are that
    the range is continuous, and that the drawn value is rounded to a fixed
    number of decimals so the rendered FASTEXPR is stable.

    The buckets are cut at the same *fractions* of the range size, so a
    balanced draw gives each fifth of the range the same probability whatever
    the range is.
    """

    # The cut points of the five buckets, as fractions of the range size.
    BUCKET_FRACTIONS = IntegerSampler.BUCKET_FRACTIONS

    # The number of buckets a balanced draw splits the range into.
    BUCKET_COUNT = IntegerSampler.BUCKET_COUNT

    # The range a draw covers when the caller names none: the float arguments
    # the platform takes are scale factors and thresholds, all of them inside
    # 0..3.
    RANGE = (0.0, 3.0)

    # The number of decimals a drawn float is rounded to before it is returned.
    DECIMALS = 4

    @classmethod
    def buckets(cls, min_value: float, max_value: float) -> list[tuple[float, float]]:
        """Partition an inclusive float range into five nonempty buckets.

        The cuts are the range's quintiles, the same fractions
        `IntegerSampler` uses, so a float range and an integer range over the
        same span are bucketed alike.
        """
        count = max_value - min_value
        if count <= 0:
            return [(min_value, max_value)]

        # Bucket boundaries are fractions of the range, end-exclusive on the
        # left and inclusive on the right.
        cuts = [0.0]
        for index, fraction in enumerate(cls.BUCKET_FRACTIONS, start=1):
            scaled_cut = count * fraction
            # Every bucket must hold a positive span, so a cut may not fall
            # below the previous one nor above the room left for the later
            # buckets.
            lower_bound = cuts[-1]
            upper_bound = count * (1 - (cls.BUCKET_COUNT - index) / cls.BUCKET_COUNT)
            cuts.append(max(lower_bound, min(scaled_cut, upper_bound)))
        cuts.append(count)

        return [
            (min_value + left, min_value + right)
            for left, right in itertools.pairwise(cuts)
        ]

    @classmethod
    def sample(
        cls,
        value_range: tuple[float, float] | None = None,
        seed: int | None = None,
        stream: int = 0,
        *,
        distribution: Literal["uniform", "balanced"] = "balanced",
    ) -> float:
        """Draw one float from the inclusive range `value_range`.

        `value_range` defaults to `RANGE`, the 0..3 span the platform's float
        arguments live in.

        `distribution="uniform"` (default): every point of the range is equally
        likely.

        `distribution="balanced"`: one of the five buckets is drawn uniformly,
        then a point inside that bucket is drawn uniformly. Each bucket covers
        a fifth of the range, so each carries the same probability.

        The returned value is rounded to `DECIMALS` decimals, so the same seed
        always renders the same FASTEXPR text.

        `seed=None` draws fresh entropy from the OS CSPRNG, so the draw is not
        anchored to any fixed constant.

        `stream` picks the entropy sub-stream: draws that share a seed but sit on
        different streams are independent, so adding a new draw for another
        category never shifts the value an existing draw produces. The same seed
        and stream replay the same float bit-exact.
        """
        if value_range is None:
            value_range = cls.RANGE
        min_value, max_value = value_range
        if min_value > max_value:
            raise ValueError("value_range must be an inclusive (min, max) pair")
        if distribution not in ("uniform", "balanced"):
            raise ValueError("distribution must be 'uniform' or 'balanced'")

        if seed is None:
            seed = int.from_bytes(os.urandom(8), "big")
        rng = np.random.default_rng([seed, stream])

        if distribution == "uniform":
            value = float(rng.uniform(min_value, max_value))
        else:
            buckets = cls.buckets(min_value, max_value)
            bucket = buckets[int(rng.integers(0, len(buckets)))]
            value = float(rng.uniform(bucket[0], bucket[1]))

        return round(value, cls.DECIMALS)
