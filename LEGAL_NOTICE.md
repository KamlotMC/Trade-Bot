# Legal Notice & Compliance Information

## Meowcoin Market Maker Bot — MEWC/USDT on NonKYC Exchange

**Last Updated: February 2026**

---

## 1. Nature of This Software

This software is an **automated market-making tool** that places resting limit
orders on both sides of the MEWC/USDT order book on the NonKYC cryptocurrency
exchange. Market making is a well-established, legitimate practice in financial
markets — market makers provide liquidity to an exchange by continuously
quoting buy and sell prices.

This bot:
- Places **genuine, two-sided limit orders** that are intended to be filled.
- Does **NOT** engage in wash trading (trading with itself).
- Does **NOT** engage in spoofing or layering (placing orders with intent to cancel
  before execution to manipulate price).
- Does **NOT** engage in front-running or insider trading.
- Does **NOT** engage in pump-and-dump schemes.

---

## 2. Regulatory Landscape

### 2.1 United States
- The CFTC (Commodity Futures Trading Commission) and SEC (Securities and
  Exchange Commission) regulate trading activity in the US. Market making
  itself is legal; however, certain manipulative practices are prohibited
  under the Commodity Exchange Act (CEA) and the Securities Exchange Act.
- **Spoofing** is explicitly illegal under the Dodd-Frank Act (7 U.S.C. § 6c(a)(5)).
- If MEWC is classified as a security, additional registration requirements
  may apply. Consult a securities attorney.
- US users should be aware of FinCEN requirements. Operating as a money
  services business (MSB) may require registration.

### 2.2 European Union
- Under MiCA (Markets in Crypto-Assets Regulation), market manipulation
  in crypto-asset markets is prohibited (Article 91). Legitimate market making
  is permitted.
- Market makers on EU-regulated platforms may need to comply with specific
  obligations.

### 2.3 United Kingdom
- The FCA (Financial Conduct Authority) regulates crypto-asset activities.
  Market manipulation provisions apply under the Financial Services and
  Markets Act 2000.

### 2.4 Other Jurisdictions
- Cryptocurrency regulation varies widely. Some jurisdictions ban or restrict
  cryptocurrency trading entirely. It is **your responsibility** to determine
  whether operating this bot is lawful in your jurisdiction.

---

## 3. NonKYC Exchange Considerations

The NonKYC exchange operates without mandatory Know-Your-Customer (KYC)
verification. Users should be aware that:

- Trading on non-KYC platforms may be restricted or prohibited in certain
  jurisdictions (e.g., platforms may be subject to sanctions, or local law
  may require KYC for all exchange operations).
- You remain personally responsible for any applicable tax reporting
  obligations (capital gains, income tax on trading profits, etc.).
- Anti-Money Laundering (AML) laws still apply to individual users
  regardless of whether the exchange enforces KYC.

---

## 4. Tax Obligations

Automated trading generates potentially large numbers of taxable events.
You are responsible for:

- Tracking all trades and calculating capital gains/losses.
- Reporting trading income to your tax authority.
- Maintaining records of all transactions for the required retention period.

Consider using cryptocurrency tax software to assist with record-keeping.

---

## 5. Risk Disclosures

### Financial Risk
- Cryptocurrency markets are highly volatile. You may lose part or all of
  your invested capital.
- Market-making strategies can incur losses due to adverse selection
  (being filled on the wrong side of a directional move).
- Illiquid markets (such as MEWC/USDT) carry higher risk of slippage and
  wider-than-expected effective spreads.

### Technical Risk
- Software bugs, network failures, exchange outages, or API changes can
  result in unintended order placement or failure to cancel orders.
- Always start with small position sizes and monitor the bot closely.
- Use the risk management parameters (stop-loss, daily loss limit, exposure
  caps) configured in `config.yaml`.

### Exchange Risk
- The NonKYC exchange, like all exchanges, carries counterparty risk. Funds
  held on the exchange may be lost due to hacks, insolvency, or other events.
- Only deposit funds you can afford to lose entirely.

---

## 6. Anti-Manipulation Compliance

This bot is specifically designed to **avoid** market manipulation:

| Practice         | Status    | How                                          |
|-----------------|-----------|----------------------------------------------|
| Wash Trading    | PREVENTED | Bot only places resting limit orders; it never trades with itself. |
| Spoofing        | PREVENTED | All orders are genuine and intended to be filled. Orders are only cancelled as part of the regular refresh cycle. |
| Layering        | PREVENTED | Multi-level orders are genuine liquidity at progressively deeper levels. |
| Front-Running   | PREVENTED | Bot has no access to other users' pending orders beyond the public orderbook. |
| Pump & Dump     | PREVENTED | Bot provides two-sided liquidity; it does not accumulate and dump positions. Inventory skew actively rebalances. |

---

## 7. Limitation of Liability

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE, AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES, OR OTHER
LIABILITY ARISING FROM THE USE OF THIS SOFTWARE.

---

## 8. User Acknowledgement

By running this software, you acknowledge that:

1. You have read and understood this Legal Notice in its entirety.
2. You accept full responsibility for ensuring compliance with all applicable
   laws and regulations in your jurisdiction.
3. You understand the financial risks involved in cryptocurrency trading.
4. You will not use this software for any illegal purpose, including but not
   limited to market manipulation, money laundering, or sanctions evasion.
5. You will configure and monitor the bot's risk parameters appropriately.

---

*This document does not constitute legal advice. Consult a qualified attorney
for guidance specific to your situation and jurisdiction.*
