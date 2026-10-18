# Vendored pyMMAopt

These files come from [LLNL/pyMMAopt](https://github.com/LLNL/pyMMAopt/tree/934c0f304354fcb9430e2c326dedf557e3705eab), commit `934c0f304354fcb9430e2c326dedf557e3705eab` (2021-08-11), the last revision before the [bridge article](https://www.migueloptimization.com/posts/open-source/) was published on 2021-11-21.

The upstream GPL-2.0 `LICENSE` and `NOTICE` are included unchanged. The upstream `__about__.py` also remains unchanged, including its older metadata. `UPSTREAM.json` records source hashes and any compatibility patches; the optimization algorithm and parameters must be preserved.

The bridge adds `vendor/` to its Python import path to use this package. NumExpr remains a runtime dependency, as in the original implementation.
