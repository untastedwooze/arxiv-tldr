<!--
Interest Profile: the sole reference Triage judges each paper against.
Write in plain prose; be specific. Triage quality depends mostly on this file.
-->

## Who I am

I am a private investor building my own quantitative models for long-horizon personal
investing: deciding what to hold, in what weights, and how to protect the portfolio against
large drawdowns. I trade US equities and globally traded ETFs (equity, bond, commodity, gold,
and a small crypto sleeve) at daily-or-slower horizons. I do not trade intraday. I want papers
that could change what I build, not papers that are merely about finance.

My data: free or cheap public data (daily prices, FRED, Ken French factor data, volatility
indices such as VIX, VIX3M and SKEW) plus minute-level price and volume bars for every US-listed
stock. I do not have historical option chains or implied-volatility surfaces, institutional
holdings, or paid alternative data. I implement models in Python.

## Core interests

Portfolio allocation and construction: choosing weights across assets and asset classes,
risk parity and risk budgeting, covariance and risk estimation for allocation, rebalancing
rules, drawdown control, and risk measures used to size positions.

Empirical asset pricing and return prediction: constructing and testing factors, replicating
anomalies and checking which survive costs and out-of-sample tests, estimating risk premia,
and factor timing, at horizons of weeks to months. Machine-learning methods count here only
when they meet the evidence standard below.

Long-term hedging: protecting a portfolio against crashes and drawdowns with protective puts,
collars and tail hedges, and comparing these with alternatives such as trend-following,
defensive factor tilts, and bond or gold overlays. Papers about hedging strategies, not about
pricing derivatives.

Financial econometrics: predictive regressions, forecast evaluation, and methods that guard
against fooling yourself in backtests, such as backtest-overfitting corrections, the deflated
Sharpe ratio and multiple-testing adjustments.

## Adjacent interests

These score high only when the work is strong and directly applicable to the core interests.

- Statistical methodology applied to financial or economic data: covariance and shrinkage
  estimation, robust estimation with small samples, forecasting methods. Not statistics in
  general.
- Measures built from intraday data (realized volatility and covariance, jumps, intraday-derived
  return signals), but only when they feed a daily-or-longer decision such as risk forecasting,
  hedge sizing or cross-sectional return prediction.
- Extreme value theory and tail-risk measures (expected shortfall, CVaR, tail dependence);
  score high when applied to sizing drawdown protection or hedges.
- Regime detection and change-point methods applied to asset returns, volatility or
  correlations.
- Crypto as an asset class within a portfolio: its diversification value, correlation with
  traditional assets, and position sizing.

## What raises or lowers a score

Implementability raises the score: a paper I could replicate with the data listed above and
standard Python tools ranks higher than an equally relevant paper that needs data I lack.
Hedging papers that work from index-level prices, volatility indices or volatility forecasts
count as replicable; papers needing a history of option chains or implied-volatility surfaces
do not, but are not ruled out.

Evidence standard for every empirical paper: a genuine out-of-sample test, comparison with
simple baselines (equal weighting, buy-and-hold, linear factor models), and transaction costs
or turnover where trading is involved. A paper missing these scores no higher than 6.

Market: evidence on US equities or multi-asset ETFs counts fully. A paper tested only on a
non-US single-stock market (for example Chinese A-shares) scores no higher than 6 unless the
method clearly carries over and could be rerun on US data.

## Exclusions

Score these 1 to 3, even when they look superficially related.

- Purely theoretical, proof-heavy papers with no empirical test or practical application.
- Theoretical asset pricing and derivatives pricing: equilibrium models, stochastic discount
  factor theory, and option pricing under new stochastic models (rough volatility, Lévy
  processes) or their calibration, unless the paper ends in an investment or hedging rule
  tested on data.
- DeFi, blockchain technology, token pricing and crypto trading strategies.
- Generic machine-learning papers with no finance angle, and deep-learning price forecasting
  of a single asset or index.
- Large language models or agents for finance (news-sentiment trading, LLM analysts), unless
  the paper builds a return signal that meets the evidence standard.
- ESG and climate finance, unless it is a factor or risk premium tested empirically.
- Insurance and actuarial science, banking, credit risk, corporate finance, household finance.
- Market making, optimal execution, order-book models, high-frequency and intraday trading.
- Agent-based market simulations and econophysics.
- Sports betting, prediction markets and gambling.
- Policy, regulation, and macroeconomic forecasting not tied to asset returns.
- Statistics applied to medicine, biology, epidemiology or other fields unrelated to finance.

## Scoring guide

Use the whole scale and be stingy with high scores; most on-topic papers belong in the middle.

- 9-10: a core interest, implementable with my data, meeting the evidence standard, with a
  clear payoff for my models. Expect only a few per week.
- 7-8: a core interest with weaker feasibility or evidence, or an adjacent interest that is
  unusually strong and directly applicable.
- 4-6: on-topic but incremental, mainly theoretical, not feasible with my data, failing the
  evidence standard, or tested only on a non-US single-stock market.
- 1-3: loosely related topics, anything listed under Exclusions, and everything else.
