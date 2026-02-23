from dashboard.backend import NonKYCClient, DataStore, LogParser, PnLCalculator

client = NonKYCClient()
print("Price:", client.get_ticker())

store = DataStore()
store.add_snapshot(1000000)

parser = LogParser()
print("Errors:", parser.get_errors(50))
print("Status:", parser.get_bot_status(50))

calc = PnLCalculator(store)
print("P&L:", calc.get_current_pnl())
