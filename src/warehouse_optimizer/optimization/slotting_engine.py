"""Slotting engine: proposes an executable, constraint-respecting relocation plan.

Stock split policy (MVP): a SKU is relocated only if it has exactly one pick
location; it moves with its full quantity. SKUs held in several pick
locations, in fixed locations or in mixed (multi-SKU) locations are kept
where they are and reported.

Search: greedy improvement under a move budget. In each step the engine picks
the single best action among
    (1) move a SKU into a currently empty eligible location, or
    (2) evict the occupant of an eligible location to an empty location and
        move the SKU into the freed location (2 moves),
where "best" is the largest score reduction minus the per-move threshold.
Every SKU moves at most once, every move goes into an empty location at the
time of execution, so the plan can be executed in sequence without buffer
locations. Infeasible placements are never generated (cost = inf).

This is a heuristic. It returns a *proposed* layout, not a proven optimum.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .constraints import CONSTRAINT_LABELS, check_placement, constraint_matrices
from .scoring import (ClassBasedWeights, HybridWeights, class_based_cost, hybrid_cost, zone_index,
                      zone_thresholds)

METHOD_LABELS = {"class_based": "Yöntem A — Sınıf tabanlı (class-based)",
                 "hybrid": "Yöntem B — Hibrit"}

NOT_MOVABLE_REASONS = {
    "no_pick_location": "Toplama lokasyonunda stoğu yok",
    "multi_location": "Birden fazla toplama lokasyonunda (stok bölme politikası: taşınmaz)",
    "fixed": "Sabit lokasyonda",
    "mixed": "Karışık (çok SKU'lu) lokasyonda",
    "unreachable": "Mevcut lokasyonuna rota ağı üzerinden ulaşılamıyor",
}


@dataclass
class SlottingConfig:
    method: str = "hybrid"
    max_moves: int = 30
    class_based: ClassBasedWeights = field(default_factory=ClassBasedWeights)
    hybrid: HybridWeights = field(default_factory=HybridWeights)
    handling_compatibility: dict | None = None


@dataclass
class SlottingResult:
    method: str
    moves: pd.DataFrame
    placement_current: dict[str, list[str]]
    placement_proposed: dict[str, list[str]]
    not_movable: pd.DataFrame
    unassignable: pd.DataFrame
    pool_size: int
    movable_count: int
    notes: list[str] = field(default_factory=list)

    @property
    def move_count(self) -> int:
        return len(self.moves)

    @property
    def moved_sku_count(self) -> int:
        return int(self.moves["sku"].nunique()) if not self.moves.empty else 0


MOVE_COLUMNS = ["sequence", "group", "sku", "from_location", "to_location", "move_type", "score_gain",
                "group_score_gain", "reason"]


def current_pick_placement(inventory: pd.DataFrame, locations: pd.DataFrame) -> dict[str, list[str]]:
    """SKU -> sorted list of pickable locations holding it."""
    pickable = set(locations.loc[locations["is_pickable"], "location_id"])
    inv = inventory[inventory["location_id"].isin(pickable)]
    return {sku: sorted(group["location_id"]) for sku, group in inv.groupby("sku")}


def _family_distance(skus: pd.DataFrame, cur_xy: np.ndarray, pool_xy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Manhattan distance to the family centroid (current placement); 0 for families of size 1."""
    fam = skus["product_family"].fillna("").to_numpy()
    centroids = {}
    for f in np.unique(fam):
        members = fam == f
        if f == "" or members.sum() < 2:
            continue
        centroids[f] = cur_xy[members].mean(axis=0)
    matrix = np.zeros((len(skus), len(pool_xy)))
    diag = np.zeros(len(skus))
    for i, f in enumerate(fam):
        if f in centroids:
            c = centroids[f]
            matrix[i] = np.abs(pool_xy[:, 0] - c[0]) + np.abs(pool_xy[:, 1] - c[1])
            diag[i] = abs(cur_xy[i, 0] - c[0]) + abs(cur_xy[i, 1] - c[1])
    return matrix, diag


def run_slotting(products: pd.DataFrame, locations: pd.DataFrame, inventory: pd.DataFrame,
                 abc_table: pd.DataFrame, config: SlottingConfig) -> SlottingResult:
    """`locations` must carry a `dock_distance_m` column (NaN = unreachable)."""
    if config.method not in METHOD_LABELS:
        raise ValueError(f"Bilinmeyen yöntem: {config.method}")
    locs = locations.set_index("location_id", drop=False).rename_axis(None)
    placement = current_pick_placement(inventory, locations)
    skus_per_location = inventory.groupby("location_id")["sku"].nunique()
    mixed_locations = set(skus_per_location[skus_per_location > 1].index)
    fixed_locations = set(locs.index[locs["is_fixed"]])
    qty_by_pair = inventory.set_index(["sku", "location_id"])["current_quantity"]

    # --- movable SKUs -------------------------------------------------------
    not_movable = []
    movable = []
    for sku in sorted(products["sku"]):
        locs_of = placement.get(sku, [])
        if not locs_of:
            reason = "no_pick_location"
        elif len(locs_of) > 1:
            reason = "multi_location"
        elif locs_of[0] in fixed_locations:
            reason = "fixed"
        elif locs_of[0] in mixed_locations:
            reason = "mixed"
        elif np.isnan(locs.at[locs_of[0], "dock_distance_m"]):
            reason = "unreachable"
        else:
            movable.append(sku)
            continue
        not_movable.append({"sku": sku, "current_locations": ", ".join(locs_of), "reason_code": reason,
                            "reason": NOT_MOVABLE_REASONS[reason]})
    not_movable_df = pd.DataFrame(not_movable, columns=["sku", "current_locations", "reason_code", "reason"])

    # --- eligible pool --------------------------------------------------------
    occupied = set(inventory["location_id"])
    movable_locations = {placement[s][0] for s in movable}
    capacity_cols = ["max_weight_kg", "max_volume_m3", "max_length_m", "max_width_m", "max_height_m"]
    eligible = (locs["is_available"] & locs["is_pickable"] & ~locs["is_fixed"]
                & locs[capacity_cols].notna().all(axis=1) & locs["dock_distance_m"].notna()
                & (~locs.index.isin(occupied) | locs.index.isin(movable_locations))
                & ~locs.index.isin(mixed_locations))
    pool = locs[eligible].sort_values("location_id")
    notes = []

    prod = products.set_index("sku").loc[movable].reset_index() if movable else products.iloc[0:0]
    abc = abc_table.set_index("sku")
    classes = np.array([abc.at[s, "abc_class"] if s in abc.index else "C" for s in movable])
    freq = np.array([float(abc.at[s, "order_lines"]) if s in abc.index else 0.0 for s in movable])
    qty = np.array([float(qty_by_pair[(s, placement[s][0])]) for s in movable])
    cur_loc = [placement[s][0] for s in movable]

    S, L = len(movable), len(pool)
    empty_moves = pd.DataFrame(columns=MOVE_COLUMNS)
    proposed = {k: list(v) for k, v in placement.items()}
    if S == 0 or L == 0:
        notes.append("Taşınabilir SKU veya uygun hedef lokasyon yok; öneri üretilmedi.")
        return SlottingResult(config.method, empty_moves, placement, proposed, not_movable_df,
                              pd.DataFrame(columns=["sku", "abc_class", "reason"]), L, S, notes)

    mats = constraint_matrices(prod, qty, pool, config.handling_compatibility)
    violated = np.zeros((S, L), dtype=bool)
    for m in mats.values():
        violated |= m
    feasible = ~violated

    pool_ids = pool["location_id"].to_numpy()
    pool_index = {loc: j for j, loc in enumerate(pool_ids)}
    pool_dist = pool["dock_distance_m"].to_numpy(float)
    cur_rows = locs.loc[cur_loc]
    cur_dist = cur_rows["dock_distance_m"].to_numpy(float)

    if config.method == "class_based":
        w = config.class_based
        n_a, n_b = int((classes == "A").sum()), int((classes == "B").sum())
        thresholds = zone_thresholds(pool_dist, n_a, n_b)
        zone_penalty = 10.0 * max(float(np.nanmax(pool_dist)), 1.0) * max(w.class_weight_a, 1.0)
        cost = class_based_cost(classes, pool_dist[None, :], zone_index(pool_dist, thresholds)[None, :],
                                w, zone_penalty)
        cur_cost = class_based_cost(classes, cur_dist, zone_index(cur_dist, thresholds), w, zone_penalty)
        threshold = w.min_gain
        zone_names = np.array(["A", "B", "C"])
        pool_zone = zone_names[zone_index(pool_dist, thresholds)]
        cur_zone = zone_names[zone_index(cur_dist, thresholds)]
    else:
        w = config.hybrid
        pool_z = pool["z"].fillna(0).to_numpy(float)
        cur_z = cur_rows["z"].fillna(0).to_numpy(float)
        vol = prod["length_m"].to_numpy(float) * prod["width_m"].to_numpy(float) * prod["height_m"].to_numpy(float)
        load = qty * vol
        pool_fill = load[:, None] / pool["max_volume_m3"].to_numpy(float)[None, :]
        cur_vol = cur_rows["max_volume_m3"].to_numpy(float)
        cur_fill = np.where(np.isnan(cur_vol), 1.0, load / np.where(np.isnan(cur_vol), 1.0, cur_vol))
        fam_matrix, fam_diag = _family_distance(prod, cur_rows[["x", "y"]].to_numpy(float),
                                                pool[["x", "y"]].to_numpy(float))
        cost = hybrid_cost(freq, pool_dist[None, :], pool_z[None, :], fam_matrix, pool_fill, w)
        cur_cost = hybrid_cost(freq, cur_dist, cur_z, fam_diag, cur_fill, w)
        threshold = w.move_cost_m
        pool_zone = cur_zone = None

    cost = np.where(feasible, cost, np.inf)

    occupant = np.full(L, -1)
    for i, loc in enumerate(cur_loc):
        if loc in pool_index:
            occupant[pool_index[loc]] = i
    moved = np.zeros(S, dtype=bool)
    budget = max(int(config.max_moves), 0)
    moves: list[dict] = []
    group = 0

    while budget > 0:
        free = occupant == -1
        if not free.any():
            free_cost = np.full(S, np.inf)
            free_arg = np.zeros(S, dtype=int)
        else:
            masked = np.where(free[None, :], cost, np.inf)
            free_arg = masked.argmin(axis=1)
            free_cost = masked[np.arange(S), free_arg]
        gain1 = np.where(moved | np.isinf(free_cost), -np.inf, cur_cost - free_cost - threshold)
        best1 = int(np.argmax(gain1))
        best_gain = gain1[best1]
        action = ("move", best1, int(free_arg[best1])) if np.isfinite(best_gain) else None

        if budget >= 2:
            occ_valid = (occupant >= 0)
            occ_idx = np.where(occ_valid, occupant, 0)
            evict_gain = np.where(occ_valid & ~moved[occ_idx] & np.isfinite(free_cost[occ_idx]),
                                  cur_cost[occ_idx] - free_cost[occ_idx] - threshold, -np.inf)
            g2 = cur_cost[:, None] - cost - threshold + evict_gain[None, :]
            g2 = np.where(moved[:, None] | (occ_idx[None, :] == np.arange(S)[:, None]) | ~occ_valid[None, :],
                          -np.inf, g2)
            flat = int(np.argmax(g2))
            s2, t2 = divmod(flat, L)
            if np.isfinite(g2[s2, t2]) and g2[s2, t2] > best_gain + 1e-9:
                best_gain = g2[s2, t2]
                o = int(occupant[t2])
                action = ("swap", s2, t2, o, int(free_arg[o]))

        if action is None or not np.isfinite(best_gain) or best_gain <= 1e-9:
            break

        group += 1
        if action[0] == "move":
            _, s, t = action
            moves.append(_move_row(len(moves) + 1, group, movable[s], cur_loc[s], pool_ids[t], "move",
                                   cur_cost[s] - cost[s, t], best_gain, s, t, classes, freq, cur_dist, pool_dist,
                                   config.method, pool_zone, cur_zone, None))
            if cur_loc[s] in pool_index:
                occupant[pool_index[cur_loc[s]]] = -1
            occupant[t] = s
            moved[s] = True
            budget -= 1
        else:
            _, s, t, o, u = action
            moves.append(_move_row(len(moves) + 1, group, movable[o], cur_loc[o], pool_ids[u], "evict",
                                   cur_cost[o] - cost[o, u], best_gain, o, u, classes, freq, cur_dist, pool_dist,
                                   config.method, pool_zone, cur_zone, movable[s]))
            occupant[u] = o
            moved[o] = True
            moves.append(_move_row(len(moves) + 1, group, movable[s], cur_loc[s], pool_ids[t], "move",
                                   cur_cost[s] - cost[s, t], best_gain, s, t, classes, freq, cur_dist, pool_dist,
                                   config.method, pool_zone, cur_zone, None))
            if cur_loc[s] in pool_index:
                occupant[pool_index[cur_loc[s]]] = -1
            occupant[t] = s
            moved[s] = True
            budget -= 2

    moves_df = pd.DataFrame(moves, columns=MOVE_COLUMNS + ["_s", "_t"]).drop(columns=["_s", "_t"]) if moves \
        else empty_moves
    for row in moves:
        proposed[row["sku"]] = [row["to_location"]]

    # --- SKUs without any feasible target -------------------------------------
    unassignable = []
    own_slot = np.zeros((S, L), dtype=bool)
    for i, loc in enumerate(cur_loc):
        if loc in pool_index:
            own_slot[i, pool_index[loc]] = True
    no_target = ~(feasible & ~own_slot).any(axis=1)
    for i in np.where(no_target)[0]:
        counts = {code: int((m[i] & ~own_slot[i]).sum()) for code, m in mats.items()}
        dominant = max(counts, key=lambda c: (counts[c], c))
        unassignable.append({"sku": movable[i], "abc_class": classes[i],
                             "reason": f"Uygun hedef lokasyon bulunamadı (en sık engel: {CONSTRAINT_LABELS[dominant]}, "
                                       f"{counts[dominant]}/{L - int(own_slot[i].sum())} lokasyon)"})
    unassignable_df = pd.DataFrame(unassignable, columns=["sku", "abc_class", "reason"])
    if budget == 0 and moves:
        notes.append("Maksimum taşıma sayısına ulaşıldı; ek iyileştirmeler mümkün olabilir.")

    return SlottingResult(config.method, moves_df, placement, proposed, not_movable_df, unassignable_df,
                          L, S, notes)


def _move_row(seq, group, sku, src, dst, move_type, gain, group_gain, s, t, classes, freq, cur_dist, pool_dist,
              method, pool_zone, cur_zone, evicted_for) -> dict:
    delta = cur_dist[s] - pool_dist[t]
    cls = classes[s]
    direction = "daha yakın" if delta >= 0 else "daha uzak"
    if method == "class_based":
        reason = f"{cls} sınıfı ürün {cur_zone[s]} bölgesinden {pool_zone[t]} bölgesine; sevkiyata {abs(delta):.1f} m {direction}"
    else:
        reason = f"{cls} sınıfı, dönemde {int(freq[s])} sipariş satırı; sevkiyata {abs(delta):.1f} m {direction}"
    if move_type == "evict":
        reason = f"Yer açma ({src} → {evicted_for} için boşaltılıyor). " + reason
    return {"sequence": seq, "group": group, "sku": sku, "from_location": src, "to_location": dst,
            "move_type": move_type, "score_gain": float(gain), "group_score_gain": float(group_gain),
            "reason": reason, "_s": s, "_t": t}


def verify_moves(moves: pd.DataFrame, products: pd.DataFrame, locations: pd.DataFrame, inventory: pd.DataFrame,
                 handling_compatibility: dict | None = None) -> pd.DataFrame:
    """Re-check every move independently and simulate the sequence (target must be empty when used)."""
    out = moves.copy()
    if out.empty:
        out["constraint_check"] = pd.Series(dtype=str)
        return out
    prod = products.set_index("sku")
    locs = locations.set_index("location_id")
    qty = inventory.set_index(["sku", "location_id"])["current_quantity"]
    occupied = set(inventory["location_id"])
    results = []
    for _, row in out.iterrows():
        problems = check_placement(prod.loc[row["sku"]].copy(), locs.loc[row["to_location"]].copy(),
                                   float(qty[(row["sku"], row["from_location"])]), handling_compatibility)
        loc = locs.loc[row["to_location"]]
        if not bool(loc["is_pickable"]):
            problems.append("not_pickable")
        if bool(loc["is_fixed"]):
            problems.append("fixed")
        if row["to_location"] in occupied:
            problems.append("occupied")
        occupied.discard(row["from_location"])
        occupied.add(row["to_location"])
        results.append("Geçti" if not problems else "İhlal: " + ", ".join(problems))
    out["constraint_check"] = results
    return out
