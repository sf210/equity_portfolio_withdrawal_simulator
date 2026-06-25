# Motivation for the Equity Portfolio Withdrawal Simulator

This project grew out of my own retirement planning. There are many algorithms
for managing cash flow during retirement. The most famous is Bill Bengen's, from
his 1994 paper [Determining Withdrawal Rates Using Historical
Data](https://web.archive.org/web/20120417135441/http://www.retailinvestor.org/pdf/Bengen1.pdf),
now known as the **"4% Rule."** Many others have been published since, and a good
number can be modeled at [F1Calc](https://f1calc.app). Nearly all of them work by
drawing down a portfolio of stocks, bonds, and cash. These methods can be
back-tested against history, or stress-tested with parametric models of the
securities markets, but none comes with a guarantee. You can tune the parameters
to make the investments and withdrawals more aggressive or more conservative,
yet without the certainty that you will not outlive your money, it is hard to
resist panic-selling in a deep down market.

## Sharkansky's spending rule

In 2024, Stefan Sharkansky published [The Only Other Spending Rule Article You
Will Ever
Need](https://www.tandfonline.com/doi/epdf/10.1080/0015198X.2025.2541567?needAccess=true).
His method has the following steps:

1. **Determine how much annual income you need.** This may be less than you would
   ideally like, but it should be enough that — knowing it will arrive every year,
   with a raise to match inflation — you can resist panic-selling when stocks drop
   sharply from their all-time high.
2. **Lock in that needed income.** Add up what you will receive each year from
   Social Security and any other pension that provides an annual cost-of-living
   adjustment. If that falls short of your minimum, buy a TIPS ladder to close the
   gap.
3. **Invest the remainder in equities** — the portion of your assets you are
   willing to spend down in retirement.
4. **Each year, withdraw from the equity portfolio** up to the amount a fixed-term
   annuity lasting as long as your life expectancy would pay. For example, if you
   are 67 and determine that your life expectancy is 85, calculate the payout
   percentage of an annuity with a 22-year term.

The appeal of Sharkansky's method is that Treasury bonds and Social Security
backstop the funding of your needs: even if the stock market went to zero, your
essential needs would still be met.

## My modifications

I wanted to make a few modifications to the method and model them out.

1. **Use a life annuity instead of a fixed-term annuity.** Rather than computing
   payments for a fixed-term annuity, look up an estimate of what you would be
   paid annually for a *life* annuity, which keeps paying for as long as you live.
   Estimated quotes are available at
   [immediateannuities.com](https://www.immediateannuities.com/).
2. **Add a capital-preservation rule.** You may not need the money from your
   equity portfolio, but you also don't want it to run out. Cap how much you spend
   from the portfolio relative to your first year's withdrawal, adjusted for
   inflation — for example, allow yourself no more than 30% above what you took out
   in real terms in the first year. If equities rise sharply you can take less
   than the indicated amount to preserve capital; then, when the market comes
   down, you are less likely to have to take a pay cut.

## The simulator

The scripts `montecarlo.py` and `montecarlo_gui.py` run simulations so you can
test different parameters and assumptions. Inflation is a big assumption, and the
latest version of the software simulates inflation, interest rates, and
equity-market returns together. Several parameters can be tuned, and you can also
choose how many years to simulate.
