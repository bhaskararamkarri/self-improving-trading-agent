"""Compatibility layer for pandas DataFrame and Series with pure-Python fallback."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Union


class Series(list):
    """Pure-Python fallback for pandas Series."""

    def __init__(self, data: Optional[List[Any]] = None, index: Optional[List[Any]] = None):
        data_list = list(data) if data is not None else []
        super().__init__(data_list)
        self.index = index if index is not None else list(range(len(data_list)))

    def astype(self, dtype: Any) -> Series:
        return Series([dtype(x) if x is not None else x for x in self], self.index)

    def diff(self, n: int = 1) -> Series:
        res = [None] * n + [
            self[i] - self[i - n] if self[i] is not None and self[i - n] is not None else None
            for i in range(n, len(self))
        ]
        return Series(res, self.index)

    def shift(self, n: int = 1) -> Series:
        res = [None] * n + [self[i - n] for i in range(n, len(self))]
        return Series(res, self.index)

    def abs(self) -> Series:
        return Series([abs(x) if x is not None else None for x in self], self.index)

    def fillna(self, val: Any) -> Series:
        return Series([val if x is None else x for x in self], self.index)

    def where(self, cond: List[bool], other: Any = 0.0) -> Series:
        return Series([self[i] if cond[i] else other for i in range(len(self))], self.index)

    def ewm(self, span: int, adjust: bool = False) -> Any:
        alpha = 2.0 / (span + 1.0)

        class EWM:
            def __init__(self, s: Series, a: float):
                self.s = s
                self.a = a

            def mean(self) -> Series:
                res = []
                ema = None
                for x in self.s:
                    if x is None:
                        res.append(None)
                    elif ema is None:
                        ema = float(x)
                        res.append(ema)
                    else:
                        ema = self.a * float(x) + (1.0 - self.a) * ema
                        res.append(ema)
                return Series(res, self.s.index)

        return EWM(self, alpha)

    def rolling(self, window: int, min_periods: int = 1) -> Any:
        class Rolling:
            def __init__(self, s: Series, w: int, mp: int):
                self.s = s
                self.w = w
                self.mp = mp

            def mean(self) -> Series:
                res = []
                for i in range(len(self.s)):
                    start = max(0, i - self.w + 1)
                    sub = [x for x in self.s[start : i + 1] if x is not None]
                    if len(sub) >= self.mp and sub:
                        res.append(sum(sub) / len(sub))
                    else:
                        res.append(None)
                return Series(res, self.s.index)

            def std(self) -> Series:
                res = []
                for i in range(len(self.s)):
                    start = max(0, i - self.w + 1)
                    sub = [x for x in self.s[start : i + 1] if x is not None]
                    if len(sub) > 1:
                        m = sum(sub) / len(sub)
                        variance = sum((x - m) ** 2 for x in sub) / (len(sub) - 1)
                        res.append(math.sqrt(variance))
                    else:
                        res.append(0.0)
                return Series(res, self.s.index)

        return Rolling(self, window, min_periods)

    def __sub__(self, other: Any) -> Series:
        if isinstance(other, (int, float)):
            return Series([x - other if x is not None else None for x in self], self.index)
        return Series(
            [self[i] - other[i] if self[i] is not None and other[i] is not None else None for i in range(len(self))],
            self.index,
        )

    def __rsub__(self, other: Any) -> Series:
        return Series([other - x if x is not None else None for x in self], self.index)

    def __add__(self, other: Any) -> Series:
        if isinstance(other, (int, float)):
            return Series([x + other if x is not None else None for x in self], self.index)
        return Series(
            [self[i] + other[i] if self[i] is not None and other[i] is not None else None for i in range(len(self))],
            self.index,
        )

    def __mul__(self, other: Any) -> Series:
        if isinstance(other, (int, float)):
            return Series([x * other if x is not None else None for x in self], self.index)
        return Series(
            [self[i] * other[i] if self[i] is not None and other[i] is not None else None for i in range(len(self))],
            self.index,
        )

    def __truediv__(self, other: Any) -> Series:
        if isinstance(other, (int, float)):
            return Series([x / other if x is not None and other != 0 else 0.0 for x in self], self.index)
        return Series(
            [self[i] / other[i] if self[i] is not None and other[i] not in (None, 0) else 0.0 for i in range(len(self))],
            self.index,
        )

    def __neg__(self) -> Series:
        return Series([-x if x is not None else None for x in self], self.index)

    def __gt__(self, other: Any) -> List[bool]:
        if isinstance(other, (int, float)):
            return [x > other if x is not None else False for x in self]
        return [self[i] > other[i] if self[i] is not None and other[i] is not None else False for i in range(len(self))]

    def __lt__(self, other: Any) -> List[bool]:
        if isinstance(other, (int, float)):
            return [x < other if x is not None else False for x in self]
        return [self[i] < other[i] if self[i] is not None and other[i] is not None else False for i in range(len(self))]


class RowDict(dict):
    """Dictionary representing a single DataFrame row."""

    def __getitem__(self, key: str) -> Any:
        col_map = {k.lower(): k for k in self.keys()}
        if key in self:
            return super().__getitem__(key)
        if key.lower() in col_map:
            return super().__getitem__(col_map[key.lower()])
        return super().__getitem__(key)

    def get(self, key: str, default: Any = None) -> Any:
        col_map = {k.lower(): k for k in self.keys()}
        if key in self:
            return super().get(key, default)
        if key.lower() in col_map:
            return super().get(col_map[key.lower()], default)
        return default


class ILocIndexer:
    def __init__(self, df: DataFrame):
        self.df = df

    def __getitem__(self, idx: Union[int, slice]) -> Union[RowDict, DataFrame]:
        if isinstance(idx, int):
            row_idx = idx if idx >= 0 else len(self.df) + idx
            row_dict = {col: self.df._data[col][row_idx] for col in self.df._columns}
            return RowDict(row_dict)
        elif isinstance(idx, slice):
            start, stop, step = idx.indices(len(self.df))
            new_data = {col: self.df._data[col][start:stop:step] for col in self.df._columns}
            return DataFrame(new_data)
        raise TypeError(f"Invalid iloc indexer: {idx}")


class DataFrame:
    """Lightweight pure-Python fallback for pandas DataFrame."""

    def __init__(self, data: Optional[Union[Dict[str, List[Any]], List[Dict[str, Any]]]] = None):
        self._columns: List[str] = []
        self._data: Dict[str, List[Any]] = {}

        if data is not None:
            if isinstance(data, dict):
                self._columns = list(data.keys())
                self._data = {k: list(v) for k, v in data.items()}
            elif isinstance(data, list):
                if data:
                    self._columns = list(data[0].keys())
                    for col in self._columns:
                        self._data[col] = [row.get(col) for row in data]
        self.iloc = ILocIndexer(self)

    @property
    def columns(self) -> List[str]:
        return list(self._columns)

    @property
    def empty(self) -> bool:
        return len(self) == 0

    def __len__(self) -> int:
        if not self._columns or not self._data:
            return 0
        return len(self._data[self._columns[0]])

    def __getitem__(self, key: str) -> Series:
        col_map = {c.lower(): c for c in self._columns}
        actual_col = key if key in self._data else col_map.get(key.lower(), key)
        if actual_col not in self._data:
            raise KeyError(f"Column '{key}' not found in DataFrame ({self._columns})")
        return Series(self._data[actual_col])

    def __setitem__(self, key: str, value: Any) -> None:
        if key not in self._columns:
            self._columns.append(key)
        if isinstance(value, Series):
            self._data[key] = list(value)
        elif isinstance(value, list):
            self._data[key] = list(value)
        elif hasattr(value, "__iter__") and not isinstance(value, (str, bytes)):
            self._data[key] = list(value)
        else:
            self._data[key] = [value] * len(self)

    def copy(self) -> DataFrame:
        return DataFrame({k: list(v) for k, v in self._data.items()})

    def reset_index(self) -> DataFrame:
        return self.copy()

    def rename(self, columns: Dict[str, str], inplace: bool = True) -> DataFrame:
        new_data = {}
        new_cols = []
        for c in self._columns:
            target = columns.get(c, c)
            new_cols.append(target)
            new_data[target] = self._data[c]
        if inplace:
            self._columns = new_cols
            self._data = new_data
            return self
        return DataFrame(new_data)

    def to_dict(self, orient: str = "records") -> Any:
        res = []
        for i in range(len(self)):
            row = {col: self._data[col][i] for col in self._columns}
            res.append(row)
        return res


# Global module shim
class PandasShim:
    DataFrame = DataFrame
    Series = Series

    @staticmethod
    def isna(val: Any) -> bool:
        return val is None or (isinstance(val, float) and math.isnan(val))

    @staticmethod
    def concat(objs: List[Any], axis: int = 0) -> Any:
        if axis == 1:
            # Column-wise max or concatenation
            length = len(objs[0])
            res = []
            for i in range(length):
                row_vals = [obj[i] for obj in objs if obj[i] is not None]
                res.append(max(row_vals) if row_vals else 0.0)
            return Series(res)
        return objs[0]
