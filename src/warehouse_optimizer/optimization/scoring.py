"""Placement cost functions used by the slotting engine.

The engine minimises a cost per (SKU, location) pair. Both cost functions are
heuristic scores: a lower score is better, but minimising the score does not
guarantee the globally optimal layout and the score itself is NOT a measured
travel distance. Real impact is evaluated separately by the route simulation.

Class-based (method A):
    cost = class_weight[class] * d + zone_penalty * |zone(location) - class|
    Locations are split into A/B/C zones by distance rank; zone sizes equal the
    number of movable SKUs in each class.

Hybrid (method B), expressed in "metre equivalents per analysis period":
    cost = w_travel  * f * 2 * d          expected travel if each line were a single trip
         + w_height  * f * z              penalty for picking from higher levels
         + w_family  * family_distance    distance to the family's current centroid
         + w_fit     * unused_volume_share
    f = order lines of the SKU in the analysis period, d = one-way dock distance.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

CLASS_INDEX = {"A": 0, "B": 1, "C": 2}


@dataclass
class ClassBasedWeights:
    class_weight_a: float = 3.0
    class_weight_b: float = 2.0
    class_weight_c: float = 1.0
    min_gain: float = 1.0  # minimum score improvement per move

    def class_weight(self, classes: np.ndarray) -> np.ndarray:
        lookup = {"A": self.class_weight_a, "B": self.class_weight_b, "C": self.class_weight_c}
        return np.array([lookup.get(c, self.class_weight_c) for c in classes], dtype=float)


@dataclass
class HybridWeights:
    w_travel: float = 1.0
    w_height: float = 0.5
    w_family: float = 0.0
    w_fit: float = 2.0
    move_cost_m: float = 30.0  # minimum expected saving (metre equivalents) that justifies one move


def zone_index(distances: np.ndarray, thresholds: tuple[float, float]) -> np.ndarray:
    d_a, d_b = thresholds
    return np.where(distances <= d_a, 0, np.where(distances <= d_b, 1, 2))


def zone_thresholds(pool_distances: np.ndarray, n_a: int, n_b: int) -> tuple[float, float]:
    ordered = np.sort(pool_distances)
    if len(ordered) == 0:
        return (np.inf, np.inf)
    d_a = ordered[min(n_a, len(ordered)) - 1] if n_a > 0 else -np.inf
    d_b = ordered[min(n_a + n_b, len(ordered)) - 1] if n_a + n_b > 0 else d_a
    return float(d_a), float(d_b)


def class_based_cost(classes: np.ndarray, distances: np.ndarray, zones: np.ndarray,
                     weights: ClassBasedWeights, zone_penalty: float) -> np.ndarray:
    """classes: (S,) ; distances, zones: broadcastable to (S, L) or (S,)."""
    cls_idx = np.array([CLASS_INDEX.get(c, 2) for c in classes])
    cw = weights.class_weight(classes)
    if np.ndim(distances) == 2:
        cls_idx, cw = cls_idx[:, None], cw[:, None]
    return cw * distances + zone_penalty * np.abs(zones - cls_idx)


def hybrid_cost(freq: np.ndarray, distances: np.ndarray, heights: np.ndarray, family_dist: np.ndarray,
                fill_share: np.ndarray, weights: HybridWeights) -> np.ndarray:
    """freq: (S,) ; other arrays broadcastable with freq[:, None] (matrix) or (S,) (diagonal)."""
    f = freq[:, None] if np.ndim(distances) == 2 else freq
    unused = np.clip(1.0 - fill_share, 0.0, 1.0)
    return (weights.w_travel * f * 2.0 * distances
            + weights.w_height * f * heights
            + weights.w_family * family_dist
            + weights.w_fit * unused)
