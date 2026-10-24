### Fixed
- A payment with its mailed receipt is counted once. When you accepted a receipt in `review receipts`
  and your payment source then delivered the same payment, the Day's spend, `rollup ledger`, `rollup
  money`, a trip's spend and an org's money counted it twice until you retracted the receipt. They now
  count the source's line alone, on its own day, and name the receipt as its evidence (`1 with its
  receipt`). One card line covers one receipt, the nearest in time, in the queue's covered rows too.
- A trip's spend reads a corrected transaction in the place of the line it supersedes, as the ledger
  does, instead of counting both.
- A receipt's merchant is never a raw email address: a sender with no name and no registered domain
  (`x@localhost`, an address with no domain) is `a sender`, and two such senders are two merchants.
