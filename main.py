import ccxt, os, json, pandas as pd
from datetime import datetime

SYMBOL='DOGE/USDT'
exchange=ccxt.mexc({'apiKey':os.getenv('MEXC_API_KEY'),'secret':os.getenv('MEXC_SECRET'),'enableRateLimit':True})

def load_entry():
    try:
        if os.path.exists('entry.json'):
            return json.load(open('entry.json'))['entry']
    except: pass
    return None

def save_entry(p):
    json.dump({'entry':p,'time':str(datetime.now())}, open('entry.json','w'))

c=exchange.fetch_ohlcv(SYMBOL,'5m',limit=100)
df=pd.DataFrame(c,columns=['t','o','h','l','c','v'])
df['e9']=df['c'].ewm(span=9).mean()
df['e21']=df['c'].ewm(span=21).mean()
last,prev=df.iloc[-1],df.iloc[-2]
price=float(last['c'])
cross_up=prev['e9']<=prev['e21'] and last['e9']>last['e21']
cross_down=prev['e9']>=prev['e21'] and last['e9']<last['e21']

bal=exchange.fetch_balance()
usdt=float(bal.get('USDT',{}).get('free',0) or 0)
doge=float(bal.get('DOGE',{}).get('free',0) or 0)
entry=load_entry()

print(f"{datetime.now()} | H:{price:.6f} E9:{last['e9']:.6f} E21:{last['e21']:.6f} | UP:{cross_up} DOWN:{cross_down}")
print(f"USDT:{usdt:.2f} DOGE:{doge:.4f} Entry:{entry}")

if doge*price>1 and entry:
    if price<=entry*0.97:
        amt=exchange.amount_to_precision(SYMBOL,doge)
        exchange.create_market_sell_order(SYMBOL,amt)
        save_entry(None)
        print(">> JUAL SL 3%")
    elif cross_down:
        amt=exchange.amount_to_precision(SYMBOL,doge)
        exchange.create_market_sell_order(SYMBOL,amt)
        save_entry(None)
        print(">> JUAL TP CROSS")
    else: print(">> HOLD DOGE")
elif cross_up:
    if usdt>=1.1:
        cost=round(usdt*0.95,2)
        o=exchange.create_market_buy_order(SYMBOL,cost)
        save_entry(float(o.get('average') or price))
        print(f">> BUY {cost} USDT @ {price}")
    else: print(f">> GAGAL BUY, USDT {usdt} kurang dari 5")
else: print(">> HOLD, tunggu cross_up")
