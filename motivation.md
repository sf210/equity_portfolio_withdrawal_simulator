Motivation for the Equity Portfolio Withdrawal Simulator

This project came from a process of financial planning for retirment. There are many algorithms for planning cash flow during retirement. The most famous one is from Bill Bengen in his 1994 paper [Determining Withdrawal Rates Using Historical Data](https://web.archive.org/web/20120417135441/http://www.retailinvestor.org/pdf/Bengen1.pdf), which is knows as "The 4% Rule". Since then other algorithms have been published. Many of them are available for modeling at [F1Calc](f1calc.app). All of them are based on drawing from a portfolio of stocks, bonds, and cash. While these methods can be back-tested, or tested using parametric specifications of securities markets, there is no guarantee any of them will work. You can adjust parameters to make the investments and withdrawal rates more aggressive or conservative, but without knowing for certain that you will not outlive your funds, it can be hard not to panic sell in a big downmarket.

In 2024, Stefan Sharkansky published [The Only Other Spending Rule Article You Will Ever Need](https://www.tandfonline.com/doi/epdf/10.1080/0015198X.2025.2541567?needAccess=true). Sharkansky's method has the folling steps:

1. Determine how much annual income you need. This may be less than what you would ideally like, but it should be enough so that if you know you will have that coming and get an raise to match inflation every year, that you will be able to resist panic selling when stocks have a large drop from their all-time high.
2. Lock in you needed income. Determine how much you will get each year from Social Security, an any other pension that provides annual cost-of-living adjustments. If that falls short of your minimum, then buy a TIPS Ladder to close the gap.
3. With the remainder of your assets that you want to be able to spend in retirement, invest them in equities.
4. Each year you can withdraw from your equity portfolio up to the amount you would get from a fixed annuity which lasts as long as your life expectance. For example, if you are 67 and you determine that your life expectancy is 85, then calculate the percentage of the annuity investment that would pay out for a 22 year contract.

The appeal of Sharkansky's method is the safety of treasury bonds and social security back the funding of your needs. Even if the stock market went to zero, you would have your needs met.

I wanted to make some modifications to the method and model them out.

1. Instead of computing payments for a fixed annuity, look up an estimate for what you would get paid annually if you purchased a life annuity. A life annuity keeps making payments for as long as you live. Estimated quotes are available at immediateannuities.com.
2. Capital preseration rule. While you do not need money from your equity portfolio, you do not want it to run out either. Have a rule that limits how much you will spend from the equity portfolio relative to your first year of withdrawing adjusted for inflation. For example, you could allow yoursef no more than 30% above what you took out in real terms in the first year. If the equity market goes up sharply you could take less than the indicated amount to preserve capital. Then when the market came down, you would be less likely to have to take a pay cut.

The sripts montecarlo.py and montecarlo_gui.py. Run simulations so you can test different parameters and assumptions. Inflation is a big assumption. The lasest version of the software simulates inflation, interest rates, and equity market changes. There are different parameters that can be tuned for this. You can also determine the number of years you want to simulate.
