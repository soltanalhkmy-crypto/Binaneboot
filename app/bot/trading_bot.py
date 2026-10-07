import ccxt
import time
import os
import threading
from datetime import datetime, timedelta
from app.db.database import SessionLocal
from app.db.models import Settings, Trade
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class TradingBot:
    def __init__(self):
        self.api_key = os.getenv("BINANCE_API_KEY")
        self.api_secret = os.getenv("BINANCE_API_SECRET")

        # Spot Exchange
        self.spot_exchange = ccxt.binance({
            'apiKey': self.api_key,
            'secret': self.api_secret,
            'enableRateLimit': True,
        })

        # Futures Exchange
        self.futures_exchange = ccxt.binanceusdm({
            'apiKey': self.api_key,
            'secret': self.api_secret,
            'enableRateLimit': True,
        })

        self.running = False
        self.current_trade = None

    def get_settings(self):
        with SessionLocal() as db:
            return db.query(Settings).first()

    def scan_markets(self, target_funding_rate):
        logger.info("Scanning markets for funding rates...")
        try:
            self.futures_exchange.load_markets()
            funding_rates = []

            try:
                # Fetch all funding rates in one API call
                all_rates = self.futures_exchange.fetch_funding_rates()

                for symbol, info in all_rates.items():
                    if symbol.endswith(':USDT'):
                        rate = info.get('fundingRate', 0) * 100 # Convert to percentage
                        if rate >= target_funding_rate:
                            funding_rates.append({
                                'symbol': symbol,
                                'rate': rate,
                                'fundingTimestamp': info.get('fundingTimestamp')
                            })
            except Exception as e:
                logger.error(f"Error fetching funding rates: {e}")

            # Sort by highest rate
            funding_rates = sorted(funding_rates, key=lambda x: x['rate'], reverse=True)
            return funding_rates[0] if funding_rates else None

        except Exception as e:
            logger.error(f"Error scanning markets: {e}")
            return None

    def check_prices(self, symbol):
        base_symbol = symbol.replace(':USDT', '/USDT')
        try:
            spot_ticker = self.spot_exchange.fetch_ticker(base_symbol)
            futures_ticker = self.futures_exchange.fetch_ticker(symbol)

            spot_price = spot_ticker['last']
            futures_price = futures_ticker['last']

            # Futures price must be higher to avoid loss on entry (since we short futures and buy spot)
            # Actually, for cash and carry, if futures is higher, we short high and buy low.
            # We also need to factor in the spread and fees (approx 0.1% for spot, 0.05% for futures)
            fee_buffer = 0.0015 * spot_price

            if futures_price > (spot_price + fee_buffer):
                 return True, spot_price, futures_price
            return False, spot_price, futures_price
        except Exception as e:
            logger.error(f"Error checking prices: {e}")
            return False, 0, 0

    def execute_concurrent_orders(self, base_symbol, futures_symbol, amount, side):
        # side: "enter" -> Spot Buy, Futures Sell
        # side: "exit" -> Spot Sell, Futures Buy

        spot_order_result = {}
        futures_order_result = {}

        def spot_task():
            try:
                if side == "enter":
                    spot_order_result['result'] = self.spot_exchange.create_market_buy_order(base_symbol, amount)
                else:
                    spot_order_result['result'] = self.spot_exchange.create_market_sell_order(base_symbol, amount)
                spot_order_result['success'] = True
            except Exception as e:
                spot_order_result['success'] = False
                spot_order_result['error'] = str(e)

        def futures_task():
            try:
                if side == "enter":
                    futures_order_result['result'] = self.futures_exchange.create_market_sell_order(futures_symbol, amount)
                else:
                    futures_order_result['result'] = self.futures_exchange.create_market_buy_order(futures_symbol, amount)
                futures_order_result['success'] = True
            except Exception as e:
                futures_order_result['success'] = False
                futures_order_result['error'] = str(e)

        t1 = threading.Thread(target=spot_task)
        t2 = threading.Thread(target=futures_task)

        t1.start()
        t2.start()

        t1.join()
        t2.join()

        return spot_order_result, futures_order_result

    def enter_trade(self, symbol_info, settings):
        futures_symbol = symbol_info['symbol']
        base_symbol = futures_symbol.replace(':USDT', '/USDT')

        logger.info(f"Checking prices for {futures_symbol} before entry.")
        is_safe, spot_price, futures_price = self.check_prices(futures_symbol)

        if not is_safe:
            logger.info("Prices not safe for entry (Futures price not high enough). Skipping.")
            return False

        amount_usdt = settings.trade_amount
        # Calculate amount of coin to buy/sell
        amount = amount_usdt / spot_price

        # Load markets to get min amount limits and precision
        self.spot_exchange.load_markets()
        market = self.spot_exchange.market(base_symbol)
        amount = self.spot_exchange.amount_to_precision(base_symbol, amount)
        amount = float(amount)

        logger.info(f"Executing entry: Buy Spot, Short Futures for {amount} {base_symbol}")
        spot_res, futures_res = self.execute_concurrent_orders(base_symbol, futures_symbol, amount, "enter")

        with SessionLocal() as db:
            trade = Trade(
                symbol=futures_symbol,
                spot_entry_price=spot_price, # Roughly, should get from order result in prod
                futures_entry_price=futures_price,
                amount=amount
            )

            if not spot_res['success'] or not futures_res['success']:
                logger.error("Entry failed. Initiating safety rollback.")
                trade.status = "failed"
                trade.error_message = f"Spot: {spot_res.get('error', 'OK')} | Futures: {futures_res.get('error', 'OK')}"

                # Safety Protocol: Close whatever succeeded
                if spot_res['success']:
                    logger.info("Selling Spot to rollback...")
                    self.spot_exchange.create_market_sell_order(base_symbol, amount)
                if futures_res['success']:
                    logger.info("Buying Futures to rollback...")
                    self.futures_exchange.create_market_buy_order(futures_symbol, amount)

                db.add(trade)
                db.commit()
                return False

            # Update actual prices from order results
            if 'average' in spot_res['result']: trade.spot_entry_price = spot_res['result']['average']
            if 'average' in futures_res['result']: trade.futures_entry_price = futures_res['result']['average']

            db.add(trade)
            db.commit()
            self.current_trade = trade.id
            return True

    def exit_trade(self):
        if not self.current_trade:
            return

        with SessionLocal() as db:
            trade = db.query(Trade).filter(Trade.id == self.current_trade).first()
            if not trade or trade.status != "open":
                return

            futures_symbol = trade.symbol
            base_symbol = futures_symbol.replace(':USDT', '/USDT')
            amount = trade.amount

            logger.info(f"Executing exit for {futures_symbol}")
            spot_res, futures_res = self.execute_concurrent_orders(base_symbol, futures_symbol, amount, "exit")

            trade.exit_time = datetime.utcnow()

            if spot_res['success'] and futures_res['success']:
                trade.status = "closed"
                # Update prices
                spot_exit_price = spot_res['result'].get('average', 0)
                futures_exit_price = futures_res['result'].get('average', 0)

                trade.spot_exit_price = spot_exit_price
                trade.futures_exit_price = futures_exit_price

                # Approximate profit (Spot Loss + Futures Gain + Funding (assume we got it))
                # For a real bot, we would fetch the actual funding fee from account history
                # This is a simplified profit calculation excluding fees and exact funding
                spot_pnl = (spot_exit_price - trade.spot_entry_price) * amount
                futures_pnl = (trade.futures_entry_price - futures_exit_price) * amount
                trade.profit_usdt = spot_pnl + futures_pnl
            else:
                trade.status = "failed"
                trade.error_message = f"Exit Error: Spot: {spot_res.get('error', 'OK')} | Futures: {futures_res.get('error', 'OK')}"

            db.commit()
            self.current_trade = None

    def run_cycle(self):
        settings = self.get_settings()
        if not settings or not settings.bot_active:
            return

        if self.current_trade:
            # Check if it's time to exit
            # We exit when funding timestamp is reached + exit_safe_seconds
            # For simplicity in this logic, we will fetch the next funding time
            with SessionLocal() as db:
                trade = db.query(Trade).filter(Trade.id == self.current_trade).first()
                if not trade:
                    self.current_trade = None
                    return

                try:
                    info = self.futures_exchange.fetch_funding_rate(trade.symbol)
                    funding_time_ms = info['fundingTimestamp']
                    funding_time = datetime.utcfromtimestamp(funding_time_ms / 1000.0)

                    exit_time = funding_time + timedelta(seconds=settings.exit_safe_seconds)

                    if datetime.utcnow() >= exit_time:
                        self.exit_trade()
                except Exception as e:
                    logger.error(f"Error checking exit time: {e}")
        else:
            # We are not in a trade, look for one
            opportunity = self.scan_markets(settings.target_funding_rate)
            if opportunity:
                funding_time_ms = opportunity['fundingTimestamp']
                funding_time = datetime.utcfromtimestamp(funding_time_ms / 1000.0)
                time_to_funding = (funding_time - datetime.utcnow()).total_seconds() / 60.0

                logger.info(f"Found opportunity: {opportunity['symbol']} at {opportunity['rate']}%. Time to funding: {time_to_funding:.2f} mins")

                # Enter if within the entry window (e.g., <= 15 minutes before)
                if 0 < time_to_funding <= settings.entry_time_minutes:
                    self.enter_trade(opportunity, settings)
                else:
                    logger.info("Outside entry window. Waiting...")

    def start(self):
        self.running = True
        logger.info("Trading bot background thread started.")
        while self.running:
            try:
                self.run_cycle()
                time.sleep(30) # Check every 30 seconds
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                time.sleep(60)

    def stop(self):
        self.running = False
        logger.info("Trading bot background thread stopped.")

bot_instance = TradingBot()
