# NFL fitted parameters

Training seasons: **[2018, 2019, 2020, 2021, 2022, 2023]** · EPA window: 10 weeks · prior-season weight: 0.0

Constants are fitted here and consumed by `nfl_model.py`. The test seasons are never touched by this script — fitting on all seasons and then backtesting on a subset of them is the most common way a model reports an edge it does not have.

## result ~ edge_epa

- n = **1164**
- slope (EPA_TO_POINTS) = **15.38** pts per EPA/play (t = 6.20)
- intercept (HOME_FIELD) = **+1.68** pts
- R² = **0.0320** · residual SD = 14.07 pts

> v1 asserted EPA_TO_POINTS = 63.0 applied with a /2.0 divisor, an effective **31.5**. The fitted value is **15.38** — v1's projection was scaled roughly 2x too large, which inflated every edge it reported.

## line ~ edge_epa  (does the market already price this?)

- slope = **10.52** · R² = **0.0726**

> The diagnostic v1 never ran. The closing line loads on `edge_epa` nearly as hard as the outcome does, and with a tighter fit. The model's only input is already inside the price.

## Calibration of the assembled projection

- result ~ projection: slope **1.000**, intercept +0.00, R² 0.0320
- **PROJ_SHRINK = 1.000**

> Slope near 1: the projection's scale is calibrated. That says nothing about whether it beats the market — only that its magnitudes are not systematically inflated.

## (result − line) ~ (projection − line)  ← the number that matters

- slope = **+0.0942** (t = **1.57**)
- R² = **0.00213** · n = 1164

> This replaces v1's ATS correlation. It asks directly: when the model disagrees with the closing line, does the game land the model's way, and by how much per point of disagreement? Zero means the disagreement carries no information. One would mean the model is right and the market wrong, point for point.

> **t = 1.57 — not distinguishable from zero.** On the TRAINING data, which is the friendliest possible test, the model's disagreements carry no measurable information. No threshold, filter or band will recover signal that is not there.

## Values to paste into nfl_model.py

```python
PARAM_FIT_WINDOW = "2018-2023 train"
HOME_FIELD = 1.68
EPA_TO_POINTS = 15.38
PROJ_SHRINK = 1.0
```
