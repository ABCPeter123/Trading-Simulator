# Research interoperability

The simulator uses Python for orchestration, NumPy for signal calculations,
Polars to store and normalize provider-supplied OHLCV candles, and DuckDB to
query local Parquet datasets. The default on-disk archive is:

```text
data/market/<instrument_id>/<range>.parquet
```

The first successful request for `/api/market/aapl?range=1Y` generates
`data/market/aapl/1Y.parquet` (if the provider is reachable).
The endpoint `/api/archive/aapl?range=1Y` reports archived bar counts and
price ranges. These are provider candles, not executable Level II order quotes.

## Python + DuckDB

```python
import duckdb

result = duckdb.sql("""
  SELECT time, close, volume
  FROM read_parquet('data/market/aapl/1Y.parquet')
  ORDER BY time
""").df()
print(result.tail())
```

## Python + Polars lazy

```python
import polars as pl

prices = (
    pl.scan_parquet("data/market/aapl/1Y.parquet")
    .sort("time")
    .with_columns(pl.col("close").rolling_mean(window_size=20).alias("sma20"))
    .collect()
)
print(prices.tail())
```

## Optional R workflow

R is useful for econometrics, statistical tests, and reports. It is **not**
used on the execution hot path. If R is installed, the same Parquet files can
be analyzed without conversion:

```r
# install.packages(c("arrow", "data.table"))
library(arrow)
library(data.table)

bars <- as.data.table(read_parquet("data/market/aapl/1Y.parquet"))
setorder(bars, time)
bars[, sma20 := frollmean(close, n = 20, align = "right")]
print(tail(bars))
```

Data are always sourced externally, and data accuracy is limited by the
provider's feed, including delayed bars, missing corporate actions, and
instrument coverage. Avoid training or backtesting on mixed adjusted and
unadjusted candle series.
