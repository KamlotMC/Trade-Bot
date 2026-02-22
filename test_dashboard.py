from dashboard.backend import NonKYCClient, DataStore, LogParser, PnLCalculator

client = NonKYCClient()
print("Price:", client.get_ticker())

store = DataStore()
store.add_snapshot(1000000, 50, 0.000037, 87)

parser = LogParser()
print("Recent events:", parser.parse(50))

calc = PnLCalculator(store)
print("P&L:", calc.get_current_pnl())
